"""Serialize a Level to ABC, MusicXML and MIDI.

ABC is written directly (music21's ABC writer is unreliable); MusicXML and MIDI go
through the music21 Score built in `to_music21`.
"""
from __future__ import annotations

import tempfile
from fractions import Fraction
from pathlib import Path

from ..schema import Level, Note
from ..theory import TICKS_PER_QUARTER, bar_ticks
from .to_music21 import level_to_score

def _abc_len(ticks: int, unit_ticks: int) -> str:
    f = Fraction(ticks, unit_ticks)
    if f == 1:
        return ""
    if f.denominator == 1:
        return str(f.numerator)
    if f.numerator == 1:
        return f"/{f.denominator}" if f.denominator != 2 else "/"
    return f"{f.numerator}/{f.denominator}"


Item = tuple[list[int] | None, int, bool, str | None]  # (pitches, ticks, tie, chord symbol)


def _bar_text(items: list[Item], level: Level, unit_ticks: int, written_shift: int) -> str:
    """Lay out items into ABC bars with a bar line after every full bar, a line break every
    four bars, and the pickup handled like the melody's."""
    bt = bar_ticks(level.meter)
    pos = (-level.pickup_ticks) % bt if level.pickup_ticks else 0
    body: list[str] = []
    bars = 0
    for pitches, dur, tie, symbol in items:
        tok = f'"{symbol}"' if symbol else ""
        if pitches is None:
            tok += "z" + _abc_len(dur, unit_ticks)
        else:
            names = [_abc_pitch_in_key(p + written_shift, level) for p in sorted(pitches)]
            tok += (names[0] if len(names) == 1 else "[" + "".join(names) + "]") + _abc_len(dur, unit_ticks)
            if tie:
                tok += "-"
        body.append(tok)
        pos += dur
        if pos >= bt:
            pos = 0
            bars += 1
            body.append("|")
            if bars % 4 == 0:
                body.append("\n")
    text = " ".join(body).replace(" \n ", "\n").replace("\n |", "\n|").strip()
    if not text.endswith("|"):
        text += " |"
    return text + "]"


def _melody_items(level: Level) -> list[Item]:
    chords = {c.start: c.symbol for c in level.chords}
    items: list[Item] = []
    t = 0
    for n in level.melody:
        items.append(([n.pitch] if n.pitch is not None else None, n.duration, n.tie, chords.get(t)))
        t += n.duration
    return items


def _accompaniment_items(level: Level) -> list[Item]:
    """Accompaniment events with rests in the gaps, split at bar lines with ties."""
    bt = bar_ticks(level.meter)
    total = sum(n.duration for n in level.melody)
    items: list[Item] = []
    cursor = 0

    def emit(pitches: list[int] | None, start: int, dur: int) -> None:
        pos = (start - level.pickup_ticks) % bt if level.pickup_ticks else start % bt
        while dur > 0:
            room = min(dur, bt - pos)
            dur -= room
            items.append((pitches, room, pitches is not None and dur > 0, None))
            pos = 0

    for ev in sorted(level.accompaniment, key=lambda e: e.start):
        if ev.start > cursor:
            emit(None, cursor, ev.start - cursor)
        if ev.start < cursor:
            continue
        dur = min(ev.duration, total - ev.start)
        if dur > 0:
            emit(ev.pitches, ev.start, dur)
            cursor = ev.start + dur
    if cursor < total:
        emit(None, cursor, total - cursor)
    return items


def to_abc(level: Level, *, title: str | None = None) -> str:
    """Two-voice ABC: the melody with chord symbols on top, the rendered accompaniment
    on a bass-clef staff below. Accidentals are written explicitly wherever the key
    signature does not already imply them."""
    num, den = level.meter.split("/")
    unit = Fraction(1, 8)
    unit_ticks = int(unit * 4 * TICKS_PER_QUARTER)
    key_name = level.tonic if level.mode == "major" else level.tonic + "m"
    clef = {"S": "treble", "A": "treble", "T": "treble-8", "B": "bass"}[level.voice]
    # an octave-transposing clef sounds an octave below what is written
    written_shift = 12 if clef.endswith("-8") else 0
    has_acc = bool(level.accompaniment)
    lines = [
        "X:1",
        f"T:{title or 'Mockingbird level ' + level.id}",
        f"M:{num}/{den}",
        f"L:{unit.numerator}/{unit.denominator}",
        f"Q:1/4={level.tempo_bpm}",
    ]
    if has_acc:
        lines.append("%%score 1 2")
    lines.append(f'V:1 clef={clef} name="Voice"')
    if has_acc:
        lines.append('V:2 clef=bass name="Piano"')
    lines.append(f"K:{key_name}")
    lines.append("V:1")
    lines.append(_bar_text(_melody_items(level), level, unit_ticks, written_shift))
    if has_acc:
        lines.append("V:2")
        lines.append(_bar_text(_accompaniment_items(level), level, unit_ticks, 0))
    return "\n".join(lines) + "\n"


def _abc_pitch_in_key(midi: int, level: Level) -> str:
    """Pitch with an explicit accidental where the key signature does not already imply
    it, and an explicit natural where it does but the note is unaltered."""
    from music21 import key as m21key, pitch as m21pitch

    tonic = level.tonic.replace("b", "-") if len(level.tonic) > 1 and level.tonic[1] == "b" else level.tonic
    k = m21key.Key(tonic if level.mode == "major" else tonic.lower(), level.mode)
    p = m21pitch.Pitch(midi=midi)
    # spell with the key's accidental direction
    if k.sharps < 0 and p.accidental is not None and p.accidental.alter > 0:
        p = p.getEnharmonic()
    elif k.sharps > 0 and p.accidental is not None and p.accidental.alter < 0:
        p = p.getEnharmonic()
    letter = p.step
    octave = p.octave
    sig_alter = {pp.step: pp.accidental.alter for pp in k.alteredPitches}
    alter = p.accidental.alter if p.accidental is not None else 0.0
    if alter == sig_alter.get(letter, 0.0):
        acc = ""
    elif alter == 0:
        acc = "="
    elif alter > 0:
        acc = "^" * int(alter)
    else:
        acc = "_" * int(-alter)
    if octave >= 5:
        name = letter.lower() + "'" * (octave - 5)
    else:
        name = letter + "," * (4 - octave)
    return acc + name


def to_musicxml(level: Level) -> str:
    score = level_to_score(level)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "level.musicxml"
        score.write("musicxml", fp=str(out))
        return out.read_text(encoding="utf-8")


def to_midi(level: Level) -> bytes:
    score = level_to_score(level)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "level.mid"
        score.write("midi", fp=str(out))
        return out.read_bytes()
