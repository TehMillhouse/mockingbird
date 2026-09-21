"""Turn a chord list into accompaniment events below the melody."""
from __future__ import annotations

from itertools import product

from ..schema import AccompEvent, Chord, Note
from ..theory import beat_ticks
from .chords import ChordType

STYLES = ("block", "arpeggio", "none")


def _chord_pcs(c: Chord) -> list[int]:
    return sorted(ChordType(c.roman, c.root_pc, c.quality).pcs)


def _voicing(pcs: list[int], root_pc: int, lo: int, hi: int, prev: list[int] | None) -> list[int]:
    """Close-position voicing of the chord's upper notes inside [lo, hi] that moves
    least from the previous voicing (root is handled separately by the bass)."""
    upper = [pc for pc in pcs if pc != root_pc] or [root_pc]
    options = []
    for pc in upper:
        options.append([p for p in range(lo, hi + 1) if p % 12 == pc])
    best, best_cost = None, float("inf")
    for combo in product(*options):
        combo = sorted(set(combo))
        if len(combo) < len(upper):
            continue
        spread = combo[-1] - combo[0]
        if spread > 12:
            continue
        cost = spread * 0.1
        if prev:
            cost += sum(min(abs(p - q) for q in prev) for p in combo)
        else:
            cost += abs(sum(combo) / len(combo) - (lo + hi) / 2)
        if cost < best_cost:
            best, best_cost = combo, cost
    return best or [lo + ((pc - lo) % 12) for pc in upper]


def render(chords: list[Chord], melody: list[Note], meter: str, style: str = "block") -> list[AccompEvent]:
    if style == "none" or not chords:
        return []
    melody_low = min((n.pitch for n in melody if n.pitch is not None), default=60)
    upper_hi = melody_low - 3
    upper_lo = upper_hi - 14
    bass_hi = upper_lo - 1
    bass_lo = bass_hi - 11
    beat = beat_ticks(meter)
    events: list[AccompEvent] = []
    prev_upper: list[int] | None = None
    for c in chords:
        pcs = _chord_pcs(c)
        bass = next(p for p in range(bass_hi, bass_lo - 1, -1) if p % 12 == c.root_pc)
        upper = _voicing(pcs, c.root_pc, upper_lo, upper_hi, prev_upper)
        prev_upper = upper
        if style == "block":
            events.append(AccompEvent(start=c.start, duration=c.duration, pitches=[bass] + upper))
        else:  # arpeggio: bass on the first beat, upper notes cycling on the following beats
            t = c.start
            end = c.start + c.duration
            i = 0
            while t < end:
                d = min(beat, end - t)
                if i == 0:
                    events.append(AccompEvent(start=t, duration=d, pitches=[bass]))
                else:
                    events.append(AccompEvent(start=t, duration=d, pitches=[upper[(i - 1) % len(upper)]]))
                t += d
                i += 1
    return events
