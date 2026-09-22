"""Fit chords to a frame-space melody with a Viterbi search.

Segments are one beat long. Emission: beat-weighted share of melody notes in the
segment that are chord tones (passing tones between chord tones count a little).
Transition: a hand-set functional harmony table plus a bass-motion penalty, with a
cost for changing chord that is small on strong beats and larger on weak ones, so
the harmonic rhythm follows the melody but changes land on the beat. Consecutive
equal chords are merged into one span. When the melody is an ending, the last bar
is nudged towards the tonic, the bar before towards the dominant and the one before
that towards a pre-dominant (ii or IV).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..schema import Chord, Note
from ..theory import bar_ticks, beat_ticks, strong_beat_ticks
from .chords import ChordType, alphabet

OTHER = -2.5  # log-prob for transitions not listed below
CHANGE_STRONG = -0.15  # cost of changing chord on a strong beat
CHANGE_WEAK = -0.9  # ... on a weak beat
SECONDARY_PRIOR = -1.5
END_TONIC_BONUS = 1.0
END_DOMINANT_BONUS = 0.6
END_PREDOMINANT_BONUS = 0.3
PREDOMINANTS = {"ii", "IV", "ii°", "iv"}

MAJOR_T: dict[str, dict[str, float]] = {
    "I": {"IV": -0.7, "V": -0.7, "V7": -1.0, "vi": -1.2, "ii": -1.2, "iii": -2.0, "vii°": -2.2, "V/V": -2.0, "V/ii": -2.2},
    "ii": {"V": -0.4, "V7": -0.6, "vii°": -1.8, "IV": -2.0, "I": -2.0},
    "iii": {"vi": -0.8, "IV": -1.0, "ii": -1.5, "I": -1.8},
    "IV": {"V": -0.6, "I": -0.9, "ii": -1.2, "V7": -0.9, "vii°": -1.8, "vi": -2.0},
    "V": {"I": -0.3, "vi": -1.3, "V7": -1.0, "IV": -2.2, "ii": -2.5},
    "V7": {"I": -0.2, "vi": -1.3},
    "vi": {"ii": -0.8, "IV": -0.8, "V": -1.2, "iii": -1.8, "I": -1.8},
    "vii°": {"I": -0.3, "iii": -1.8},
    "V/V": {"V": -0.2, "V7": -0.4},
    "V/ii": {"ii": -0.2},
}

MINOR_T: dict[str, dict[str, float]] = {
    "i": {"iv": -0.7, "V": -0.7, "V7": -1.0, "VI": -1.2, "ii°": -1.3, "III": -1.6, "VII": -1.6, "vii°": -2.2, "V/iv": -2.0, "V/V": -2.2},
    "ii°": {"V": -0.4, "V7": -0.6, "vii°": -1.8, "i": -2.0},
    "III": {"VI": -0.8, "iv": -1.0, "VII": -1.2, "i": -1.5},
    "iv": {"V": -0.6, "i": -0.9, "ii°": -1.4, "V7": -0.9, "VII": -1.8, "VI": -2.0},
    "V": {"i": -0.3, "VI": -1.3, "V7": -1.0, "iv": -2.2},
    "V7": {"i": -0.2, "VI": -1.3},
    "VI": {"ii°": -1.0, "iv": -0.8, "V": -1.2, "III": -1.5, "VII": -1.5, "i": -1.8},
    "VII": {"III": -0.5, "i": -1.5, "iv": -1.8},
    "vii°": {"i": -0.3},
    "V/iv": {"iv": -0.2},
    "V/V": {"V": -0.2, "V7": -0.4},
}


@dataclass
class Segment:
    start: int
    duration: int
    weights: list[tuple[int, float, int | None, int | None]]  # (pc, weight, prev_pitch, next_pitch)
    strong: bool
    bar_index: int  # 0 = pickup or first bar
    is_pickup: bool = False


def build_segments(notes: list[Note], meter: str, pickup_ticks: int) -> list[Segment]:
    bt = bar_ticks(meter)
    beat = beat_ticks(meter)
    total = sum(n.duration for n in notes)
    strong_pos = set(strong_beat_ticks(meter))
    segments: list[Segment] = []
    t = 0
    if pickup_ticks:
        segments.append(Segment(0, pickup_ticks, [], True, 0, True))
        t = pickup_ticks
    while t < total:
        in_bar = (t - pickup_ticks) % bt
        bar_index = (t - pickup_ticks) // bt + (1 if pickup_ticks else 0)
        segments.append(Segment(t, min(beat, total - t), [], in_bar in strong_pos, bar_index))
        t += beat
    pitched_idx = [i for i, n in enumerate(notes) if n.pitch is not None]
    pos = 0
    for i, n in enumerate(notes):
        if n.pitch is not None:
            in_bar = (pos - pickup_ticks) % bt
            w_beat = 2.0 if in_bar in strong_pos else 1.0 if in_bar % beat == 0 else 0.5
            k = pitched_idx.index(i)
            prev_p = notes[pitched_idx[k - 1]].pitch if k > 0 else None
            next_p = notes[pitched_idx[k + 1]].pitch if k + 1 < len(pitched_idx) else None
            for seg in segments:
                overlap = min(pos + n.duration, seg.start + seg.duration) - max(pos, seg.start)
                if overlap > 0:
                    seg.weights.append((n.pitch % 12, w_beat * overlap, prev_p, next_p))
        pos += n.duration
    return segments


def emission(seg: Segment, chord: ChordType) -> float:
    if not seg.weights:
        return 0.0
    pcs = chord.pcs
    total = sum(w for _, w, _, _ in seg.weights)
    cover = 0.0
    for pc, w, prev_p, next_p in seg.weights:
        if pc in pcs:
            cover += w
        elif (prev_p is not None and next_p is not None and prev_p % 12 in pcs and next_p % 12 in pcs
              and abs(prev_p - next_p) <= 4):
            cover += 0.3 * w  # passing or neighbour tone between chord tones
    return math.log(cover / total + 0.05)


def transition(a: ChordType, b: ChordType, table: dict[str, dict[str, float]], strong: bool) -> float:
    if a.roman == b.roman:
        return 0.0
    lp = table.get(a.roman, {}).get(b.roman, OTHER) + (CHANGE_STRONG if strong else CHANGE_WEAK)
    if b.is_secondary:
        lp += SECONDARY_PRIOR
    d = min((b.root_pc - a.root_pc) % 12, (a.root_pc - b.root_pc) % 12)
    if d > 5:
        lp -= 0.3 * (d - 5)
    return lp


def harmonize(notes: list[Note], meter: str, mode: str, pickup_ticks: int = 0, *,
              offset: int = 0, ending: bool = False) -> list[Chord]:
    """Return merged chord spans. `offset` is the semitone shift from the frame to
    concert pitch, used only for the chord symbols."""
    segs = build_segments(notes, meter, pickup_ticks)
    if not segs:
        return []
    chords = alphabet(mode)
    table = MAJOR_T if mode == "major" else MINOR_T
    n = len(chords)
    tonic_idx = 0
    dom_idx = next(i for i, c in enumerate(chords) if c.roman == "V")
    last_bar = segs[-1].bar_index
    neg = float("-inf")
    score = [[neg] * n for _ in segs]
    back = [[-1] * n for _ in segs]

    def bonus(seg: Segment, c: ChordType) -> float:
        if not ending:
            return 0.0
        if seg.bar_index == last_bar and c.roman in ("I", "i"):
            return END_TONIC_BONUS
        if seg.bar_index == last_bar - 1 and c.is_dominant:
            return END_DOMINANT_BONUS
        if seg.bar_index == last_bar - 2 and c.roman in PREDOMINANTS:
            return END_PREDOMINANT_BONUS
        return 0.0

    for j, c in enumerate(chords):
        if segs[0].is_pickup:
            start_lp = 0.0 if j in (tonic_idx, dom_idx) else -3.0
        else:
            start_lp = 0.0 if j == tonic_idx else -2.0 if j == dom_idx else -3.0
        score[0][j] = start_lp + emission(segs[0], c) + bonus(segs[0], c)
    for i in range(1, len(segs)):
        em = [emission(segs[i], c) + bonus(segs[i], c) for c in chords]
        for j, c in enumerate(chords):
            best, arg = neg, -1
            for k, prev in enumerate(chords):
                if score[i - 1][k] == neg:
                    continue
                s = score[i - 1][k] + transition(prev, c, table, segs[i].strong)
                if s > best:
                    best, arg = s, k
            score[i][j] = best + em[j]
            back[i][j] = arg
    j = max(range(n), key=lambda x: score[-1][x])
    path = [j]
    for i in range(len(segs) - 1, 0, -1):
        j = back[i][j]
        path.append(j)
    path.reverse()
    out: list[Chord] = []
    prev_pickup = False
    for seg, j in zip(segs, path):
        c = chords[j]
        if out and out[-1].roman == c.roman and not prev_pickup:
            out[-1] = out[-1].model_copy(update={"duration": out[-1].duration + seg.duration})
        else:
            out.append(Chord(start=seg.start, duration=seg.duration, root_pc=c.root_pc,
                             quality=c.quality, roman=c.roman, symbol=c.symbol(offset)))
        prev_pickup = seg.is_pickup  # the pickup keeps its own span
    return out
