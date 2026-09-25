"""Cadence statistics for validation phrases versus generated levels.

    uv run python tools/cadence_metric.py [--levels 24]

For real endings in the validation set and for freshly generated levels it reports how
often the last note is the tonic (or another stable degree), how often the final note
is the longest in its bar, and how often the penultimate bar touches the leading tone
or supertonic (dominant preparation). For generated levels it also reports cadence
compliance: how often the forced final PAC, and each interior cadence type the model
chose, is what the classifier finds in the output.
"""
from __future__ import annotations

import argparse
import json
import os
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")

from mockingbird import tokenizer as tk  # noqa: E402
from mockingbird.data.segment import bars_of  # noqa: E402
from mockingbird.schema import GenerateRequest, Phrase  # noqa: E402
from mockingbird.harmonize.cadence import label_phrases  # noqa: E402
from mockingbird.theory import frame_offset, scale_degree  # noqa: E402


def cadence_features(ph: Phrase) -> dict[str, bool]:
    bars = bars_of(ph)
    last_bar = [n for n in tk.merge_ties(bars[-1]) if n.pitch is not None]
    pitched = [n for n in ph.notes if n.pitch is not None]
    if not last_bar or not pitched:
        return {}
    final = pitched[-1]
    deg = scale_degree(final.pitch, ph.mode)
    penult = [scale_degree(n.pitch, ph.mode) for n in (bars[-2] if len(bars) > 1 else []) if n.pitch is not None]
    return {
        "final_tonic": deg == 1,
        "final_stable": deg in (1, 3, 5),
        "final_longest": final.duration >= max(n.duration for n in last_bar),
        "penult_dominant_prep": any(d in (7, 2) for d in penult),
    }


def summarize(rows: list[dict], label: str) -> None:
    c = Counter()
    n = 0
    for r in rows:
        if r:
            n += 1
            for k, v in r.items():
                c[k] += bool(v)
    print(f"{label} (n={n}): " + ", ".join(f"{k} {100 * c[k] / max(1, n):.0f}%" for k in
                                           ("final_tonic", "final_stable", "final_longest", "penult_dominant_prep")))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", type=int, default=24)
    ap.add_argument("--val", type=Path, default=Path("data/processed/val.jsonl"))
    ap.add_argument("--model", type=Path, default=Path("models/melody-v1.pt"))
    ap.add_argument("--skip-val", action="store_true")
    args = ap.parse_args()

    by_style: dict[str, list[dict]] = {}
    with (args.val.open(encoding="utf-8") if not args.skip_val else open(os.devnull)) as f:
        for line in f:
            r = json.loads(line)
            if not r.get("is_ending"):
                continue
            ph = Phrase(**{k: v for k, v in r.items() if k != "difficulty_score"})
            by_style.setdefault(ph.style, []).append(cadence_features(ph))
    for style, rows in sorted(by_style.items()):
        summarize(rows, f"validation endings {style}")

    from mockingbird.generate.service import LevelGenerator

    gen = LevelGenerator(args.model, thresholds_path=Path("models/difficulty_thresholds.json"))
    rows = []
    compliance = Counter()
    styles = ["folk", "chorale", "lied", "choral"]
    for seed in range(args.levels):
        req = GenerateRequest(tonic="C", mode="major" if seed % 2 == 0 else "minor",
                              meter="4/4" if seed % 3 else "3/4", voice="S",
                              difficulty=2 + seed % 3, bars=8, style=styles[seed % 4], seed=seed)
        level = gen.generate(req)
        off = frame_offset(req.tonic, req.mode)
        frame = Phrase(mode=req.mode, meter=req.meter, style=req.style, pickup_ticks=level.pickup_ticks,
                       notes=[n.model_copy(update={"pitch": n.pitch - off if n.pitch is not None else None})
                              for n in level.melody])
        rows.append(cadence_features(frame))
        found = label_phrases(frame.notes, level.phrase_ends, req.meter, req.mode, level.pickup_ticks)
        for i, (want, got) in enumerate(zip(level.cadences, found)):
            pos = "final" if i == len(found) - 1 else "interior"
            compliance[(pos, want, got)] += 1
    summarize(rows, "generated levels")
    for pos in ("final", "interior"):
        items = [(w, g, n) for (p, w, g), n in compliance.items() if p == pos]
        total = sum(n for _, _, n in items)
        if not total:
            continue
        ok = sum(n for w, g, n in items if w == g)
        chosen = Counter()
        for w, _, n in items:
            chosen[w] += n
        print(f"{pos} phrases: realised as intended {100 * ok / total:.0f}% of {total}; intended "
              + ", ".join(f"{w} {n}" for w, n in chosen.most_common()))


if __name__ == "__main__":
    main()
