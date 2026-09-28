"""Cut long phrases into training windows of at most MAX_BARS bars."""
from __future__ import annotations

from ..schema import Note, Phrase
from ..theory import bar_ticks, beat_ticks
from ..tokenizer import normalize

MAX_BARS = 32
MIN_CUT_BARS = 24
OVERLAP_BARS = 8


def bars_of(phrase: Phrase) -> list[list[Note]]:
    """Group a normalized phrase's notes by bar. The pickup, if any, is bar 0."""
    bt = bar_ticks(phrase.meter)
    bars: list[list[Note]] = [[]]
    pos = (-phrase.pickup_ticks) % bt if phrase.pickup_ticks else 0
    for n in phrase.notes:
        bars[-1].append(n)
        pos += n.duration
        if pos >= bt:
            pos = 0
            bars.append([])
    if not bars[-1]:
        bars.pop()
    return bars


def _good_cut(prev_bar: list[Note], next_bar: list[Note], meter: str) -> bool:
    """A cut is good when the previous bar ends with a rest of at least a beat, or the
    last note of the previous bar is not tied into the next one."""
    if not prev_bar or not next_bar:
        return False
    last = prev_bar[-1]
    if last.pitch is None and last.duration >= beat_ticks(meter):
        return True
    return not last.tie


def _phrase_cut(bars: list[list[Note]], cut: int, phrase_ends: list[int]) -> bool:
    """True when a phrase ends exactly at the start of bar `cut`."""
    tick = sum(n.duration for b in bars[:cut] for n in b)
    return tick in phrase_ends


def _is_rest_bar(bar: list[Note]) -> bool:
    return all(n.pitch is None for n in bar)


def trim_rest_bars(phrase: Phrase) -> Phrase:
    """Drop rest-only bars at both ends (instrumental intros and outros)."""
    bars = bars_of(phrase)
    pickup = phrase.pickup_ticks
    start = 0
    while start < len(bars) and _is_rest_bar(bars[start]):
        start += 1
        pickup = 0
    end = len(bars)
    while end > start and _is_rest_bar(bars[end - 1]):
        end -= 1
    if start == 0 and end == len(bars):
        return phrase
    removed = sum(n.duration for b in bars[:start] for n in b)
    notes = [n.model_copy() for b in bars[start:end] for n in b]
    total = sum(n.duration for n in notes)
    return phrase.model_copy(update={"notes": notes, "pickup_ticks": pickup,
                                     "phrase_ends": _shift_ends(phrase.phrase_ends, removed, total)})


def _shift_ends(ends: list[int], removed: int, total: int) -> list[int]:
    """Phrase ends of a sub-range: shift by the removed prefix and keep those inside.
    A window that stops mid-phrase simply has no phrase end at its total."""
    return [e - removed for e in ends if 0 < e - removed <= total]


def segment(phrase: Phrase) -> list[Phrase]:
    phrase = trim_rest_bars(normalize(phrase))
    bars = bars_of(phrase)
    has_pickup = phrase.pickup_ticks > 0
    n_full = len(bars) - (1 if has_pickup else 0)
    if n_full <= MAX_BARS:
        return [phrase]
    out: list[Phrase] = []
    start = 0  # index into `bars`
    while start < len(bars):
        limit = min(start + MAX_BARS + (1 if start == 0 and has_pickup else 0), len(bars))
        end = limit
        if limit < len(bars):
            lo = start + MIN_CUT_BARS
            for cut in range(limit, lo, -1):  # prefer a phrase end, then any clean bar line
                if _phrase_cut(bars, cut, phrase.phrase_ends):
                    end = cut
                    break
            else:
                for cut in range(limit, lo, -1):
                    if _good_cut(bars[cut - 1], bars[cut], phrase.meter):
                        end = cut
                        break
        window = [n for b in bars[start:end] for n in b]
        if window:
            pickup = phrase.pickup_ticks if start == 0 else 0
            removed = sum(n.duration for b in bars[:start] for n in b)
            total = sum(n.duration for n in window)
            out.append(trim_rest_bars(phrase.model_copy(update={
                "notes": [n.model_copy() for n in window],
                "pickup_ticks": pickup,
                "is_ending": phrase.is_ending and end >= len(bars),
                "phrase_ends": _shift_ends(phrase.phrase_ends, removed, total),
                "source": f"{phrase.source}@{start}",
            })))
        if end >= len(bars):
            break
        start = max(end - OVERLAP_BARS, start + 1)
    # avoid a tiny final window that is mostly a repeat of the previous one
    if len(out) > 1 and len(bars_of(out[-1])) < MIN_CUT_BARS // 2:
        out.pop()
    return out
