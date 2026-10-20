"""Choir pieces from MusicXML: playback data for the practice page, and the score
itself (cleaned up) for rendering.

Pieces live as .mxl / .musicxml files in one directory and are identified by file
name. Repeats are not expanded: playback follows the score as written, which is what
the rendered page shows.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from .theory import TICKS_PER_QUARTER, VOICE_RANGES, Voice

SUFFIXES = (".mxl", ".musicxml", ".xml")
SOFT_HYPHEN = "­"
VOICE_NAMES = {"sopr": "S", "alt": "A", "ten": "T", "bas": "B"}


class PieceEvent(BaseModel):
    """A sounding note or chord; tied notes are merged."""
    start: int
    duration: int
    pitches: list[int]


class PiecePart(BaseModel):
    index: int
    name: str
    sung: bool
    voice: Voice | None  # the closest SATB voice, for sung parts
    events: list[PieceEvent]


class Measure(BaseModel):
    number: str
    start: int
    duration: int
    meter: str


class TempoChange(BaseModel):
    start: int
    bpm: float  # quarter notes per minute


class Verse(BaseModel):
    number: str
    incipit: str  # the first words, to tell the lyric lines apart


class Piece(BaseModel):
    id: str
    title: str
    composer: str | None
    parts: list[PiecePart]
    measures: list[Measure]
    tempos: list[TempoChange]
    verses: list[Verse]


class PieceSummary(BaseModel):
    id: str
    title: str
    composer: str | None


def piece_files(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        return {}
    return {p.stem: p for p in sorted(directory.iterdir()) if p.suffix.lower() in SUFFIXES}


def load_piece(path: Path) -> Piece:
    return _load(path, path.stat().st_mtime)


@lru_cache(maxsize=32)
def _load(path: Path, _mtime: float) -> Piece:
    from music21 import converter, tempo

    score = converter.parse(str(path))
    ticks = lambda ql: round(float(ql) * TICKS_PER_QUARTER)

    first = score.parts[0]
    measures = []
    meter = "4/4"
    for m in first.getElementsByClass("Measure"):
        if m.timeSignature is not None:
            meter = m.timeSignature.ratioString
        measures.append(Measure(number=str(m.measureNumberWithSuffix()), start=ticks(m.offset),
                                duration=ticks(m.duration.quarterLength), meter=meter))

    tempos: list[TempoChange] = []
    for mm in score.flatten().getElementsByClass(tempo.MetronomeMark):
        if mm.number is None:
            continue
        change = TempoChange(start=ticks(mm.offset), bpm=round(float(mm.getQuarterBPM()), 3))
        if tempos and tempos[-1].start == change.start:
            tempos[-1] = change
        else:
            tempos.append(change)
    if not tempos or tempos[0].start > 0:
        tempos.insert(0, TempoChange(start=0, bpm=tempos[0].bpm if tempos else 100.0))
    tempos = [t for i, t in enumerate(tempos) if i == 0 or t.bpm != tempos[i - 1].bpm]

    parts = []
    for i, part in enumerate(score.parts):
        notes = [n for n in part.flatten().notes if n.duration.quarterLength > 0]  # no grace notes
        sung = any(n.lyrics for n in notes)
        events = _events(notes, ticks)
        parts.append(PiecePart(index=i, name=part.partName or f"Part {i + 1}", sung=sung,
                               voice=_voice(part.partName or "", events) if sung else None, events=events))

    md = score.metadata
    # music21 falls back to the file name for the movement name
    named = md and (md.title or (md.movementName if md.movementName != path.name else None))
    return Piece(id=path.stem, title=named or path.stem.replace("_", " "),
                 composer=md.composer if md else None, parts=parts, measures=measures,
                 tempos=tempos, verses=_verses(score))


def _events(notes, ticks) -> list[PieceEvent]:
    events: list[PieceEvent] = []
    for n in notes:
        start, duration = ticks(n.offset), ticks(n.duration.quarterLength)
        pitches = sorted(p.midi for p in n.pitches)
        last = events[-1] if events else None
        tied_on = n.tie is not None and n.tie.type in ("stop", "continue")
        if tied_on and last and last.start + last.duration == start and last.pitches == pitches:
            last.duration += duration
        else:
            events.append(PieceEvent(start=start, duration=duration, pitches=pitches))
    return events


def _voice(name: str, events: list[PieceEvent]) -> Voice:
    lowered = name.lower()
    for prefix, voice in VOICE_NAMES.items():
        if lowered.startswith(prefix):
            return voice
    pitches = [p for e in events for p in e.pitches]
    mean = sum(pitches) / len(pitches) if pitches else 60
    return min(VOICE_RANGES, key=lambda v: abs(sum(VOICE_RANGES[v]) / 2 - mean))


def _verses(score) -> list[Verse]:
    """Lyric line numbers with the first few words of the first sung part."""
    for part in score.parts:
        words: dict[str, list[str]] = {}
        for n in part.flatten().notes:
            for lyric in n.lyrics:
                key = str(lyric.number)
                text = (lyric.text or "").replace(SOFT_HYPHEN, "").strip()
                if not text:
                    continue
                joined = words.setdefault(key, [])
                if joined and lyric.syllabic in ("middle", "end"):
                    joined[-1] += text
                else:
                    joined.append(text)
        if words:
            return [Verse(number=k, incipit=" ".join(v[:5])) for k, v in sorted(words.items())]
    return []


def musicxml(path: Path) -> str:
    """The score as uncompressed MusicXML, with Finale's soft-hyphen syllables removed:
    it exports some syllable joins as a lyric that starts with a syllable consisting of
    only a soft hyphen, followed by an elision."""
    if path.suffix.lower() == ".mxl":
        with zipfile.ZipFile(path) as z:
            container = ET.fromstring(z.read("META-INF/container.xml"))
            rootfile = next(e for e in container.iter() if e.tag.endswith("rootfile"))
            text = z.read(rootfile.get("full-path")).decode("utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text)  # ElementTree cannot fetch the DTD
    root = ET.fromstring(text)
    for lyric in root.iter("lyric"):
        children = list(lyric)
        texts = [i for i, c in enumerate(children) if c.tag == "text"]
        if len(texts) < 2 or (children[texts[0]].text or "").strip(SOFT_HYPHEN + " "):
            continue
        cut = texts[0] + 1
        while cut < len(children) and children[cut].tag == "elision":
            cut += 1
        start = texts[0] - 1 if texts[0] > 0 and children[texts[0] - 1].tag == "syllabic" else texts[0]
        for c in children[start:cut]:
            lyric.remove(c)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
