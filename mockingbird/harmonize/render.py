"""Turn voiced chord spans into accompaniment events in a style-dependent texture.

Textures:
  chorale  the three lower voices move with the melody: a new attack at every melody
           onset inside the span, sustained otherwise (choir-like)
  block    one sustained chord per span
  oompah   bass on the strong beats, upper voices on the other beats (folk dance)
  broken   eighth-note figure bass, tenor, alto, tenor through the span (lied)
  none     no accompaniment
`auto` picks by style: chorale/choral/renaissance -> chorale, folk -> oompah, lied -> broken.
"""
from __future__ import annotations

from ..schema import AccompEvent, Chord, Note
from ..theory import TICKS_PER_QUARTER, bar_ticks, beat_ticks, strong_beat_ticks
from .voicing import Voicing

STYLES = ("auto", "chorale", "block", "oompah", "broken", "none")
STYLE_TEXTURE = {"chorale": "chorale", "choral": "chorale", "renaissance": "chorale",
                 "folk": "oompah", "lied": "broken"}
EIGHTH = TICKS_PER_QUARTER // 2


def resolve_texture(accompaniment: str, style: str | None) -> str:
    if accompaniment != "auto":
        return accompaniment
    return STYLE_TEXTURE.get(style or "", "chorale")


def _melody_onsets(melody: list[Note]) -> list[int]:
    out, pos = [], 0
    for n in melody:
        if n.pitch is not None:
            out.append(pos)
        pos += n.duration
    return out


def render(chords: list[Chord], voicings: list[Voicing], melody: list[Note], meter: str,
           texture: str, pickup_ticks: int = 0) -> list[AccompEvent]:
    if texture == "none" or not chords:
        return []
    bt = bar_ticks(meter)
    beat = beat_ticks(meter)
    strong = set(strong_beat_ticks(meter))
    onsets = _melody_onsets(melody)
    events: list[AccompEvent] = []

    def in_bar(t: int) -> int:
        return (t - pickup_ticks) % bt

    for c, v in zip(chords, voicings):
        end = c.start + c.duration
        full = v.pitches()
        if texture == "block":
            events.append(AccompEvent(start=c.start, duration=c.duration, pitches=full))
        elif texture == "chorale":
            cuts = sorted({c.start, *[o for o in onsets if c.start < o < end], end})
            for a, b in zip(cuts, cuts[1:]):
                events.append(AccompEvent(start=a, duration=b - a, pitches=full))
        elif texture == "oompah":
            t = c.start
            while t < end:
                d = min(beat, end - t)
                if in_bar(t) in strong or in_bar(t) % beat != 0:
                    events.append(AccompEvent(start=t, duration=d, pitches=[v.bass]))
                else:
                    events.append(AccompEvent(start=t, duration=d, pitches=[v.tenor, v.alto]))
                t += d
        elif texture == "broken":
            figure = (v.bass, v.tenor, v.alto, v.tenor)
            t = c.start
            i = 0
            while t < end:
                d = min(EIGHTH, end - t)
                events.append(AccompEvent(start=t, duration=d, pitches=[figure[i % 4]]))
                t += d
                i += 1
        else:
            raise ValueError(f"unknown texture {texture}")
    return events
