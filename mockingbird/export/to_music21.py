"""Build a music21 Score from a Level (melody plus optional accompaniment)."""
from __future__ import annotations

from fractions import Fraction

from music21 import chord as m21chord
from music21 import clef, harmony, instrument, key as m21key, meter, note as m21note, stream, tempo, tie

from ..schema import Level, Note
from ..theory import TICKS_PER_QUARTER, bar_ticks


def _ql(ticks: int) -> Fraction:
    return Fraction(ticks, TICKS_PER_QUARTER)


def _key(level: Level) -> m21key.Key:
    tonic = level.tonic.replace("b", "-") if len(level.tonic) > 1 and level.tonic[1] == "b" else level.tonic
    return m21key.Key(tonic if level.mode == "major" else tonic.lower(), level.mode)


CHORD_KINDS = {"maj": "major", "min": "minor", "dim": "diminished", "dom7": "dominant-seventh"}


def _chord_symbol(c) -> harmony.ChordSymbol:
    root = c.symbol.rstrip("m7di")  # strip quality suffix, keep the root spelling
    root = root[0] + root[1:].replace("b", "-")
    return harmony.ChordSymbol(root=root, kind=CHORD_KINDS[c.quality])


def _fill_measures(part: stream.Part, notes: list[Note], level: Level, *, velocity: int,
                   chord_symbols: bool = False) -> None:
    """Append notes to a part, creating measures and honouring the pickup bar."""
    bt = bar_ticks(level.meter)
    pos = (-level.pickup_ticks) % bt if level.pickup_ticks else 0
    m = stream.Measure(number=0 if level.pickup_ticks else 1)
    if level.pickup_ticks:
        m.paddingLeft = _ql(pos)
    measures = [m]
    chords = {c.start: c for c in level.chords} if chord_symbols else {}
    abs_tick = 0
    for n in notes:
        if abs_tick in chords:
            measures[-1].append(_chord_symbol(chords[abs_tick]))
        if n.pitch is None:
            el = m21note.Rest(quarterLength=_ql(n.duration))
        else:
            el = m21note.Note(n.pitch, quarterLength=_ql(n.duration))
            el.volume.velocity = velocity
            if n.tie:
                el.tie = tie.Tie("start")
        measures[-1].append(el)
        pos += n.duration
        abs_tick += n.duration
        if pos >= bt:
            pos = 0
            measures.append(stream.Measure(number=len(measures) + (0 if level.pickup_ticks else 1)))
    if not measures[-1].notesAndRests:
        measures.pop()
    for m in measures:
        part.append(m)
    # music21 represents a tie as start/stop pairs; mark the stop side too
    prev = None
    for el in part.recurse().notes:
        if prev is not None and prev.tie is not None and prev.tie.type == "start":
            el.tie = tie.Tie("stop") if el.tie is None else tie.Tie("continue")
        prev = el


def level_to_score(level: Level, *, include_accompaniment: bool = True) -> stream.Score:
    score = stream.Score()
    score.metadata = None
    ts = meter.TimeSignature(level.meter)
    k = _key(level)

    melody = stream.Part(id="melody")
    melody.partName = "Voice"
    melody.insert(0, instrument.Vocalist())
    melody.append(tempo.MetronomeMark(number=level.tempo_bpm))
    melody.append(k)
    melody.append(ts)
    melody.append(clef.TrebleClef() if level.voice in ("S", "A") else clef.Treble8vbClef()
                  if level.voice == "T" else clef.BassClef())
    _fill_measures(melody, level.melody, level, velocity=90, chord_symbols=True)
    score.insert(0, melody)

    if include_accompaniment and level.accompaniment:
        acc = stream.Part(id="accompaniment")
        acc.partName = "Piano"
        acc.insert(0, instrument.Piano())
        acc.append(k.__class__(k.tonicPitchNameWithCase, k.mode))
        acc.append(meter.TimeSignature(level.meter))
        acc.append(clef.BassClef())
        bt = bar_ticks(level.meter)
        pos = (-level.pickup_ticks) % bt if level.pickup_ticks else 0
        m = stream.Measure(number=0 if level.pickup_ticks else 1)
        if level.pickup_ticks:
            m.paddingLeft = _ql(pos)
        measures = [m]
        cursor = 0
        events = sorted(level.accompaniment, key=lambda e: e.start)
        for ev in events:
            # fill any gap with a rest, splitting at bar lines
            while cursor < ev.start:
                room = min(ev.start - cursor, bt - pos)
                measures[-1].append(m21note.Rest(quarterLength=_ql(room)))
                cursor += room
                pos += room
                if pos >= bt:
                    pos = 0
                    measures.append(stream.Measure(number=len(measures) + (0 if level.pickup_ticks else 1)))
            remaining = ev.duration
            first = True
            while remaining > 0:
                room = min(remaining, bt - pos)
                ch = m21chord.Chord(ev.pitches, quarterLength=_ql(room))
                ch.volume.velocity = 60
                if not first:
                    ch.tie = tie.Tie("stop")
                if remaining > room:
                    ch.tie = tie.Tie("start") if first else tie.Tie("continue")
                measures[-1].append(ch)
                remaining -= room
                cursor += room
                pos += room
                first = False
                if pos >= bt:
                    pos = 0
                    measures.append(stream.Measure(number=len(measures) + (0 if level.pickup_ticks else 1)))
        if not measures[-1].notesAndRests:
            measures.pop()
        for m in measures:
            acc.append(m)
        score.insert(0, acc)
    return score
