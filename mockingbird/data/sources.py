"""Enumerate corpus files per style.

Each source yields `(source_id, path)` pairs. Parsing happens in `extract` so the
enumeration is cheap and can be split across worker processes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from music21 import corpus

# Essen files to skip: han1/han2 are Chinese folk songs (the choir wants a European
# classical corpus), test*/variant* are tiny duplicates of other files.
ESSEN_SKIP_PREFIXES = ("han", "test", "variant")

SOURCES: dict[str, str] = {
    "essen": "folk",
    "bach": "chorale",
    "palestrina": "renaissance",
    "monteverdi": "renaissance",
    "josquin": "renaissance",
    "lieder": "lied",
    "pdmx": "choral",
}


def list_files(source: str) -> Iterator[tuple[str, Path]]:
    if source == "essen":
        for p in corpus.getComposer("essenFolksong"):
            p = Path(p)
            if p.suffix != ".abc" or p.name.startswith(ESSEN_SKIP_PREFIXES):
                continue
            yield f"essen/{p.stem}", p
    elif source == "bach":
        for p in corpus.getComposer("bach"):
            p = Path(p)
            # everything is a chorale except the WTC prelude bwv846 and the analyses folder
            if p.suffix in (".mxl", ".xml", ".krn") and p.stem.startswith("bwv") and p.stem != "bwv846":
                yield f"bach/{p.stem}", p
    elif source in ("palestrina", "monteverdi", "josquin"):
        for p in corpus.getComposer(source):
            p = Path(p)
            if p.suffix in (".mxl", ".xml", ".krn", ".abc"):
                yield f"{source}/{p.stem}", p
    elif source == "lieder":
        from .lieder import list_files as lieder_files

        yield from lieder_files()
    elif source == "pdmx":
        from .pdmx import list_files as pdmx_files

        yield from pdmx_files()
    else:
        raise ValueError(f"unknown source {source}")
