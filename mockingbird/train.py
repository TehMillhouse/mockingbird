"""Training loop for the melody model."""
from __future__ import annotations

import json
import math
import random
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import torch
import torch.nn.functional as F

from . import tokenizer as tk
from .data.segment import bars_of
from .difficulty import Thresholds
from .model import MelodyModel, ModelConfig
from .schema import Phrase
from .theory import PITCH_MAX, PITCH_MIN, is_diatonic


@dataclass
class TrainConfig:
    data_dir: Path = Path("data/processed")
    out_dir: Path = Path("models")
    epochs: int = 50
    batch_size: int = 32
    lr: float = 5e-4
    min_lr: float = 5e-5
    warmup_steps: int = 500
    weight_decay: float = 0.1
    label_smoothing: float = 0.05
    grad_clip: float = 1.0
    patience: int = 8
    seed: int = 0
    octave_shift_p: float = 0.3
    diff_jitter_p: float = 0.1
    crop_p: float = 0.25
    checkpoint_name: str = "melody-v1.pt"
    device: str = "cuda" if torch.cuda.is_available() else "cpu"


def load_records(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def record_phrase(r: dict) -> Phrase:
    return Phrase(**{k: v for k, v in r.items() if k != "difficulty_score"})


class PhraseDataset:
    def __init__(self, records: list[dict], thresholds: Thresholds, cfg: TrainConfig, train: bool):
        self.phrases = [record_phrase(r) for r in records]
        self.buckets = [thresholds.bucket(r["difficulty_score"], r["style"]) for r in records]
        self.cfg = cfg
        self.train = train
        self.rng = random.Random(cfg.seed + (0 if train else 1))
        self.lengths = [len(tk.encode(p, difficulty=b)) for p, b in zip(self.phrases, self.buckets)]

    def __len__(self) -> int:
        return len(self.phrases)

    def encode(self, i: int) -> list[int]:
        ph, bucket = self.phrases[i], self.buckets[i]
        if not self.train:
            return tk.encode(ph, difficulty=bucket)
        rng = self.rng
        if rng.random() < self.cfg.crop_p:
            bars = bars_of(ph)
            n_full = len(bars) - (1 if ph.pickup_ticks else 0)
            if n_full > 8:
                first = 1 if ph.pickup_ticks else 0
                start = rng.randint(first, len(bars) - 8)
                notes = [n for b in bars[start:] for n in b]
                if start > 0 and notes:
                    ph = ph.model_copy(update={"notes": notes, "pickup_ticks": 0})
        if rng.random() < self.cfg.octave_shift_p:
            shift = rng.choice((-12, 12))
            ps = [n.pitch for n in ph.notes if n.pitch is not None]
            if ps and PITCH_MIN <= min(ps) + shift and max(ps) + shift <= PITCH_MAX:
                ph = ph.model_copy(update={"notes": [
                    n.model_copy(update={"pitch": n.pitch + shift}) if n.pitch is not None else n
                    for n in ph.notes]})
        if rng.random() < self.cfg.diff_jitter_p:
            bucket = min(5, max(1, bucket + rng.choice((-1, 1))))
        return tk.encode(ph, difficulty=bucket)

    def batches(self, batch_size: int, shuffle: bool) -> list[list[int]]:
        idx = list(range(len(self)))
        if shuffle:
            self.rng.shuffle(idx)
        # sort within chunks so batches have similar lengths and little padding
        chunk = batch_size * 50
        out: list[list[int]] = []
        for c in range(0, len(idx), chunk):
            part = sorted(idx[c:c + chunk], key=lambda i: self.lengths[i])
            out += [part[b:b + batch_size] for b in range(0, len(part), batch_size)]
        if shuffle:
            self.rng.shuffle(out)
        return out

    def collate(self, batch: list[int], max_len: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Token ids plus per-token bar index and tick class (for metric embeddings)."""
        seqs = [self.encode(i)[:max_len] for i in batch]
        t = max(len(s) for s in seqs)
        x = torch.full((len(seqs), t), tk.tid(tk.PAD), dtype=torch.long)
        bars = torch.zeros((len(seqs), t), dtype=torch.long)
        ticks = torch.zeros((len(seqs), t), dtype=torch.long)
        for r, s in enumerate(seqs):
            x[r, :len(s)] = torch.tensor(s)
            b, k = tk.metric_positions(s)
            bars[r, :len(s)] = torch.tensor(b)
            ticks[r, :len(s)] = torch.tensor(k)
        return x, bars, ticks


def loss_fn(logits: torch.Tensor, targets: torch.Tensor, smoothing: float) -> torch.Tensor:
    return F.cross_entropy(logits.reshape(-1, logits.size(-1)), targets.reshape(-1),
                           ignore_index=tk.tid(tk.PAD), label_smoothing=smoothing)


@torch.no_grad()
def evaluate(model: MelodyModel, ds: PhraseDataset, cfg: TrainConfig) -> dict[str, float]:
    model.eval()
    tot = defaultdict(float)
    cnt = defaultdict(int)
    for batch in ds.batches(cfg.batch_size, shuffle=False):
        x, bars, ticks = (m.to(cfg.device) for m in ds.collate(batch, model.cfg.max_len))
        with torch.autocast(cfg.device, dtype=torch.bfloat16, enabled=cfg.device == "cuda"):
            logits = model(x[:, :-1], bars[:, :-1], ticks[:, :-1])
        nll = F.cross_entropy(logits.float().reshape(-1, logits.size(-1)), x[:, 1:].reshape(-1),
                              ignore_index=tk.tid(tk.PAD), reduction="none").view(x.size(0), -1)
        mask = (x[:, 1:] != tk.tid(tk.PAD)).float()
        per_seq = (nll * mask).sum(1)
        for j, i in enumerate(batch):
            style = ds.phrases[i].style
            tot[style] += per_seq[j].item()
            cnt[style] += int(mask[j].sum().item())
            tot["all"] += per_seq[j].item()
            cnt["all"] += int(mask[j].sum().item())
    return {k: tot[k] / max(1, cnt[k]) for k in tot}


@torch.no_grad()
def sample_stats(model: MelodyModel, cfg: TrainConfig, n: int = 16) -> dict[str, float]:
    """Unconstrained samples for a quick musical sanity check of an epoch."""
    from .generate.sampler import sample_unconstrained

    model.eval()
    in_key, bars, notes = [], [], []
    for mode in ("major", "minor"):
        prefix = tk.prefix_tokens(mode, "4/4", 2, "folk", "S")
        seqs = sample_unconstrained(model, prefix, n=n // 2, max_new=400, device=cfg.device)
        for s in seqs:
            try:
                dec = tk.decode(s)
            except ValueError:
                continue
            ps = [x.pitch for x in dec.phrase.notes if x.pitch is not None]
            if ps:
                in_key.append(sum(is_diatonic(p, mode) for p in ps) / len(ps))
            bars.append(dec.complete_bars)
            notes.append(len(dec.phrase.notes))
    return {"in_key": sum(in_key) / max(1, len(in_key)),
            "bars": sum(bars) / max(1, len(bars)),
            "notes": sum(notes) / max(1, len(notes))}


def train(cfg: TrainConfig, mcfg: ModelConfig | None = None) -> Path:
    torch.manual_seed(cfg.seed)
    random.seed(cfg.seed)
    mcfg = mcfg or ModelConfig()
    thresholds = Thresholds.load(cfg.data_dir / "difficulty_thresholds.json")
    train_ds = PhraseDataset(load_records(cfg.data_dir / "train.jsonl"), thresholds, cfg, train=True)
    val_ds = PhraseDataset(load_records(cfg.data_dir / "val.jsonl"), thresholds, cfg, train=False)
    print(f"train {len(train_ds)} phrases / {sum(train_ds.lengths)} tokens; val {len(val_ds)}")

    model = MelodyModel(mcfg).to(cfg.device)
    print(f"model params {model.num_params() / 1e6:.2f}M on {cfg.device}; config {mcfg}")
    decay, no_decay = [], []
    for name, p in model.named_parameters():
        (decay if p.dim() >= 2 else no_decay).append(p)
    opt = torch.optim.AdamW([{"params": decay, "weight_decay": cfg.weight_decay},
                             {"params": no_decay, "weight_decay": 0.0}], lr=cfg.lr, betas=(0.9, 0.95))
    steps_per_epoch = math.ceil(len(train_ds) / cfg.batch_size)
    total_steps = steps_per_epoch * cfg.epochs

    def lr_at(step: int) -> float:
        if step < cfg.warmup_steps:
            return cfg.lr * step / cfg.warmup_steps
        prog = (step - cfg.warmup_steps) / max(1, total_steps - cfg.warmup_steps)
        return cfg.min_lr + 0.5 * (cfg.lr - cfg.min_lr) * (1 + math.cos(math.pi * prog))

    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    best_path = cfg.out_dir / cfg.checkpoint_name
    log_path = cfg.out_dir / "train_log.jsonl"
    best_val, bad_epochs, step = float("inf"), 0, 0
    with log_path.open("w") as log:
        for epoch in range(1, cfg.epochs + 1):
            model.train()
            t0, tot_loss, n_batches = time.time(), 0.0, 0
            for batch in train_ds.batches(cfg.batch_size, shuffle=True):
                x, bars, ticks = (m.to(cfg.device) for m in train_ds.collate(batch, mcfg.max_len))
                for g in opt.param_groups:
                    g["lr"] = lr_at(step)
                with torch.autocast(cfg.device, dtype=torch.bfloat16, enabled=cfg.device == "cuda"):
                    logits = model(x[:, :-1], bars[:, :-1], ticks[:, :-1], loops=model.sample_loops())
                loss = loss_fn(logits.float(), x[:, 1:], cfg.label_smoothing)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
                opt.step()
                tot_loss += loss.item()
                n_batches += 1
                step += 1
            val = evaluate(model, val_ds, cfg)
            stats = sample_stats(model, cfg)
            row = {"epoch": epoch, "train_loss": tot_loss / n_batches, "val_nll": val["all"],
                   "val_by_style": {k: round(v, 4) for k, v in val.items() if k != "all"},
                   "samples": {k: round(v, 3) for k, v in stats.items()},
                   "lr": lr_at(step), "sec": round(time.time() - t0, 1)}
            log.write(json.dumps(row) + "\n")
            log.flush()
            print(json.dumps(row))
            if val["all"] < best_val:
                best_val, bad_epochs = val["all"], 0
                model.save(best_path, extra={"epoch": epoch, "val_nll": best_val, "vocab": tk.VOCAB,
                                             "thresholds": thresholds.per_style})
                shutil.copy(cfg.data_dir / "difficulty_thresholds.json",
                            cfg.out_dir / "difficulty_thresholds.json")
            else:
                bad_epochs += 1
                if bad_epochs >= cfg.patience:
                    print(f"early stop at epoch {epoch}; best val {best_val:.4f}")
                    break
    return best_path
