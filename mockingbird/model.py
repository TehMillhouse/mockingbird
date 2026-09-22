"""Decoder-only Transformer for melody tokens, with a few architectural switches.

Positional information can come from learned absolute embeddings, rotary embeddings
(RoPE) or nothing, and can be supplemented by *metric embeddings*: each token knows
the bar it is in and its tick position within the bar, both derived deterministically
from the token stream (see `tokenizer.metric_positions`).

Two layouts are available. `stack` is a plain GPT stack. `looped` runs a prelude, then
a small core block group several times with shared weights (a learned per-iteration
embedding tells the core which pass it is on), then a coda. The loop count is jittered
during training and fixed at `loop_center` for evaluation and generation.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

from .tokenizer import BAR_TICK_CLASSES, MAX_BAR_INDEX, VOCAB_SIZE


@dataclass
class ModelConfig:
    vocab_size: int = VOCAB_SIZE
    n_layer: int = 6
    d_model: int = 256
    n_head: int = 4
    d_ff: int = 1024
    max_len: int = 1024
    dropout: float = 0.2
    pos_encoding: str = "learned"  # learned | rope | none
    metric_emb: bool = True
    arch: str = "stack"  # stack | looped
    n_prelude: int = 1
    n_core: int = 2
    n_coda: int = 1
    loop_center: int = 3
    loop_jitter: int = 1
    sandwich_norm: bool = False


def _rope_cache(max_len: int, head_dim: int, device, base: float = 10000.0) -> tuple[torch.Tensor, torch.Tensor]:
    inv = 1.0 / (base ** (torch.arange(0, head_dim, 2, device=device).float() / head_dim))
    t = torch.arange(max_len, device=device).float()
    freqs = torch.outer(t, inv)  # (T, head_dim/2)
    emb = torch.cat([freqs, freqs], dim=-1)
    return emb.cos(), emb.sin()


def _rotate_half(x: torch.Tensor) -> torch.Tensor:
    x1, x2 = x.chunk(2, dim=-1)
    return torch.cat([-x2, x1], dim=-1)


def _apply_rope(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    # x: (B, H, T, D); cos/sin: (T, D)
    return x * cos + _rotate_half(x) * sin


class Block(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.ln1 = nn.LayerNorm(cfg.d_model)
        self.qkv = nn.Linear(cfg.d_model, 3 * cfg.d_model)
        self.proj = nn.Linear(cfg.d_model, cfg.d_model)
        self.ln2 = nn.LayerNorm(cfg.d_model)
        self.ff = nn.Sequential(nn.Linear(cfg.d_model, cfg.d_ff), nn.GELU(),
                                nn.Linear(cfg.d_ff, cfg.d_model))
        self.drop = nn.Dropout(cfg.dropout)
        self.n_head = cfg.n_head
        self.attn_dropout = cfg.dropout
        self.rope = cfg.pos_encoding == "rope"
        # sandwich norm: also normalise each branch output before the residual add
        self.post1 = nn.LayerNorm(cfg.d_model) if cfg.sandwich_norm else nn.Identity()
        self.post2 = nn.LayerNorm(cfg.d_model) if cfg.sandwich_norm else nn.Identity()

    def forward(self, x: torch.Tensor, rope: tuple[torch.Tensor, torch.Tensor] | None) -> torch.Tensor:
        b, t, d = x.shape
        q, k, v = self.qkv(self.ln1(x)).split(d, dim=2)
        q = q.view(b, t, self.n_head, d // self.n_head).transpose(1, 2)
        k = k.view(b, t, self.n_head, d // self.n_head).transpose(1, 2)
        v = v.view(b, t, self.n_head, d // self.n_head).transpose(1, 2)
        if self.rope and rope is not None:
            cos, sin = rope
            q = _apply_rope(q, cos[:t], sin[:t])
            k = _apply_rope(k, cos[:t], sin[:t])
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True,
                                           dropout_p=self.attn_dropout if self.training else 0.0)
        y = y.transpose(1, 2).contiguous().view(b, t, d)
        x = x + self.drop(self.post1(self.proj(y)))
        x = x + self.drop(self.post2(self.ff(self.ln2(x))))
        return x


class MelodyModel(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.cfg = cfg
        self.tok = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.pos = nn.Embedding(cfg.max_len, cfg.d_model) if cfg.pos_encoding == "learned" else None
        if cfg.metric_emb:
            self.bar_emb = nn.Embedding(MAX_BAR_INDEX + 1, cfg.d_model)
            self.tick_emb = nn.Embedding(BAR_TICK_CLASSES, cfg.d_model)
        self.drop = nn.Dropout(cfg.dropout)
        if cfg.arch == "looped":
            self.prelude = nn.ModuleList(Block(cfg) for _ in range(cfg.n_prelude))
            self.core = nn.ModuleList(Block(cfg) for _ in range(cfg.n_core))
            self.coda = nn.ModuleList(Block(cfg) for _ in range(cfg.n_coda))
            self.loop_emb = nn.Embedding(cfg.loop_center + cfg.loop_jitter + 1, cfg.d_model)
            n_blocks = cfg.n_prelude + cfg.n_core + cfg.n_coda
        else:
            self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.n_layer))
            n_blocks = cfg.n_layer
        self.ln_f = nn.LayerNorm(cfg.d_model)
        self.apply(self._init)
        for name, p in self.named_parameters():
            if name.endswith("proj.weight") or name.endswith("ff.2.weight"):
                nn.init.normal_(p, mean=0.0, std=0.02 / math.sqrt(2 * n_blocks))
        if cfg.pos_encoding == "rope":
            cos, sin = _rope_cache(cfg.max_len, cfg.d_model // cfg.n_head, torch.device("cpu"))
            self.register_buffer("rope_cos", cos, persistent=False)
            self.register_buffer("rope_sin", sin, persistent=False)

    @staticmethod
    def _init(m: nn.Module) -> None:
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)
            if m.bias is not None:
                nn.init.zeros_(m.bias)
        elif isinstance(m, nn.Embedding):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def forward(self, idx: torch.Tensor, bars: torch.Tensor | None = None,
                ticks: torch.Tensor | None = None, loops: int | None = None) -> torch.Tensor:
        b, t = idx.shape
        if t > self.cfg.max_len:
            raise ValueError(f"sequence length {t} exceeds max_len {self.cfg.max_len}")
        x = self.tok(idx)
        if self.pos is not None:
            x = x + self.pos(torch.arange(t, device=idx.device))
        if self.cfg.metric_emb:
            if bars is None or ticks is None:
                raise ValueError("metric_emb model needs bars and ticks")
            x = x + self.bar_emb(bars.clamp(max=MAX_BAR_INDEX)) + self.tick_emb(ticks)
        x = self.drop(x)
        rope = (self.rope_cos, self.rope_sin) if self.cfg.pos_encoding == "rope" else None
        if self.cfg.arch == "looped":
            for blk in self.prelude:
                x = blk(x, rope)
            n_loops = loops if loops is not None else self.cfg.loop_center
            for i in range(n_loops):
                x = x + self.loop_emb.weight[min(i, self.loop_emb.num_embeddings - 1)]
                for blk in self.core:
                    x = blk(x, rope)
            for blk in self.coda:
                x = blk(x, rope)
        else:
            for blk in self.blocks:
                x = blk(x, rope)
        x = self.ln_f(x)
        return x @ self.tok.weight.T  # tied output embedding

    def sample_loops(self, gen: torch.Generator | None = None) -> int:
        """Training-time loop count: uniform in [center - jitter, center + jitter]."""
        if self.cfg.arch != "looped" or self.cfg.loop_jitter == 0:
            return self.cfg.loop_center
        lo = max(1, self.cfg.loop_center - self.cfg.loop_jitter)
        hi = self.cfg.loop_center + self.cfg.loop_jitter
        return int(torch.randint(lo, hi + 1, (1,), generator=gen).item())

    def num_params(self) -> int:
        return sum(p.numel() for p in self.parameters())

    def save(self, path, extra: dict | None = None) -> None:
        torch.save({"config": asdict(self.cfg), "state_dict": self.state_dict(),
                    **(extra or {})}, path)

    @classmethod
    def load(cls, path, device: str = "cpu") -> tuple["MelodyModel", dict]:
        ckpt = torch.load(path, map_location=device, weights_only=False)
        model = cls(ModelConfig(**ckpt["config"]))
        model.load_state_dict(ckpt["state_dict"])
        model.to(device).eval()
        return model, {k: v for k, v in ckpt.items() if k not in ("config", "state_dict")}
