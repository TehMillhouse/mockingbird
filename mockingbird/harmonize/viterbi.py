"""Fit one chord per segment to a frame-space melody with a Viterbi search.

Emission: beat-weighted share of melody notes in a segment that are chord tones
(passing tones between chord tones count a little). Transition: a hand-set functional
harmony table plus a bass-motion penalty. First segment is I (or V for a pickup); when
the melody is an ending, the last segment is nudged towards the tonic and the one
before it towards the dominant.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..schema import Chord, Note
from ..theory import bar_ticks, beat_ticks, strong_beat_ticks
from .chords import ChordType, alphabet

OTHER = -2.5  # log-prob for transitions not listed below
REPEAT = -0.5
SECONDARY_PRIOR = -1.5
END_TONIC_BONUS = 0.8
END_DOMINANT_BONUS = 0.4

MAJOR_T: dict[str, dict[str, float]] = {
    "I": {"IV": -0.7, "V": -0.7, "V7": -1.0, "vi": -1.2, "ii": -1.2, "iii": -2.0, "vii°": -2.2, "V/V": -2.0, "V/ii": -2.2},
    "ii": {"V": -0.4, "V7": -0.6, "vii°": -1.8, "IV": -2.0, "I": -2.0},
    "iii": {"vi": -0.8, "IV": -1.0, "ii": -1.5, "I": -1.8},
    "IV": {"V": -0.6, "I": -0.9, "ii": -1.2, "V7": -0.9, "vii°": -1.8, "vi": -2.0},
    "V": {"I": -0.3, "vi": -1.3, "V7": -1.0, "IV": -2.2, "ii": -2.5},
    "V7": {"I": -0.2, "vi": -1.3},
    "vi": {"ii": -0.8, "IV": -0.8, "V": -1.2, "iii": -1.8, "I": -1.8},
    "vii°": {"I": -0.3, "iii": -1.8},
    "V/V": {"V": -0.2, "V7": -0.4},
    "V/ii": {"ii": -0.2},
}

MINOR_T: dict[str, dict[str, float]] = {
    "i": {"iv": -0.7, "V": -0.7, "V7": -1.0, "VI": -1.2, "ii°": -1.3, "III": -1.6, "VII": -1.6, "vii°": -2.2, "V/iv": -2.0, "V/V": -2.2},
    "ii°": {"V": -0.4, "V7": -0.6, "vii°": -1.8, "i": -2.0},
    "III": {"VI": -0.8, "iv": -1.0, "VII": -1.2, "i": -1.5},
    "iv": {"V": -0.6, "i": -0.9, "ii°": -1.4, "V7": -0.9, "VII": -1.8, "VI": -2.0},
    "V": {"i": -0.3, "VI": -1.3, "V7": -1.0, "iv": -2.2},
    "V7": {"i": -0.2, "VI": -1.3},
    "VI": {"ii°": -1.0, "iv": -0.8, "V": -1.2, "III": -1.5, "VII": -1.5, "i": -1.8},
    "VII": {"III": -0.5, "i": -1.5, "iv": -1.8},
    "vii°": {"i": -0.3},
    "V/iv": {"iv": -0.2},
    "V/V": {"V": -0.2, "V7": -0.4},
}


@dataclass
class Segment:
    start: int
    duration: int
    weights: list[tuple[int, float, int | None, int | None]]  # (pc, weight, prev_pitch, next_pitch)
    is_pickup: bool = False


def segment_ticks(meter: str) -> int:
    bt = bar_ticks(meter)
    return bt // 2 if bt >= 96 else bt


def build_segments(notes: list[Note], meter: str, pickup_ticks: int) -> list[Segment]:
    bt = bar_ticks(meter)
    seg_len = segment_ticks(meter)
    total = sum(n.duration for n in notes)
    bounds: list[tuple[int, int, bool]] = []
    t = 0
    if pickup_ticks:
        bounds.append((0, pickup_ticks, True))
        t = pickup_ticks
    while t < total:
        bounds.append((t, min(seg_len, total - t), False))
        t += seg_len
    strong = set(strong_beat_ticks(meter))
    beat = beat_ticks(meter)
    pitched_idx = [i for i, n in enumerate(notes) if n.pitch is not None]
    segments = [Segment(s, d, [], p) for s, d, p in bounds]
    pos = 0
    for i, n in enumerate(notes):
        if n.pitch is not None:
            in_bar = (pos - pickup_ticks) % bt if pickup_ticks else pos % bt
            w_beat = 2.0 if in_bar in strong else 1.0 if in_bar % beat == 0 else 0.5
            k = pitched_idx.index(i)
            prev_p = notes[pitched_idx[k - 1]].pitch if k > 0 else None
            next_p = notes[pitched_idx[k + 1]].pitch if k + 1 < len(pitched_idx) else None
            for seg in segments:
                overlap = min(pos + n.duration, seg.start + seg.duration) - max(pos, seg.start)
                if overlap > 0:
                    seg.weights.append((n.pitch % 12, w_beat * overlap, prev_p, next_p))
        pos += n.duration
    return segments


def emission(seg: Segment, chord: ChordType) -> float:
    if not seg.weights:
        return 0.0
    pcs = chord.pcs
    total = sum(w for _, w, _, _ in seg.weights)
    cover = 0.0
    for pc, w, prev_p, next_p in seg.weights:
        if pc in pcs:
            cover += w
        elif (prev_p is not None and next_p is not None and prev_p % 12 in pcs and next_p % 12 in pcs
              and abs(prev_p - next_p) <= 4):
            cover += 0.3 * w  # passing or neighbour tone between chord tones
    return math.log(cover / total + 0.05)


def transition(a: ChordType, b: ChordType, table: dict[str, dict[str, float]]) -> float:
    if a.roman == b.roman:
        lp = REPEAT
    else:
        lp = table.get(a.roman, {}).get(b.roman, OTHER)
    if b.is_secondary:
        lp += SECONDARY_PRIOR
    d = min((b.root_pc - a.root_pc) % 12, (a.root_pc - b.root_pc) % 12)
    if d > 5:
        lp -= 0.3 * (d - 5)
    return lp


def harmonize(notes: list[Note], meter: str, mode: str, pickup_ticks: int = 0, *,
              offset: int = 0, ending: bool = False) -> list[Chord]:
    """Return one Chord per segment. `offset` is the semitone shift from the frame to
    concert pitch, used only for the chord symbols."""
    segs = build_segments(notes, meter, pickup_ticks)
    if not segs:
        return []
    chords = alphabet(mode)
    table = MAJOR_T if mode == "major" else MINOR_T
    n = len(chords)
    tonic_idx = 0
    dom_idx = next(i for i, c in enumerate(chords) if c.roman == "V")
    neg = float("-inf")
    score = [[neg] * n for _ in segs]
    back = [[-1] * n for _ in segs]
    for j, c in enumerate(chords):
        if segs[0].is_pickup:
            start_lp = 0.0 if j in (tonic_idx, dom_idx) else -3.0
        else:
            start_lp = 0.0 if j == tonic_idx else -2.0 if j == dom_idx else -3.0
        score[0][j] = start_lp + emission(segs[0], c)
    for i in range(1, len(segs)):
        em = [emission(segs[i], c) for c in chords]
        if ending and i == len(segs) - 1:
            em[tonic_idx] += END_TONIC_BONUS
        if ending and i == len(segs) - 2:
            for j, c in enumerate(chords):
                if c.is_dominant:
                    em[j] += END_DOMINANT_BONUS
        for j, c in enumerate(chords):
            best, arg = neg, -1
            for k, prev in enumerate(chords):
                if score[i - 1][k] == neg:
                    continue
                s = score[i - 1][k] + transition(prev, c, table)
                if s > best:
                    best, arg = s, k
            score[i][j] = best + em[j]
            back[i][j] = arg
    j = max(range(n), key=lambda x: score[-1][x])
    path = [j]
    for i in range(len(segs) - 1, 0, -1):
        j = back[i][j]
        path.append(j)
    path.reverse()
    out: list[Chord] = []
    for seg, j in zip(segs, path):
        c = chords[j]
        out.append(Chord(start=seg.start, duration=seg.duration, root_pc=c.root_pc,
                         quality=c.quality, roman=c.roman, symbol=c.symbol(offset)))
    return out
