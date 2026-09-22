"""Compare training runs: best validation NLL per style, epoch reached, parameter count.

    uv run python tools/compare_runs.py models/ablation/metric models/ablation/rope_metric ...

Each run directory must hold train_log.jsonl and model.pt as written by `mb train`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import torch

from mockingbird.model import MelodyModel


def summarize(run: Path) -> dict:
    rows = [json.loads(l) for l in (run / "train_log.jsonl").open()]
    best = min(rows, key=lambda r: r["val_nll"])
    ckpt = next(run.glob("*.pt"))
    model, _ = MelodyModel.load(ckpt, "cpu")
    cfg = model.cfg
    return {
        "run": run.name,
        "params_M": round(model.num_params() / 1e6, 2),
        "arch": f"{cfg.arch} pos={cfg.pos_encoding} metric={cfg.metric_emb}"
                + (f" loops={cfg.loop_center}±{cfg.loop_jitter} core={cfg.n_core}" if cfg.arch == "looped" else "")
                + (" sandwich" if cfg.sandwich_norm else ""),
        "epochs": len(rows),
        "best_epoch": best["epoch"],
        "best_val": round(best["val_nll"], 4),
        "train_at_best": round(best["train_loss"], 4),
        **{f"val_{k}": round(v, 4) for k, v in best["val_by_style"].items()},
    }


def main(paths: list[str]) -> None:
    rows = [summarize(Path(p)) for p in paths]
    keys = ["run", "params_M", "arch", "epochs", "best_epoch", "best_val", "train_at_best",
            "val_folk", "val_chorale", "val_lied", "val_renaissance"]
    widths = {k: max(len(k), *(len(str(r.get(k, ""))) for r in rows)) for k in keys}
    print(" | ".join(k.ljust(widths[k]) for k in keys))
    print("-+-".join("-" * widths[k] for k in keys))
    for r in rows:
        print(" | ".join(str(r.get(k, "")).ljust(widths[k]) for k in keys))


if __name__ == "__main__":
    main(sys.argv[1:] or ["models"])
