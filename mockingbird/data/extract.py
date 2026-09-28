"""Turn a score into monophonic frame-space phrases.

Every source is first reduced to a list of `MeasureData` (one entry per notated
measure of the chosen vocal part, with concert-pitch events), which is then cut into
sections at meter or key-signature changes and at measures containing tuplets, with
bars that the source split around repeat signs merged back together. Old-notation
meters (x/2, x/1) are halved down to a /4 denominator and the note values scaled with
them. Each section is then keyed and transposed into the C-major / A-minor frame.

Key detection deliberately treats the final of the lowest voice (or of the melody for
monophonic sources) as the tonic and reads the mode off the third above it. Modal
pieces therefore land in the nearest major/minor frame with their characteristic
degrees as accidentals, which the difficulty score picks up as chromaticism.

`extract_file` handles music21-readable corpus files; `lieder.py` builds the same
MeasureData from MuseScore files via ms3.
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from music21 import bar as m21bar
from music21 import chord as m21chord
from music21 import converter, expressions, note as m21note, stream

from ..schema import Note, Phrase
from ..theory import (METERS, PC_NAMES, PITCH_MAX, PITCH_MIN, TICKS_PER_QUARTER,
                      VOICE_RANGES, frame_tonic_pc)

warnings.filterwarnings("ignore")

VOCAL_PART_RE = re.compile(r"soprano|sopran|cantus|superius|discantus|canto|^s(\b|\.)|voice|singstimme|"
                           r"gesang|mezzo|tenor|bariton|alt\b|vocal",
                           re.IGNORECASE)
INSTRUMENT_PART_RE = re.compile(r"piano|klavier|organ|orgel|continuo|violin|viola|cello|horn|oboe|"
                                r"flute|flauto|trumpet|tromba|bass(o)?$|alto|tenor|quinto|sextus",
                                re.IGNORECASE)

# Krumhansl-Kessler key profiles, used only as a sanity check on the final-note tonic.
KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


class Reject(Exception):
    """Raised with a short machine-readable reason when a section is unusable."""


@dataclass
class ScoreContext:
    """Whole-score evidence for key detection."""
    hist: np.ndarray  # duration-weighted pitch-class histogram over all parts
    final_pc: int | None  # final pitch class of the lowest part (None if monophonic)
    polyphonic: bool


@dataclass
class MeasureData:
    """One notated measure of the melody part, in concert pitch and quarter lengths.
    Events are (pitch, quarterLength, tie, phrase_end_after): the flag marks a phrase
    boundary right after the event (fermata, lyric punctuation, double bar, source
    phrase mark)."""
    numerator: int
    denominator: int
    keysig_sharps: int | None
    events: list[tuple[int | None, float, bool, bool]] = field(default_factory=list)

    @property
    def bar_q(self) -> float:
        return self.numerator * 4.0 / self.denominator

    @property
    def actual_q(self) -> float:
        return float(sum(e[1] for e in self.events))


@dataclass
class RawSection:
    notes: list[Note]  # concert pitch, ticks after meter scaling
    meter: str
    pickup_ticks: int
    keysig_sharps: int | None
    source: str
    is_ending: bool = False  # contains the last measure of the piece
    boundary_after: list[bool] = field(default_factory=list)  # per note, from source marks


def scale_meter(numerator: int, denominator: int) -> tuple[str, float]:
    """Halve x/2, x/1 meters down to a /4 denominator; return (meter, duration scale)."""
    scale = 1.0
    while denominator < 4:
        denominator *= 2
        scale *= 0.5
    return f"{numerator}/{denominator}", scale


def to_ticks(quarter_length: float) -> int:
    t = quarter_length * TICKS_PER_QUARTER
    if abs(t - round(t)) > 1e-6:
        raise Reject("offgrid_duration")
    t = int(round(t))
    if t % 3 != 0:
        raise Reject("tuplet")
    return t


def sections_from_measures(measures: list[MeasureData], source: str) -> list[RawSection]:
    """Cut measures into sections of constant meter and key. Measures with tuplets or
    other off-grid durations end the current section and are skipped."""
    if not measures:
        raise Reject("no_measures")
    sections: list[RawSection] = []
    cur: RawSection | None = None
    partial_q = 0.0  # duration so far of a bar the source split across several measures
    cur_sig: tuple[int, int, int | None] | None = None
    unsupported: set[str] = set()

    def flush() -> None:
        nonlocal cur, partial_q
        if cur is not None and len([n for n in cur.notes if n.pitch is not None]) > 0:
            sections.append(cur)
        cur = None
        partial_q = 0.0

    for idx, m in enumerate(measures):
        sig = (m.numerator, m.denominator, m.keysig_sharps)
        if sig != cur_sig:
            flush()
            cur_sig = sig
        meter, scale = scale_meter(m.numerator, m.denominator)
        if meter not in METERS:
            unsupported.add(meter)
            flush()
            continue
        try:
            kept = [(p, q, tie, b) for p, q, tie, b in m.events if to_ticks(q * scale) > 0]
            notes = [Note(pitch=p, duration=to_ticks(q * scale), tie=tie and p is not None)
                     for p, q, tie, _ in kept]
            flags = [b for _, _, _, b in kept]
        except Reject:
            flush()  # tuplet or off-grid bar: end the section here and skip the bar
            continue
        actual_q, bar_q = m.actual_q, m.bar_q
        if actual_q > bar_q + 1e-6:
            flush()
            continue
        if cur is None:
            cur = RawSection(notes=[], meter=meter, pickup_ticks=0, keysig_sharps=m.keysig_sharps,
                             source=source)
            if 0 < actual_q < bar_q - 1e-6:
                cur.pickup_ticks = to_ticks(actual_q * scale)
        elif partial_q > 0 or actual_q < bar_q - 1e-6:
            partial_q += actual_q
            if partial_q > bar_q + 1e-6:
                flush()
                continue
            if abs(partial_q - bar_q) <= 1e-6 or idx == len(measures) - 1:
                partial_q = 0.0  # bar completed, or a short final bar
        cur.notes.extend(notes)
        cur.boundary_after.extend(flags)
        if idx == len(measures) - 1:
            cur.is_ending = True
    flush()
    if not sections:
        if unsupported:
            raise Reject("meter_" + sorted(unsupported)[0].replace("/", "-"))
        raise Reject("empty")
    return sections


# ---------------------------------------------------------------- music21 sources

def parse(path: Path) -> list[tuple[str, stream.Score]]:
    """Parse a corpus file; an ABC opus yields many scores."""
    obj = converter.parse(str(path))
    if isinstance(obj, stream.Opus):
        out = []
        for i, sc in enumerate(obj.scores):
            title = (sc.metadata.title if sc.metadata and sc.metadata.title else "").strip()
            out.append((f"{i:04d}-{title[:40]}", sc))
        return out
    return [("", obj)]


def _pitched(el) -> list[int]:
    if isinstance(el, m21chord.Chord):
        return [p.midi for p in el.pitches]
    if isinstance(el, m21note.Note):
        return [el.pitch.midi]
    return []


def _mean_pitch(p: stream.Part) -> float:
    ps = [m for el in p.recurse().notes for m in _pitched(el)]
    return float(np.mean(ps)) if ps else -1.0


def score_context(score: stream.Score) -> ScoreContext:
    parts = list(score.parts)
    hist = np.zeros(12)
    for p in parts:
        for el in p.recurse().notes:
            for m in _pitched(el):
                hist[m % 12] += float(el.duration.quarterLength)
    final_pc = None
    if len(parts) > 1:
        lowest = min(parts, key=_mean_pitch)
        finals = [el for el in lowest.recurse().notes if _pitched(el)]
        if finals:
            final_pc = min(_pitched(finals[-1])) % 12
    return ScoreContext(hist=hist, final_pc=final_pc, polyphonic=len(parts) > 1)


def _lyric_share(p: stream.Part) -> float:
    notes = [n for n in p.recurse().notes]
    if not notes:
        return 0.0
    return sum(1 for n in notes if n.lyric) / len(notes)


def select_top_part(score: stream.Score) -> stream.Part:
    """The vocal part: highest part carrying lyrics, else by name, else the highest
    part that is not obviously an instrument."""
    parts = list(score.parts)
    if not parts:
        raise Reject("no_parts")
    if len(parts) == 1:
        return parts[0]
    with_lyrics = [p for p in parts if _lyric_share(p) >= 0.3]
    if with_lyrics:
        return max(with_lyrics, key=_mean_pitch)
    named = [p for p in parts if p.partName and VOCAL_PART_RE.search(p.partName)]
    if named:
        return named[0]
    candidates = [p for p in parts if not (p.partName and INSTRUMENT_PART_RE.search(p.partName))]
    return max(candidates or parts, key=_mean_pitch)


LYRIC_PHRASE_END = (".", ",", ";", ":", "!", "?")


def _phrase_end_after(e, is_last_in_measure: bool, m: stream.Measure) -> bool:
    """Source phrase marks: fermata, lyric ending in punctuation, or a double / final
    bar line closing this measure."""
    if isinstance(e, (m21chord.Chord, m21note.Note)):
        if any(isinstance(x, expressions.Fermata) for x in e.expressions):
            return True
        lyric = e.lyric
        if lyric and lyric.rstrip().endswith(LYRIC_PHRASE_END):
            return True
    if is_last_in_measure and m.rightBarline is not None and m.rightBarline.type in ("double", "light-light", "final", "light-heavy"):
        return True
    return False


def measures_from_part(part: stream.Part, phrase_offsets_q: list | None = None) -> list[MeasureData]:
    """`phrase_offsets_q`: optional phrase-end offsets in quarter lengths from the part
    start (used for Essen, whose phrases are only in the source text)."""
    try:
        expanded = part.expandRepeats()
        if expanded is not None and len(expanded.getElementsByClass("Measure")) > 0:
            part = expanded
    except Exception:  # noqa: BLE001 - malformed repeats are common
        pass
    offsets = set(phrase_offsets_q or [])
    out: list[MeasureData] = []
    ts = ks = None
    cursor = 0.0
    for m in part.getElementsByClass("Measure"):
        ts = m.timeSignature or ts
        ks = m.keySignature or ks
        if ts is None:
            raise Reject("no_meter")
        src = m.voices[0] if m.voices else m
        elements = [e for e in src.getElementsByClass(["Note", "Rest", "Chord"]) if not e.duration.isGrace]
        events = []
        for i, e in enumerate(elements):
            if isinstance(e, (m21chord.Chord, m21note.Note)):
                pitch = max(_pitched(e))
                tie = e.tie is not None and e.tie.type in ("start", "continue")
            else:
                pitch, tie = None, False
            ql = float(e.duration.quarterLength)
            cursor += ql
            boundary = _phrase_end_after(e, i == len(elements) - 1, m) or any(abs(cursor - float(o)) < 1e-6 for o in offsets)
            events.append((pitch, ql, tie, boundary))
        out.append(MeasureData(ts.numerator, ts.denominator, ks.sharps if ks is not None else None, events))
    return out


# ---------------------------------------------------------------- key and frame

def pc_histogram(notes: list[Note]) -> np.ndarray:
    h = np.zeros(12)
    for n in notes:
        if n.pitch is not None:
            h[n.pitch % 12] += n.duration
    return h


def ks_best(hist: np.ndarray) -> tuple[int, str] | None:
    best, best_c = None, -2.0
    if hist.sum() == 0:
        return None
    for tonic in range(12):
        for mode, prof in (("major", KS_MAJOR), ("minor", KS_MINOR)):
            c = np.corrcoef(hist, np.roll(prof, tonic))[0, 1]
            if np.isfinite(c) and c > best_c:
                best, best_c = (tonic, mode), float(c)
    return best


def determine_key(notes: list[Note], keysig_sharps: int | None, ctx: ScoreContext) -> tuple[int, str]:
    """Return (tonic_pc, mode); see the module docstring for the rule."""
    melody_hist = pc_histogram(notes)
    if melody_hist.sum() == 0:
        raise Reject("no_pitches")
    hist = ctx.hist if ctx.polyphonic and ctx.hist.sum() > 0 else melody_hist
    if ctx.final_pc is not None:
        final_pc = ctx.final_pc
    else:
        final_pc = [n.pitch for n in notes if n.pitch is not None][-1] % 12
    top3 = set(np.argsort(hist)[-3:].tolist())
    best = ks_best(hist)
    sig_ok = False
    if keysig_sharps is not None:
        sig_major = (keysig_sharps * 7) % 12
        sig_ok = final_pc in (sig_major, (sig_major + 9) % 12)
    if not (final_pc in top3 or (best and best[0] == final_pc) or sig_ok):
        raise Reject("ambiguous_key")
    third_major = hist[(final_pc + 4) % 12]
    third_minor = hist[(final_pc + 3) % 12]
    if third_major == 0 and third_minor == 0:
        mode = best[1] if best and best[0] == final_pc else "major"
    else:
        mode = "major" if third_major >= third_minor else "minor"
    return final_pc, mode


def range_bucket(concert_pitches: list[int]) -> str:
    lo, hi = min(concert_pitches), max(concert_pitches)
    best, best_score = "S", -1e9
    for voice, (vlo, vhi) in VOICE_RANGES.items():
        overlap = min(hi, vhi) - max(lo, vlo)
        centre_gap = abs((lo + hi) / 2 - (vlo + vhi) / 2)
        s = overlap * 10 - centre_gap
        if s > best_score:
            best, best_score = voice, s
    return best


MIN_PHRASE_TICKS = 2 * TICKS_PER_QUARTER  # boundaries closer than this are merged


def phrase_ends(notes: list[Note], boundary_after: list[bool], meter: str) -> list[int]:
    """Tick offsets of phrase ends: after flagged notes, before rests of at least a
    beat, and at the end. Ends less than MIN_PHRASE_TICKS apart are merged."""
    from ..theory import beat_ticks

    beat = beat_ticks(meter)
    ends: set[int] = set()
    pos = 0
    flags = boundary_after if len(boundary_after) == len(notes) else [False] * len(notes)
    for n, flag in zip(notes, flags):
        if n.pitch is None and n.duration >= beat and pos > 0:
            ends.add(pos)
        pos += n.duration
        if flag and (n.pitch is not None or True):
            ends.add(pos)
    total = pos
    ends.add(total)
    return clean_phrase_ends(notes, sorted(e for e in ends if e > 0))


def clean_phrase_ends(notes: list[Note], ends: list[int]) -> list[int]:
    """Canonical phrase ends: never right after a rest (moved back to the rest's start,
    so trailing rests belong to the next phrase's lead-in), at least MIN_PHRASE_TICKS
    and two pitched notes per phrase (shorter fragments merge into the next phrase),
    always ending at the total length."""
    total = sum(n.duration for n in notes)
    # tick -> the event ending there
    starts: dict[int, Note] = {}
    pos = 0
    for n in notes:
        starts[pos + n.duration] = n
        pos += n.duration
    moved: set[int] = set()
    for e in ends:
        t = e
        while t in starts and starts[t].pitch is None and t != total:
            t -= starts[t].duration  # step back over rests
        if t > 0:
            moved.add(t)
    moved.add(total)
    out: list[int] = []
    prev = 0
    pos = 0
    idx = 0
    for e in sorted(moved):
        pitched = 0
        while idx < len(notes) and pos < e:
            if notes[idx].pitch is not None:
                pitched += 1
            pos += notes[idx].duration
            idx += 1
        if e == total or (pitched >= 2 and e - prev >= MIN_PHRASE_TICKS):
            out.append(e)
            prev = e
        # else: too small, fold into the next phrase (pitched count carries no further,
        # which is fine: the next phrase is at least as long as this fragment plus itself)
    if len(out) >= 2 and out[-1] == total:
        # a tiny tail fragment merges into the previous phrase
        tail_pitched = sum(1 for n in _notes_between(notes, out[-2], total) if n.pitch is not None)
        if tail_pitched < 2 or total - out[-2] < MIN_PHRASE_TICKS:
            out.pop(-2)
    return out


def _notes_between(notes: list[Note], a: int, b: int) -> list[Note]:
    out, pos = [], 0
    for n in notes:
        if a <= pos < b:
            out.append(n)
        pos += n.duration
    return out


def to_frame(section: RawSection, style: str, ctx: ScoreContext) -> Phrase:
    """Transpose a concert-pitch section into the frame and build a Phrase."""
    tonic_pc, mode = determine_key(section.notes, section.keysig_sharps, ctx)
    offset = (tonic_pc - frame_tonic_pc(mode)) % 12
    concert = [n.pitch for n in section.notes if n.pitch is not None]
    if not concert:
        raise Reject("no_pitches")
    median = float(np.median([p - offset for p in concert]))
    shift = int(round((67 - median) / 12)) * 12
    notes = [Note(pitch=(n.pitch - offset + shift) if n.pitch is not None else None,
                  duration=n.duration, tie=n.tie) for n in section.notes]
    ps = [n.pitch for n in notes if n.pitch is not None]
    if min(ps) < PITCH_MIN or max(ps) > PITCH_MAX:
        raise Reject("range_outside_frame")
    return Phrase(mode=mode, meter=section.meter, style=style, notes=notes,
                  pickup_ticks=section.pickup_ticks, is_ending=section.is_ending,
                  phrase_ends=phrase_ends(notes, section.boundary_after, section.meter),
                  range_bucket=range_bucket(concert), source=section.source,
                  original_tonic=PC_NAMES[tonic_pc])


def phrases_from_measures(measures: list[MeasureData], ctx: ScoreContext, sid: str,
                          style: str) -> tuple[list[Phrase], list[tuple[str, str]]]:
    phrases: list[Phrase] = []
    rejects: list[tuple[str, str]] = []
    try:
        for k, section in enumerate(sections_from_measures(measures, sid)):
            section.source = f"{sid}#{k}" if k else sid
            try:
                phrases.append(to_frame(section, style, ctx))
            except Reject as r:
                rejects.append((section.source, str(r)))
    except Reject as r:
        rejects.append((sid, str(r)))
    return phrases, rejects


def extract_score(score: stream.Score, sid: str, style: str,
                  phrase_offsets_q: list | None = None) -> tuple[list[Phrase], list[tuple[str, str]]]:
    try:
        part = select_top_part(score)
        ctx = score_context(score)
        measures = measures_from_part(part, phrase_offsets_q)
    except Reject as r:
        return [], [(sid, str(r))]
    except Exception as e:  # noqa: BLE001 - keep the build running on odd files
        return [], [(sid, f"error:{type(e).__name__}")]
    return phrases_from_measures(measures, ctx, sid, style)


def extract_file(path: Path, source_id: str, style: str) -> tuple[list[Phrase], list[tuple[str, str]]]:
    """Extract every usable phrase from one music21-readable corpus file.
    Returns (phrases, rejects) where rejects are (source, reason) pairs."""
    try:
        scores = parse(path)
    except Exception as e:  # noqa: BLE001
        return [], [(source_id, f"parse_error:{type(e).__name__}")]
    phrases: list[Phrase] = []
    rejects: list[tuple[str, str]] = []
    essen_offsets = None
    if "essenFolksong" in str(path):
        from .essen_phrases import parse_file

        try:
            essen_offsets = parse_file(path)
        except Exception:  # noqa: BLE001 - phrase marks are optional
            essen_offsets = None
    for i, (sub, score) in enumerate(scores):
        sid = f"{source_id}/{sub}" if sub else source_id
        offsets = essen_offsets[i] if essen_offsets is not None and i < len(essen_offsets) else None
        p, r = extract_score(score, sid, style, offsets)
        phrases += p
        rejects += r
    return phrases, rejects
