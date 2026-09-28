"""Incremental decoding with a KV cache must match a full forward pass."""
import pytest
import torch

from mockingbird import tokenizer as tk
from mockingbird.model import KVCache, MelodyModel, ModelConfig
from mockingbird.schema import Note, Phrase
from mockingbird.train import collate_tokens

CONFIGS = [
    dict(arch="stack", pos_encoding="learned", metric_emb=False),
    dict(arch="stack", pos_encoding="rope", metric_emb=True),
    dict(arch="looped", pos_encoding="metric_rope", metric_emb=True),
    dict(arch="looped", pos_encoding="metric_rope", metric_emb=True, anchor_prefix=True),
]


def _tokens() -> list[int]:
    pitches = [60, 62, 64, 65, 67, 65, 64, 62, 60, 64, 67, 72, 71, 67, 62, 60]
    phrase = Phrase(mode="major", meter="4/4", style="folk",
                    notes=[Note(pitch=p, duration=24) for p in pitches])
    return tk.encode(phrase, difficulty=2, range_bucket="S")


@pytest.mark.parametrize("cfg", CONFIGS, ids=lambda c: f"{c['arch']}-{c['pos_encoding']}"
                         + ("-anchor" if c.get("anchor_prefix") else ""))
def test_cached_decoding_matches_full_forward(cfg):
    torch.manual_seed(0)
    model = MelodyModel(ModelConfig(n_layer=2, d_model=64, n_head=2, d_ff=128, max_len=128,
                                    dropout=0.0, n_core=1, **cfg)).eval()
    toks = _tokens()
    x, metric = collate_tokens([toks, toks[:-3] + [tk.tid(tk.PAD)] * 3])
    with torch.no_grad():
        full = model(x, metric)
        cache = KVCache(128)
        steps = [model(x[:, :tk.PREFIX_LEN], _slice(metric, 0, tk.PREFIX_LEN), cache=cache)]
        for i in range(tk.PREFIX_LEN, x.size(1)):
            steps.append(model(x[:, i:i + 1], _slice(metric, i, i + 1), cache=cache))
    torch.testing.assert_close(torch.cat(steps, dim=1), full, atol=1e-5, rtol=1e-5)


def _slice(metric: dict[str, torch.Tensor], start: int, end: int) -> dict[str, torch.Tensor]:
    return {k: (v[:, start:end] if v.dim() == 2 else v) for k, v in metric.items()}
