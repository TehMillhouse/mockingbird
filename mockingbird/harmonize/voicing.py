"""Voice-lead three accompaniment voices (bass, tenor, alto) under a melody.

Works in concert pitch on merged chord spans. For every span the soprano is the
melody note sounding at the span start. Candidate voicings are all placements of
chord tones in the voice ranges; a Viterbi search over spans minimises a cost made
of voice motion, parallel perfect intervals with any other voice (the melody
included), voice crossing, wide spacing, incomplete chords, doubled leading tones
and an inversion prior (root position preferred, cadential six-four at the
dominant before a final tonic).
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from ..schema import Chord, Note
from .chords import ChordType

# Concert ranges of the accompaniment voices when the melody is a high voice.
BASS_RANGE = (36, 57)  # C2..A3
INNER_LOW = 43  # G2

W_MOTION_INNER = 1.0
W_MOTION_BASS = 0.6
W_BASS_LEAP = 3.0  # extra when the bass leaps more than a fifth
W_PARALLEL = 6.0
W_CROSSING = 10.0
W_SPACING = 2.0
W_MISSING_THIRD = 4.0
W_MISSING_FIFTH = 1.0
W_MISSING_SEVENTH = 2.0
W_DOUBLED_LEADING = 3.0
W_INVERSION = {0: 0.0, 1: 0.6, 2: 2.0, 3: 3.0}
W_CONTRARY_BONUS = -0.5
KEEP = 40  # voicings kept per span before the search


@dataclass
class Voicing:
    bass: int
    tenor: int
    alto: int
    inversion: int

    def pitches(self) -> list[int]:
        return [self.bass, self.tenor, self.alto]


def soprano_at(notes: list[Note], start: int, duration: int) -> int | None:
    """Melody pitch sounding at `start`; if it is a rest, the first note in the span,
    else the last note before it."""
    pos = 0
    before = None
    first_in_span = None
    for n in notes:
        end = pos + n.duration
        if n.pitch is not None:
            if pos <= start < end:
                return n.pitch
            if pos < start:
                before = n.pitch
            elif start < pos < start + duration and first_in_span is None:
                first_in_span = n.pitch
        pos = end
    return first_in_span if first_in_span is not None else before


def _chord_type(c: Chord) -> ChordType:
    return ChordType(c.roman, c.root_pc, c.quality)


def _static_cost(v: Voicing, chord: ChordType, soprano: int | None, leading_pc: int | None,
                 below_melody: bool) -> float:
    cost = W_INVERSION[v.inversion]
    pcs = set(p % 12 for p in v.pitches())
    if soprano is not None:
        pcs.add(soprano % 12)
    root = chord.root_pc
    third = (root + (4 if chord.quality in ("maj", "dom7") else 3)) % 12
    fifth = (root + (6 if chord.quality == "dim" else 7)) % 12
    if third not in pcs:
        cost += W_MISSING_THIRD
    if fifth not in pcs:
        cost += W_MISSING_FIFTH
    if chord.quality == "dom7" and (root + 10) % 12 not in pcs:
        cost += W_MISSING_SEVENTH
    if leading_pc is not None:
        count = sum(1 for p in v.pitches() if p % 12 == leading_pc) + (1 if soprano is not None and soprano % 12 == leading_pc else 0)
        if count > 1:
            cost += W_DOUBLED_LEADING
    if soprano is not None:
        if below_melody and v.alto >= soprano:
            cost += W_CROSSING
        if soprano - v.alto > 12 and below_melody:
            cost += W_SPACING
    if v.alto - v.tenor > 12:
        cost += W_SPACING
    return cost


def _candidates(chord: ChordType, soprano: int | None, below_melody: bool, leading_pc: int | None) -> list[tuple[Voicing, float]]:
    pcs = sorted(chord.pcs)
    root = chord.root_pc
    if below_melody and soprano is not None:
        inner_hi = soprano - 1
    else:
        inner_hi = (soprano + 7) if soprano is not None else 72
    inner_lo = INNER_LOW
    bass_hi = min(BASS_RANGE[1], inner_hi - 3)
    basses = [p for p in range(BASS_RANGE[0], bass_hi + 1) if p % 12 in pcs]
    inners = [p for p in range(inner_lo, inner_hi + 1) if p % 12 in pcs]
    out: list[tuple[Voicing, float]] = []
    for b in basses:
        interval = (b - root) % 12
        inversion = 0 if interval == 0 else 1 if interval in (3, 4) else 2 if interval in (6, 7) else 3
        for t, a in product(inners, inners):
            if not (b + 3 <= t <= a):
                continue
            if t - b > 19 or a - t > 12:
                continue
            v = Voicing(b, t, a, inversion)
            out.append((v, _static_cost(v, chord, soprano, leading_pc, below_melody)))
    out.sort(key=lambda x: x[1])
    return out[:KEEP]


def _parallels(prev: list[int], cur: list[int]) -> int:
    """Count parallel perfect fifths/octaves between voice pairs (lists aligned)."""
    n = 0
    for i in range(len(prev)):
        for j in range(i + 1, len(prev)):
            if prev[i] is None or prev[j] is None or cur[i] is None or cur[j] is None:
                continue
            di = (prev[j] - prev[i]) % 12
            dj = (cur[j] - cur[i]) % 12
            if di == dj and di in (0, 7) and prev[i] != cur[i] and (cur[i] - prev[i]) * (cur[j] - prev[j]) > 0:
                n += 1
    return n


def _transition_cost(a: Voicing, b: Voicing, sop_a: int | None, sop_b: int | None) -> float:
    cost = W_MOTION_INNER * (abs(b.tenor - a.tenor) + abs(b.alto - a.alto))
    bass_move = abs(b.bass - a.bass)
    cost += W_MOTION_BASS * bass_move
    if bass_move > 7:
        cost += W_BASS_LEAP
    cost += W_PARALLEL * _parallels([a.bass, a.tenor, a.alto, sop_a], [b.bass, b.tenor, b.alto, sop_b])
    if sop_a is not None and sop_b is not None and sop_a != sop_b and a.bass != b.bass:
        if (sop_b - sop_a) * (b.bass - a.bass) < 0:
            cost += W_CONTRARY_BONUS
    return cost


def voice(chords: list[Chord], melody: list[Note], mode: str, tonic_pc: int, *,
          below_melody: bool = True, ending: bool = False) -> list[Voicing]:
    """One Voicing per chord span, chosen by Viterbi over per-span candidates."""
    if not chords:
        return []
    leading_pc = (tonic_pc + 11) % 12
    sops = [soprano_at(melody, c.start, c.duration) for c in chords]
    types = [_chord_type(c) for c in chords]
    cands = [_candidates(t, s, below_melody, leading_pc) for t, s in zip(types, sops)]
    # cadential six-four: allow the dominant before a final tonic to sit on its fifth
    if ending and len(chords) >= 2 and types[-2].is_dominant and chords[-1].roman in ("I", "i"):
        cands[-2] = [(v, c - W_INVERSION[2] if v.inversion == 2 else c) for v, c in cands[-2]]
    best: list[list[float]] = []
    back: list[list[int]] = []
    best.append([c for _, c in cands[0]])
    back.append([-1] * len(cands[0]))
    for i in range(1, len(chords)):
        row, arg = [], []
        for v, sc in cands[i]:
            b, bk = float("inf"), -1
            for k, (pv, _) in enumerate(cands[i - 1]):
                s = best[i - 1][k] + _transition_cost(pv, v, sops[i - 1], sops[i])
                if s < b:
                    b, bk = s, k
            row.append(b + sc)
            arg.append(bk)
        best.append(row)
        back.append(arg)
    j = min(range(len(cands[-1])), key=lambda x: best[-1][x])
    path = [j]
    for i in range(len(chords) - 1, 0, -1):
        j = back[i][j]
        path.append(j)
    path.reverse()
    return [cands[i][j][0] for i, j in enumerate(path)]
