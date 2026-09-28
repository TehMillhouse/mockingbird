"""Build the training set: parse corpora in parallel, extract, segment, filter, split."""
from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .. import difficulty
from ..harmonize.cadence import label_phrases
from ..schema import Phrase
from ..tokenizer import encode
from .extract import extract_file
from .filters import dedup, reject_reason
from .segment import segment
from .sources import SOURCES, list_files

PROCESSED = Path("data/processed")


def _work(args: tuple[str, str, str]) -> tuple[list[dict], list[tuple[str, str]]]:
    path, source_id, style = args
    if path.endswith(".mscx"):
        from .lieder import extract_mscx

        phrases, rejects = extract_mscx(Path(path), source_id, style)
    else:
        phrases, rejects = extract_file(Path(path), source_id, style)
    out: list[dict] = []
    for ph in phrases:
        try:
            windows = segment(ph)
        except Exception as e:  # noqa: BLE001
            rejects.append((ph.source, f"segment_error:{type(e).__name__}"))
            continue
        for w in windows:
            reason = reject_reason(w)
            if reason:
                rejects.append((w.source, reason))
                continue
            w = w.model_copy(update={"cadences": label_phrases(w.notes, w.phrase_ends, w.meter, w.mode,
                                                                w.pickup_ticks)})
            try:
                encode(w, difficulty=3)
            except ValueError as e:
                rejects.append((w.source, f"encode:{e}"))
                continue
            d = w.model_dump()
            d["difficulty_score"] = difficulty.score(w)
            out.append(d)
    return out, rejects


def work_key(source: str) -> str:
    """Grouping key for the train/val split: one source work (file or ABC tune)."""
    return source.split("@")[0].split("#")[0]


def build(sources: list[str], out_dir: Path = PROCESSED, workers: int = 6, seed: int = 0,
          limit: int | None = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for src in sources:
        style = SOURCES[src]
        for source_id, path in list_files(src):
            jobs.append((str(path), source_id, style))
    if limit:
        jobs = jobs[:limit]
    print(f"{len(jobs)} files to process")
    records: list[dict] = []
    rejects: Counter = Counter()
    reject_log = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_work, j) for j in jobs]
        for i, fut in enumerate(as_completed(futures), 1):
            recs, rej = fut.result()
            records.extend(recs)
            for src, reason in rej:
                rejects[reason.split(":")[0]] += 1
                reject_log.append(f"{src}\t{reason}")
            if i % 50 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} files, {len(records)} windows, rejects {sum(rejects.values())}")

    phrases = [Phrase(**{k: v for k, v in r.items() if k != "difficulty_score"}) for r in records]
    kept, dropped = dedup(phrases)
    kept_sources = {p.source for p in kept}
    records = [r for r in records if r["source"] in kept_sources]
    print(f"dedup dropped {dropped}; {len(records)} windows remain")

    rng = random.Random(seed)
    works = sorted({work_key(r["source"]) for r in records})
    rng.shuffle(works)
    val_works = set(works[: max(1, len(works) // 10)])
    train = [r for r in records if work_key(r["source"]) not in val_works]
    val = [r for r in records if work_key(r["source"]) in val_works]

    scores_by_style: dict[str, list[float]] = defaultdict(list)
    for r in train:
        scores_by_style[r["style"]].append(r["difficulty_score"])
    thresholds = difficulty.calibrate(scores_by_style)
    thresholds.save(out_dir / "difficulty_thresholds.json")

    for name, rows in (("train", train), ("val", val)):
        with (out_dir / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    (out_dir / "rejects.tsv").write_text("\n".join(reject_log), encoding="utf-8")

    stats = {
        "windows": {"train": len(train), "val": len(val)},
        "by_style": dict(Counter(r["style"] for r in records)),
        "by_meter": dict(Counter(r["meter"] for r in records)),
        "by_mode": dict(Counter(r["mode"] for r in records)),
        "by_range": dict(Counter(r["range_bucket"] for r in records)),
        "tokens_train": sum(len(encode(Phrase(**{k: v for k, v in r.items() if k != "difficulty_score"}), difficulty=3)) for r in train),
        "rejects": dict(rejects.most_common()),
        "thresholds": thresholds.per_style,
    }
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))
