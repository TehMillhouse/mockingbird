"""Classify how a phrase ends, from the harmonizer's chords and the final melody note.

Labels (also the CAD_* tokens the model is trained on):
  PAC     ends on the tonic chord with the melody on the tonic
  IAC     ends on the tonic chord with the melody on the third or fifth
  HC      half cadence: ends on the dominant
  DEC     deceptive: dominant -> submediant
  OTHER   anything else
The rule is deliberately simple so labels are consistent across corpora; whether an
explicit dominant precedes the tonic is left for the model to learn from the notes.
"""
from __future__ import annotations

from ..schema import Note
from ..theory import scale_degree
from .viterbi import harmonize

LABELS = ("PAC", "IAC", "HC", "DEC", "OTHER")
TONIC = {"I", "i"}
DOMINANT = {"V", "V7", "vii°"}
SUBMEDIANT = {"vi", "VI"}


def classify(notes: list[Note], meter: str, mode: str, pickup_ticks: int = 0) -> str:
    """Cadence label of a phrase given as frame-space notes ending at the phrase end."""
    pitched = [n for n in notes if n.pitch is not None]
    if len(pitched) < 2:
        return "OTHER"
    chords = harmonize(notes, meter, mode, pickup_ticks, ending=False)
    if not chords:
        return "OTHER"
    last = chords[-1].roman
    prev = next((c.roman for c in reversed(chords[:-1]) if c.roman != last), None)
    degree = scale_degree(pitched[-1].pitch, mode)
    if last in TONIC:
        if degree == 1:
            return "PAC"
        if degree in (3, 5):
            return "IAC"
        return "OTHER"
    if last in DOMINANT:
        return "HC"
    if last in SUBMEDIANT and prev in DOMINANT:
        return "DEC"
    return "OTHER"


def label_phrases(notes: list[Note], phrase_ends: list[int], meter: str, mode: str,
                  pickup_ticks: int = 0) -> list[str]:
    """One label per phrase end. Each phrase is classified on its own notes."""
    labels: list[str] = []
    start = 0
    pos = 0
    idx = 0
    for end in phrase_ends:
        seg: list[Note] = []
        while idx < len(notes) and pos < end:
            n = notes[idx]
            take = min(n.duration, end - pos)
            seg.append(n.model_copy(update={"duration": take}) if take != n.duration else n)
            pos += take
            if take == n.duration:
                idx += 1
            else:
                notes = notes[:idx] + [n.model_copy(update={"duration": n.duration - take})] + notes[idx + 1:]
        pk = pickup_ticks if start == 0 else 0
        labels.append(classify(seg, meter, mode, pk))
        start = end
    return labels
