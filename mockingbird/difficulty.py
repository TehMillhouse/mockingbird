"""Difficulty scoring shared by data bucketing and generation-time rejection.

The raw score is 0..100. Bucket thresholds are calibrated per style to the quintiles
of the training data and stored next to the model (see `calibrate`).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .schema import Phrase
from .theory import MINOR_RAISED_PCS, bar_ticks, beat_ticks, is_diatonic, scale_degree, strong_beat_ticks
from .tokenizer import merge_ties

DEFAULT_THRESHOLDS = [15.0, 28.0, 42.0, 58.0]


def features(phrase: Phrase) -> dict[str, float]:
    notes = merge_ties(phrase.notes)
    pitched = [n for n in notes if n.pitch is not None]
    if len(pitched) < 2:
        return {k: 0.0 for k in ("interval", "leap", "bigleap", "chrom", "rhythm", "nonchord")}
    bt = bar_ticks(phrase.meter)
    beat = beat_ticks(phrase.meter)
    strong = set(strong_beat_ticks(phrase.meter))
    n_bars = max(1.0, phrase.total_ticks() / bt)

    ivs = np.array([abs(b.pitch - a.pitch) for a, b in zip(pitched, pitched[1:])])
    f_interval = min(float(ivs.mean()), 6.0) / 6.0
    f_leap = float((ivs > 4).mean())
    f_bigleap = min(float((ivs >= 8).sum()) / n_bars, 1.0)

    chrom = 0.0
    for n in pitched:
        if not is_diatonic(n.pitch, phrase.mode, allow_raised=False):
            chrom += 0.5 if (phrase.mode == "minor" and n.pitch % 12 in MINOR_RAISED_PCS) else 1.0
    f_chrom = chrom / len(pitched)

    durations = {n.duration for n in notes}
    pos = (-phrase.pickup_ticks) % bt if phrase.pickup_ticks else 0
    offbeat = 0
    nonchord = 0
    strong_count = 0
    dotted_or_tied = 0
    for n in phrase.notes:
        in_bar = pos % bt
        if n.pitch is not None:
            if in_bar % beat != 0:
                offbeat += 1
            if in_bar in strong:
                strong_count += 1
                deg = scale_degree(n.pitch, phrase.mode)
                if deg not in (1, 3, 5):
                    nonchord += 1
        if n.tie or n.duration in (9, 18, 36, 72):
            dotted_or_tied += 1
        pos += n.duration
    f_rhythm = min(1.0, (len(durations) - 1) / 5 * 0.4
                   + offbeat / len(pitched) * 0.4
                   + min(dotted_or_tied / n_bars, 1.0) * 0.2)
    f_nonchord = nonchord / strong_count if strong_count else 0.0
    return {"interval": f_interval, "leap": f_leap, "bigleap": f_bigleap, "chrom": f_chrom,
            "rhythm": f_rhythm, "nonchord": f_nonchord}


WEIGHTS = {"interval": 25, "leap": 15, "bigleap": 10, "chrom": 20, "rhythm": 20, "nonchord": 10}


def score(phrase: Phrase) -> float:
    f = features(phrase)
    return float(sum(WEIGHTS[k] * f[k] for k in WEIGHTS))


class Thresholds:
    """Per-style bucket edges. Falls back to the defaults for unknown styles."""

    def __init__(self, per_style: dict[str, list[float]] | None = None):
        self.per_style = per_style or {}

    def bucket(self, s: float, style: str) -> int:
        edges = self.per_style.get(style, DEFAULT_THRESHOLDS)
        return 1 + int(np.searchsorted(np.array(edges), s, side="right"))

    def bucket_range(self, level: int, style: str) -> tuple[float, float]:
        edges = [0.0] + list(self.per_style.get(style, DEFAULT_THRESHOLDS)) + [100.0]
        return edges[level - 1], edges[level]

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.per_style, indent=1))

    @classmethod
    def load(cls, path: Path) -> "Thresholds":
        if not path.exists():
            return cls()
        return cls(json.loads(path.read_text()))


def calibrate(scores_by_style: dict[str, list[float]]) -> Thresholds:
    per_style = {}
    for style, vals in scores_by_style.items():
        if len(vals) < 50:
            continue
        per_style[style] = [float(x) for x in np.percentile(vals, [20, 40, 60, 80])]
    return Thresholds(per_style)
