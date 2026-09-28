"""The built-in warm-up: fixed exercises on scale degrees, finished like a generated
melody (placed in the requested key and voice, harmonized and accompanied)."""
from __future__ import annotations

from ..schema import Note, Phrase
from ..theory import TICKS_PER_QUARTER, VOICE_RANGES, bar_ticks, frame_offset

METER = "4/4"
# (scale degree 1..8, length in quarters), in order
EXERCISES: list[list[tuple[int, int]]] = [
    # scale up and down
    [(d, 1) for d in (1, 2, 3, 4, 5, 6, 7, 8, 7, 6, 5, 4, 3, 2)] + [(1, 2)],
    # up from the tonic, back to it between steps
    [(d, 1) for d in (1, 2, 1, 3, 1, 4, 1, 5, 1, 6, 1, 7, 1)] + [(8, 2)],
    # down from the upper tonic as a pedal point
    [(d, 1) for d in (8, 7, 8, 6, 8, 5, 8, 4, 8, 3, 8, 2, 8)] + [(1, 2)],
    # arpeggio
    [(d, 1) for d in (1, 3, 5, 8, 5, 3)] + [(1, 2)],
    # thirds up, back down the arpeggio
    [(d, 1) for d in (1, 3, 2, 4, 3, 5, 4, 6, 5, 7, 6, 8, 5, 3)] + [(1, 2)],
]
_STEPS = {"major": (0, 2, 4, 5, 7, 9, 11, 12), "minor": (0, 2, 3, 5, 7, 8, 10, 12)}
_FRAME_TONIC = {"major": 60, "minor": 57}  # C4 and A3 in the C/A frame


def warmup_phrase(mode: str) -> Phrase:
    """The exercises in the C/A frame, each padded to whole bars and followed by a bar
    of rest to breathe."""
    bt = bar_ticks(METER)
    notes: list[Note] = []
    ends: list[int] = []
    for i, exercise in enumerate(EXERCISES):
        for degree, quarters in exercise:
            pitch = _FRAME_TONIC[mode] + _STEPS[mode][degree - 1]
            notes.append(Note(pitch=pitch, duration=quarters * TICKS_PER_QUARTER))
        t = sum(n.duration for n in notes)
        ends.append(t)
        if t % bt:
            notes.append(Note(pitch=None, duration=bt - t % bt))
        if i < len(EXERCISES) - 1:
            notes.append(Note(pitch=None, duration=bt))
    return Phrase(mode=mode, meter=METER, style="folk", notes=notes, is_ending=True, phrase_ends=ends)


def warmup_shift(tonic: str, mode: str, voice: str) -> int:
    """Transposition from the frame that centres the octave in the voice's range. The
    exercises dwell on both tonics, so centring beats minimising out-of-range notes."""
    lo, hi = VOICE_RANGES[voice]
    offset = frame_offset(tonic, mode)
    centre = _FRAME_TONIC[mode] + 6
    return min((offset + k for k in (-24, -12, 0, 12, 24)), key=lambda s: abs(centre + s - (lo + hi) / 2))
