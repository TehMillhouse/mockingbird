"""Recompute cadence labels of an existing processed dataset (no re-extraction).

    uv run python tools/relabel.py data/processed
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from mockingbird.data.extract import clean_phrase_ends
from mockingbird.harmonize.cadence import label_phrases
from mockingbird.schema import Note


def relabel(line: str) -> str:
    r = json.loads(line)
    notes = [Note(**n) for n in r["notes"]]
    r["phrase_ends"] = clean_phrase_ends(notes, r["phrase_ends"])
    r["cadences"] = label_phrases(notes, r["phrase_ends"], r["meter"], r["mode"], r["pickup_ticks"])
    return json.dumps(r)


def main(d: Path) -> None:
    for name in ("train", "val"):
        p = d / f"{name}.jsonl"
        lines = p.read_text(encoding="utf-8").splitlines()
        with ProcessPoolExecutor(6) as ex:
            out = list(ex.map(relabel, lines, chunksize=200))
        p.write_text("\n".join(out) + "\n", encoding="utf-8")
        print(name, len(out))


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "data/processed"))
