"""PDMX (public-domain MuseScore scores) loader.

`prepare` reads PDMX.csv, selects vocal scores (lyrics present, no license conflict,
deduplicated arrangement, classical or religious genre), extracts just those MusicXML
files from mxl.tar.gz and writes a manifest. Everything is tagged `choral`: the
one- and two-track scores are mostly hymns and part-songs with keyboard, closer to
choir repertoire than to the art songs of the `lied` style.

    uv run mb data prepare-pdmx        # once, after downloading the two Zenodo files
"""
from __future__ import annotations

import csv
import tarfile
from pathlib import Path
from typing import Iterator

PDMX_DIR = Path("data/external/pdmx")
MANIFEST = PDMX_DIR / "manifest.tsv"
GENRE_OK = ("classical", "religious")


def _wanted_rows(csv_path: Path) -> list[dict]:
    import pandas as pd

    df = pd.read_csv(csv_path, low_memory=False)
    m = (df["has_lyrics"] == True) & (df["subset:no_license_conflict"] == True)  # noqa: E712
    m &= df["subset:deduplicated"] == True  # noqa: E712
    m &= df["genres"].fillna("").str.contains("|".join(GENRE_OK))
    m &= df["mxl"].notna()
    sub = df[m]
    rows = []
    for r in sub.itertuples(index=False):
        style = "choral"
        rows.append({"mxl": str(r.mxl).lstrip("./"), "style": style,
                     "title": str(r.title)[:80], "composer": str(r.composer_name)[:60]})
    return rows


def prepare(csv_path: Path = PDMX_DIR / "PDMX.csv", tar_path: Path = PDMX_DIR / "mxl.tar.gz",
            out_dir: Path = PDMX_DIR) -> int:
    rows = _wanted_rows(csv_path)
    wanted = {r["mxl"]: r for r in rows}
    print(f"{len(wanted)} vocal scores selected from PDMX; extracting from {tar_path.name} ...")
    extracted = 0
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar:
            name = member.name.lstrip("./")
            if name in wanted and member.isfile():
                member.name = name
                tar.extract(member, out_dir, filter="data")
                extracted += 1
                if extracted % 1000 == 0:
                    print(f"  {extracted} files")
    with MANIFEST.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["mxl", "style", "title", "composer"])
        for r in rows:
            if (out_dir / r["mxl"]).exists():
                w.writerow([r["mxl"], r["style"], r["title"], r["composer"]])
    print(f"extracted {extracted}; manifest at {MANIFEST}")
    return extracted


def list_files() -> Iterator[tuple[str, Path]]:
    if not MANIFEST.exists():
        return
    with MANIFEST.open(encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            yield f"pdmx/{Path(r['mxl']).stem[:16]}", PDMX_DIR / r["mxl"]
