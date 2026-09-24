"""Per-step logit masks that make sampled token streams well-formed and singable.

Enforced: token grammar (pitch/rest -> duration -> pitch/rest/TIE/BAR), exact bar fill,
the requested bar count (EOS only after the last BAR), a pitch-span cap so the melody
fits the singer's range after transposition, a per-difficulty leap cap, for the two
easiest levels a diatonic-only pitch set, and a repeat limit: a bar that is identical
(ties ignored) to one already sampled MAX_BAR_REPEATS times cannot be completed again.
The REMAIN_k countdown is forced at the start of each of the last bars and forbidden
elsewhere, so every level ends the way the training pieces end. A phrase plan (bars per
phrase and a cadence label per phrase) is forced the same way through PHRASE_END_IN_k
and CAD_x tokens at bar starts, in the order REMAIN, PHRASE_END_IN, CAD.
"""
from __future__ import annotations

from collections import Counter

import torch

from .. import tokenizer as tk
from ..theory import PITCH_MAX, PITCH_MIN, VOICE_RANGES, bar_ticks, is_diatonic

LEAP_CAP = {1: 5, 2: 7, 3: 9, 4: 12, 5: 24}
MAX_BAR_REPEATS = 2
SPAN_CAP = {1: 12, 2: 14, 3: 17, 4: 19, 5: 19}


class ConstraintState:
    def __init__(self, *, mode: str, meter: str, voice: str, difficulty: int, bars: int,
                 phrase_bars: int | None = None, cadences: list[str] | None = None):
        self.mode = mode
        # phrase plan: last bar index (0-based) of each phrase and its cadence label
        pb = phrase_bars or bars
        ends = list(range(pb - 1, bars, pb))
        if not ends or ends[-1] != bars - 1:
            ends.append(bars - 1)
        if cadences is None:
            cadences = ["HC"] * (len(ends) - 1) + ["PAC"]
        if len(cadences) != len(ends):
            raise ValueError(f"plan has {len(ends)} phrases but {len(cadences)} cadence labels")
        self.plan = list(zip(ends, cadences))
        self.bt = bar_ticks(meter)
        lo, hi = VOICE_RANGES[voice]
        self.span = min(hi - lo, SPAN_CAP[difficulty])
        self.leap = LEAP_CAP[difficulty]
        self.diatonic_only = difficulty <= 2
        self.allow_raised = difficulty >= 2
        self.target_bars = bars
        self._pitch_mask = torch.zeros(tk.VOCAB_SIZE, dtype=torch.bool)
        for p in range(PITCH_MIN, PITCH_MAX + 1):
            if not self.diatonic_only or is_diatonic(p, mode, allow_raised=self.allow_raised):
                self._pitch_mask[tk.tid(f"P{p}")] = True
        self._dur_ids = [(tk.tid(f"D{d}"), d) for d in tk.DURATIONS]

    def _scan(self, tokens: list[int]):
        """Replay the stream: returns (expect, pos_in_bar, bars_done, last, lo, hi,
        seen_bars, partial_bar) where bars are tuples of event tokens without ties."""
        names = [tk.VOCAB[t] for t in tokens]
        i = tk.PREFIX_LEN
        if i < len(names) and names[i] == tk.PICKUP:
            i += 1
        pos, bars = 0, 0
        last = lo = hi = None
        expect = "pitch"
        seen: Counter = Counter()
        partial: list[str] = []
        remain_done = False  # countdown token already emitted for the current bar
        phrase_done = False
        cad_done = False
        while i < len(names):
            t = names[i]
            if t.startswith("REMAIN_"):
                remain_done = True
            elif t.startswith("PHRASE_END_IN_"):
                phrase_done = True
            elif t.startswith("CAD_"):
                cad_done = True
            elif t == tk.BAR:
                remain_done = phrase_done = cad_done = False
                bars += 1
                pos = 0
                expect = "pitch"
                seen[tuple(partial)] += 1
                partial = []
            elif t == tk.TIE:
                expect = "pitch"
            elif t == tk.REST:
                partial.append(t)
                expect = "dur"
            elif t.startswith("P"):
                p = int(t[1:])
                partial.append(t)
                last = p
                lo = p if lo is None else min(lo, p)
                hi = p if hi is None else max(hi, p)
                expect = "dur"
            elif t.startswith("D"):
                partial.append(t)
                pos += int(t[1:])
                expect = "after_dur"
            i += 1
        return expect, pos, bars, last, lo, hi, seen, tuple(partial), (remain_done, phrase_done, cad_done)

    def allowed(self, tokens: list[int]) -> torch.Tensor:
        expect, pos, bars, last, lo, hi, seen, partial, flags = self._scan(tokens)
        remain_done, phrase_done, cad_done = flags
        mask = torch.zeros(tk.VOCAB_SIZE, dtype=torch.bool)
        if bars >= self.target_bars:
            mask[tk.tid(tk.EOS)] = True
            return mask
        at_bar_start = not partial and expect == "pitch"
        remaining = self.target_bars - bars
        if remaining <= tk.COUNTDOWN and at_bar_start and not remain_done:
            mask[tk.tid(f"REMAIN_{remaining}")] = True
            return mask
        if at_bar_start:
            end_bar, label = next(((e, c) for e, c in self.plan if e >= bars), self.plan[-1])
            k = end_bar - bars + 1
            if k <= tk.COUNTDOWN and not phrase_done:
                mask[tk.tid(f"PHRASE_END_IN_{k}")] = True
                return mask
            if k == 1 and not cad_done:
                mask[tk.tid(f"CAD_{label}")] = True
                return mask
        if expect == "dur":
            room = self.bt - pos
            fitting = [(tid_, d) for tid_, d in self._dur_ids if d <= room]
            for tid_, d in fitting:
                completes_repeat = d == room and seen[partial + (f"D{d}",)] >= MAX_BAR_REPEATS
                if not completes_repeat or len(fitting) == 1:
                    mask[tid_] = True
            return mask
        if expect == "after_dur":
            if pos >= self.bt:
                mask[tk.tid(tk.BAR)] = True
                return mask
            if last is not None and tokens and tk.VOCAB[tokens[-1]].startswith("D"):
                # a tie is only meaningful after a pitched note
                prev_event = next((tk.VOCAB[t] for t in reversed(tokens[:-1])
                                   if tk.VOCAB[t].startswith("P") or tk.VOCAB[t] == tk.REST), None)
                if prev_event is not None and prev_event.startswith("P"):
                    mask[tk.tid(tk.TIE)] = True
        # a new note or rest
        mask[tk.tid(tk.REST)] = True
        pm = self._pitch_mask.clone()
        for p in range(PITCH_MIN, PITCH_MAX + 1):
            tid_ = tk.tid(f"P{p}")
            if not pm[tid_]:
                continue
            if lo is not None and (max(hi, p) - min(lo, p)) > self.span:
                pm[tid_] = False
            elif last is not None and abs(p - last) > self.leap:
                pm[tid_] = False
        if not pm.any():  # leap cap conflicts with span; fall back to span only
            for p in range(PITCH_MIN, PITCH_MAX + 1):
                tid_ = tk.tid(f"P{p}")
                if self._pitch_mask[tid_] and (lo is None or (max(hi, p) - min(lo, p)) <= self.span):
                    pm[tid_] = True
        mask |= pm
        return mask
