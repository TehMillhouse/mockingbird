"""Music-theory constants and helpers shared by every stage.

All durations are integer ticks with 24 ticks per quarter note, so 32nd notes and
(later) triplets are exactly representable. The model works in a fixed "frame":
melodies are transposed so that the tonic is C for major and A for minor. In that
frame both modes share the diatonic pitch-class set {0,2,4,5,7,9,11}.
"""
from __future__ import annotations

from typing import Literal

TICKS_PER_QUARTER = 24

Mode = Literal["major", "minor"]
Voice = Literal["S", "A", "T", "B"]
Style = Literal["folk", "chorale", "renaissance", "lied", "choral"]

# Meters supported by the tokenizer. Source meters with a denominator below 4 (4/2, 3/1,
# 2/2 ...) are halved until the denominator is 4 and the note values scaled with them;
# anything still outside this list is dropped at data-build time.
METERS: tuple[str, ...] = ("4/4", "3/4", "2/4", "6/8", "3/8", "6/4", "9/8")

# Note durations the model may emit. Longer or odd values are split into these with ties.
DURATIONS: tuple[int, ...] = (3, 6, 9, 12, 18, 24, 36, 48, 72, 96, 144, 192)

# Frame pitch window: C3 .. C6. Phrases are octave-shifted into it at build time.
PITCH_MIN = 48
PITCH_MAX = 84

# Concert singing ranges (MIDI) used for span constraints and final placement.
VOICE_RANGES: dict[str, tuple[int, int]] = {
    "S": (60, 79),
    "A": (55, 74),
    "T": (50, 69),
    "B": (43, 64),
}

DIATONIC_PCS = frozenset({0, 2, 4, 5, 7, 9, 11})
# In the A-minor frame, raised 7 (G#) and raised 6 (F#) are conventional, not chromatic.
MINOR_RAISED_PCS = frozenset({8, 6})

PC_NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
NAME_TO_PC = {
    "C": 0, "B#": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "Fb": 4,
    "F": 5, "E#": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10,
    "Bb": 10, "B": 11, "Cb": 11,
}


def frame_tonic_pc(mode: str) -> int:
    return 0 if mode == "major" else 9


def tonic_pc(name: str) -> int:
    """Pitch class of a tonic name such as 'F#', 'Bb' or 'e-' (music21 style flat)."""
    n = name.strip().replace("-", "b")
    if n[:1].islower():
        n = n[0].upper() + n[1:]
    return NAME_TO_PC[n]


def frame_offset(tonic: str, mode: str) -> int:
    """Semitones to subtract from concert pitch to reach the C/A frame (0..11)."""
    return (tonic_pc(tonic) - frame_tonic_pc(mode)) % 12


def scale_degree(frame_pitch: int, mode: str) -> int | None:
    """1-based scale degree in the frame, or None for a non-diatonic pitch class. In
    minor the raised sixth and seventh count as degrees 6 and 7."""
    pc = (frame_pitch - frame_tonic_pc(mode)) % 12
    if mode == "major":
        steps = (0, 2, 4, 5, 7, 9, 11)
        return steps.index(pc) + 1 if pc in steps else None
    table = {0: 1, 2: 2, 3: 3, 5: 4, 7: 5, 8: 6, 9: 6, 10: 7, 11: 7}
    return table.get(pc)


def is_diatonic(frame_pitch: int, mode: str, allow_raised: bool = True) -> bool:
    pc = frame_pitch % 12
    if pc in DIATONIC_PCS:
        return True
    return mode == "minor" and allow_raised and pc in MINOR_RAISED_PCS


def bar_ticks(meter: str) -> int:
    num, den = meter.split("/")
    return int(num) * (TICKS_PER_QUARTER * 4 // int(den))


def beat_ticks(meter: str) -> int:
    """Length of one felt beat. Compound meters (6/8, 3/8) beat in dotted quarters."""
    num, den = (int(x) for x in meter.split("/"))
    if den == 8 and num % 3 == 0:
        return TICKS_PER_QUARTER * 3
    return TICKS_PER_QUARTER * 4 // den


def strong_beat_ticks(meter: str) -> tuple[int, ...]:
    """Tick positions within a bar that count as strong (for harmony and difficulty)."""
    bt = beat_ticks(meter)
    num, den = (int(x) for x in meter.split("/"))
    beats = bar_ticks(meter) // bt
    if beats == 4:
        return (0, 2 * bt)
    if beats == 2:
        return (0,)
    if beats == 3:
        return (0,)
    return tuple(range(0, bar_ticks(meter), bt))


def pitch_name(midi: int) -> str:
    return f"{PC_NAMES[midi % 12]}{midi // 12 - 1}"
