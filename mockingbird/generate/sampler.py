"""Batched nucleus sampling with optional per-step logit constraints."""
from __future__ import annotations

from typing import Callable

import torch

from .. import tokenizer as tk
from ..model import MelodyModel
from ..train import collate_tokens

MaskFn = Callable[[int, list[int]], torch.Tensor | None]


def _top_p_filter(logits: torch.Tensor, top_p: float) -> torch.Tensor:
    sorted_logits, sorted_idx = torch.sort(logits, descending=True, dim=-1)
    probs = torch.softmax(sorted_logits, dim=-1)
    cum = probs.cumsum(dim=-1)
    remove = cum - probs > top_p
    sorted_logits[remove] = float("-inf")
    return torch.full_like(logits, float("-inf")).scatter(-1, sorted_idx, sorted_logits)


@torch.no_grad()
def sample(model: MelodyModel, prefix: list[int], *, n: int, max_new: int, device: str,
           temperature: float = 1.0, top_p: float = 0.9,
           mask_fn: MaskFn | None = None, seed: int | None = None) -> list[list[int]]:
    """Sample `n` continuations of `prefix`. `mask_fn(row, tokens)` may return a boolean
    tensor over the vocabulary marking allowed tokens; rows stop at EOS."""
    gen = torch.Generator(device=device)
    if seed is not None:
        gen.manual_seed(seed)
    else:
        gen.seed()
    eos = tk.tid(tk.EOS)
    seqs = [list(prefix) for _ in range(n)]
    done = [False] * n
    x = torch.tensor(seqs, dtype=torch.long, device=device)
    for _ in range(max_new):
        if all(done) or x.size(1) >= model.cfg.max_len:
            break
        metric = None
        if model.cfg.metric_emb or model.cfg.pos_encoding == "metric_rope":
            _, metric = collate_tokens(x.tolist())  # rows are PAD-extended after EOS
            metric = {k: v.to(device) for k, v in metric.items()}
        with torch.autocast(device, dtype=torch.bfloat16, enabled=device == "cuda"):
            logits = model(x, metric)[:, -1, :].float()
        logits = logits / max(temperature, 1e-4)
        if mask_fn is not None:
            for r in range(n):
                if done[r]:
                    continue
                allowed = mask_fn(r, seqs[r])
                if allowed is not None:
                    logits[r][~allowed.to(device)] = float("-inf")
        logits = _top_p_filter(logits, top_p)
        probs = torch.softmax(logits, dim=-1)
        probs = torch.nan_to_num(probs, nan=0.0)
        zero = probs.sum(-1) == 0
        if zero.any():  # every token masked: fall back to EOS
            probs[zero] = 0.0
            probs[zero, eos] = 1.0
        nxt = torch.multinomial(probs, 1, generator=gen).squeeze(1)
        for r in range(n):
            if done[r]:
                nxt[r] = tk.tid(tk.PAD)
            else:
                t = int(nxt[r])
                seqs[r].append(t)
                if t == eos:
                    done[r] = True
        x = torch.cat([x, nxt.unsqueeze(1)], dim=1)
    return seqs


def sample_unconstrained(model: MelodyModel, prefix: list[int], *, n: int, max_new: int,
                         device: str, temperature: float = 1.0, top_p: float = 0.9) -> list[list[int]]:
    return sample(model, prefix, n=n, max_new=max_new, device=device,
                  temperature=temperature, top_p=top_p)
