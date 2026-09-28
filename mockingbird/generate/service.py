"""High-level level generation: sample, select, harmonize, transpose."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from .. import difficulty, tokenizer as tk
from ..harmonize.render import STYLES as TEXTURES, render, resolve_texture
from ..harmonize.viterbi import harmonize
from ..harmonize.voicing import voice as voice_lead
from ..model import MelodyModel
from ..schema import AccompEvent, GenerateRequest, Level, Note, Phrase
from ..theory import VOICE_RANGES, bar_ticks, frame_offset, is_diatonic, tonic_pc
from . import warmup
from .constraints import ConstraintState
from .sampler import sample

NGRAM = 12
CANDIDATES = 8

log = logging.getLogger(__name__)


def _ends_with_rest_bar(ph: Phrase) -> bool:
    bt = bar_ticks(ph.meter)
    ticks = 0
    for n in reversed(ph.notes):
        if n.pitch is not None:
            return ticks >= bt
        ticks += n.duration
    return True


def _final_note_is_longest(ph: Phrase) -> bool:
    """The last note of the final bar must be at least as long as any other note in that
    bar. Rejects endings such as a half note followed by a run of sixteenths."""
    from ..data.segment import bars_of

    last_bar = bars_of(ph)[-1]
    pitched = [n for n in tk.merge_ties(last_bar) if n.pitch is not None]
    if not pitched:
        return False
    return pitched[-1].duration >= max(n.duration for n in pitched)


class MemorizationIndex:
    """Set of (interval, duration) n-grams from the training set. Without the training
    data it is empty and nothing counts as a copy."""

    def __init__(self, grams: set[tuple]):
        self.grams = grams

    @property
    def available(self) -> bool:
        return bool(self.grams)

    @classmethod
    def build(cls, train_jsonl: Path) -> "MemorizationIndex":
        grams: set[tuple] = set()
        if not train_jsonl.exists():
            log.warning("no training data at %s: generated melodies are not checked for "
                        "copies of the training set", train_jsonl)
        else:
            with train_jsonl.open(encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    notes = [Note(**n) for n in r["notes"]]
                    for g in cls.ngrams(notes):
                        grams.add(g)
        return cls(grams)

    @staticmethod
    def ngrams(notes: list[Note]):
        merged = [n for n in tk.merge_ties(notes) if n.pitch is not None]
        seq = [(b.pitch - a.pitch, b.duration) for a, b in zip(merged, merged[1:])]
        for i in range(0, len(seq) - NGRAM + 1):
            yield tuple(seq[i:i + NGRAM])

    def is_copy(self, notes: list[Note]) -> bool:
        return any(g in self.grams for g in self.ngrams(notes))


class LevelGenerator:
    def __init__(self, model_path: Path = Path("models/melody-v1.pt"),
                 thresholds_path: Path | None = None,
                 train_jsonl: Path | None = Path("data/processed/train.jsonl"),
                 device: str = "cpu"):
        # the model is small enough that per-step overhead dominates on a GPU, so with
        # the KV cache the CPU generates faster
        self.device = device
        self.model, extra = MelodyModel.load(model_path, self.device)
        if extra.get("vocab") and extra["vocab"] != tk.VOCAB:
            raise RuntimeError("checkpoint vocabulary does not match the tokenizer")
        tpath = thresholds_path or model_path.parent / "difficulty_thresholds.json"
        self.thresholds = difficulty.Thresholds.load(tpath)
        if not self.thresholds.per_style and extra.get("thresholds"):
            self.thresholds = difficulty.Thresholds(extra["thresholds"])
        self.memo = MemorizationIndex.build(train_jsonl) if train_jsonl else MemorizationIndex(set())

    def generate(self, req: GenerateRequest) -> Level:
        style = req.style or "folk"
        prefix = tk.prefix_tokens(req.mode, req.meter, req.difficulty, style, req.voice)
        try:
            state = ConstraintState(mode=req.mode, meter=req.meter, voice=req.voice,
                                    difficulty=req.difficulty, bars=req.bars,
                                    phrase_bars=req.phrase_bars)
        except ValueError as e:
            raise RuntimeError(str(e)) from e
        temperature = 0.9 if req.difficulty <= 2 else 1.0
        lo_s, hi_s = self.thresholds.bucket_range(req.difficulty, style)
        centre = (lo_s + hi_s) / 2

        best: tuple[float, Phrase] | None = None
        for attempt in range(3):
            seqs = sample(self.model, prefix, n=CANDIDATES, max_new=self.model.cfg.max_len - len(prefix) - 1,
                          device=self.device, temperature=temperature, top_p=0.9,
                          mask_fn=lambda r, toks: state.allowed(toks),
                          seed=None if req.seed is None else req.seed + attempt)
            scored: list[tuple[float, float, Phrase]] = []
            for s in seqs:
                dec = tk.decode(s)
                ph = dec.phrase
                if dec.complete_bars < req.bars or dec.trailing_ticks:
                    continue
                pitched = [n.pitch for n in ph.notes if n.pitch is not None]
                if len(pitched) < 4:
                    continue
                if self.memo.is_copy(ph.notes):
                    continue
                in_key = sum(is_diatonic(p, req.mode) for p in pitched) / len(pitched)
                if in_key < 0.8:
                    continue
                rest_ticks = sum(n.duration for n in ph.notes if n.pitch is None)
                if rest_ticks / ph.total_ticks() > 0.25 or _ends_with_rest_bar(ph):
                    continue
                if not _final_note_is_longest(ph):
                    continue
                sc = difficulty.score(ph)
                dist = 0.0 if lo_s <= sc <= hi_s else min(abs(sc - lo_s), abs(sc - hi_s))
                scored.append((dist, abs(sc - centre), ph))
            if scored:
                scored.sort(key=lambda t: (t[0], t[1]))
                cand = scored[0]
                if best is None or cand[0] < best[0]:
                    best = (cand[0], cand[2])
                if cand[0] == 0.0:
                    break
                temperature += 0.1 if all(difficulty.score(p) < lo_s for _, _, p in scored) else -0.1
                temperature = min(1.3, max(0.6, temperature))
        if best is None:
            raise RuntimeError("no valid melody sampled; try another seed or fewer constraints")
        phrase = best[1]
        return self.finish(phrase, req, style)

    def warmup(self, req: GenerateRequest) -> Level:
        """The built-in warm-up in the requested key, mode and voice."""
        phrase = warmup.warmup_phrase(req.mode)
        bars = phrase.total_ticks() // bar_ticks(warmup.METER)
        req = req.model_copy(update={"meter": warmup.METER, "bars": bars})
        return self.finish(phrase, req, shift=warmup.warmup_shift(req.tonic, req.mode, req.voice))

    def finish(self, phrase: Phrase, req: GenerateRequest, style: str | None = None,
               shift: int | None = None) -> Level:
        """Place the melody in the singer's range (or transpose it from the frame by
        `shift`), then harmonize, voice-lead and render the accompaniment in concert
        pitch."""
        if req.accompaniment not in TEXTURES:
            raise RuntimeError(f"accompaniment must be one of {TEXTURES}")
        offset = frame_offset(req.tonic, req.mode)
        lo, hi = VOICE_RANGES[req.voice]
        pitched = [n.pitch for n in phrase.notes if n.pitch is not None]
        best_shift, best_cost = offset if shift is None else shift, float("inf")
        for k in (-24, -12, 0, 12, 24) if shift is None else ():
            candidate = offset + k
            out = sum(1 for p in pitched if not lo <= p + candidate <= hi)
            centre = abs((min(pitched) + max(pitched)) / 2 + candidate - (lo + hi) / 2)
            cost = out * 100 + centre
            if cost < best_cost:
                best_shift, best_cost = candidate, cost
        melody = [Note(pitch=n.pitch + best_shift if n.pitch is not None else None,
                       duration=n.duration, tie=n.tie) for n in phrase.notes]
        frame_chords = harmonize(phrase.notes, req.meter, req.mode, phrase.pickup_ticks, offset=offset,
                                 ending=phrase.is_ending)
        chords = [c.model_copy(update={"root_pc": (c.root_pc + best_shift) % 12}) for c in frame_chords]
        texture = resolve_texture(req.accompaniment, style or req.style or phrase.style)
        acc: list[AccompEvent] = []
        if texture != "none":
            voicings = voice_lead(chords, melody, req.mode, tonic_pc(req.tonic),
                                  below_melody=req.voice in ("S", "A"), ending=phrase.is_ending)
            acc = render(chords, voicings, melody, req.meter, texture, phrase.pickup_ticks)
        return Level(id=uuid.uuid4().hex[:12], tonic=req.tonic, mode=req.mode, meter=req.meter,
                     voice=req.voice, difficulty=req.difficulty, bars=req.bars, tempo_bpm=req.tempo_bpm,
                     pickup_ticks=phrase.pickup_ticks, melody=melody, chords=chords, accompaniment=acc,
                     phrase_ends=phrase.phrase_ends, cadences=phrase.cadences,
                     difficulty_score=difficulty.score(phrase), seed=req.seed)
