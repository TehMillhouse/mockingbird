"""Transcribe MIDI-rendered practice tracks into a MusicXML score without text.

    uv run --group pieces python tools/pieces/practice_audio.py [--src DIR] [--out DIR] [names...]

Each voice comes as its own mp3 (Cyberbass style: `<stem>sop.mp3`, `alt`, `ten`, `bas`,
or whatever the piece's entry names) whose right channel holds that voice alone and is
silent while it rests.
Because the audio is rendered from MIDI, pitches sit on equal temperament and onsets on
one fixed grid, so transcription is: pitch-track each right channel, cut it into notes
at pitch changes, re-attacks and silences, and snap the cut points to the grid.

What the audio cannot tell, the piece's entry below does: metre, where the first bar
line falls, key, and roughly how fast a quarter note is. Lyrics are not transcribed.
The grid has one tempo per piece; a render that changes tempo shows up as onsets
reported off the grid.

Lines starting with a name report each piece; anything indented below is a problem
to look at.
"""
from __future__ import annotations

import argparse
import subprocess
from xml.sax.saxutils import escape
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
from music21 import clef, instrument, key, meter, metadata, note, pitch, stream, tempo

ROOT = Path(__file__).resolve().parents[2]
SR = 11025
HOP = 128
FRAME = 1024
SILENCE_DB = 30.0  # frames this far below the voice's loudest are rests
MIN_NOTE = 0.06  # seconds; shorter fragments are tracker noise
GRID_SLACK = 0.03  # seconds an onset may miss the grid by before it is reported
ATTACK_DB = 1.0  # a rise this steep within a few frames starts a note
MONO_DB = 12.0  # right minus left this far below the right: both play the same mix
RELEASE_DB = 1.5  # a fall this steep over two frames is a release, not a note's decay


@dataclass(frozen=True)
class Voice:
    name: str
    abbreviation: str
    low: str  # the range the pitch tracker searches
    high: str
    clef: type[clef.Clef]


SOPRANO = Voice("Soprano", "S.", "B3", "C6", clef.TrebleClef)
ALTO = Voice("Alto", "A.", "E3", "F5", clef.TrebleClef)
TENOR = Voice("Tenor", "T.", "B2", "C5", clef.Treble8vbClef)
BASS = Voice("Bass", "B.", "C2", "F4", clef.BassClef)
SATB = (("sop", SOPRANO), ("alt", ALTO), ("ten", TENOR), ("bas", BASS))


def numbered(n: int, suffixes: tuple[str, ...]) -> tuple[tuple[str, Voice], ...]:
    """The SATB voices of choir (or quartet) `n` of several, e.g. Soprano II, with their
    mp3 name suffixes."""
    roman = "I" * n
    return tuple((suffix, Voice(f"{v.name} {roman}", f"{v.abbreviation} {roman}", v.low, v.high, v.clef))
                 for suffix, (_, v) in zip(suffixes, SATB))


@dataclass
class Piece:
    name: str  # output file name without extension
    stem: str  # mp3 names without the voice suffix
    title: str
    composer: str
    time_signature: str
    key: str  # music21 key name, lower case for minor
    bpm: float  # quarter notes, only roughly: the grid is fitted to the audio
    # quarter notes from the first bar line to the first sung note; with a pickup, from
    # where the first bar would start if it were a full one
    first_note_offset: float = 0.0
    # quarter notes in the first bar if it is a pickup (numbered 0, as in print), else 0
    pickup: float = 0.0
    # for tracks that put other singers on the right channel too: how many dB louder
    # than the left the right channel must be where the voice sings
    lead_db: float | None = None
    # (mp3 name suffix, voice), top to bottom
    voices: tuple[tuple[str, Voice], ...] = SATB
    # what the score was made from, kept in the MusicXML's <source>
    source: str = "Transcribed from Cyberbass practice tracks; not to be passed on"


MENDELSSOHN = "Felix Mendelssohn Bartholdy"
CYBERBASS = "Transcribed from Cyberbass practice tracks (cyberbass.org); not to be passed on"
# where metre, key and the first bar line come from
SCHIRMER = ("Metre, key and bar lines from the chorus score on IMSLP, #55354: G. Schirmer, New York, n.d. [1892], "
            "plate 36349, scanned by Carolus; Public Domain there")
ELIAS = f"{CYBERBASS}. {SCHIRMER}"
# for numbers that open with a recitative the Cyberbass tracks leave out
ELIAS_CHORUS = f"{ELIAS}. Bar 1 is the first bar of the chorus section, after the recitative"
WOMEN = Voice("Women", "W.", "E3", "C6", clef.TrebleClef)
MEN = Voice("Men", "M.", "C2", "C5", clef.BassClef)
DOUBLE_QUARTET = tuple(v for pair in zip(numbered(1, ("sop1", "alt1", "ten1", "BAS1")),
                                         numbered(2, ("SOP2", "ALT2", "TEN2", "BAS2")))
                       for v in pair)

PIECES = [
    Piece("elias-01", "MENDELSSOHN_ELIJAH01_", "Elias No. 1: Hilf, Herr!", MENDELSSOHN,
          "4/4", "d", 75, source=f"{CYBERBASS}. Checked against CPDL #04415 (James R. Jennings)"),
    Piece("elias-02", "Mendelssohn_Elijah02", "Elias No. 2: Herr, höre unser Gebet!", MENDELSSOHN,
          "2/4", "a", 50, first_note_offset=1, pickup=1,
          voices=(("wom", WOMEN), ("men", MEN)), lead_db=5, source=ELIAS),
    Piece("elias-05", "Mendelssohn_Elijah05", "Elias No. 5: Aber der Herr sieht es nicht", MENDELSSOHN,
          "2/2", "c", 190, first_note_offset=2, source=ELIAS),
    Piece("elias-07", "Mendelssohn_Elijah07", "Elias No. 7: Denn er hat seinen Engeln befohlen",
          MENDELSSOHN, "2/2", "G", 126, first_note_offset=6, voices=DOUBLE_QUARTET, source=ELIAS),
    Piece("elias-09", "Mendelssohn_Elijah09", "Elias No. 9: Wohl dem, der den Herrn fürchtet",
          MENDELSSOHN, "4/4", "G", 96, first_note_offset=10, source=ELIAS),
    Piece("elias-10", "Mendelssohn_Elijah10", "Elias No. 10: Du bist's, der Israel verwirrt",
          MENDELSSOHN, "4/4", "c", 144, source=ELIAS_CHORUS),
    Piece("elias-12", "Mendelssohn_Elijah12", "Elias No. 12: Baal, erhöre uns! Wache auf!",
          MENDELSSOHN, "4/4", "f#", 160, first_note_offset=8, source=ELIAS_CHORUS),
    Piece("elias-13", "Mendelssohn_Elijah13", "Elias No. 13: Baal! Gib uns Antwort!",
          MENDELSSOHN, "6/8", "f#", 189, source=ELIAS_CHORUS),
    Piece("elias-15", "Mendelssohn_Elijah15", "Elias No. 15: Wirf dein Anliegen auf den Herrn",
          MENDELSSOHN, "4/4", "E-", 52, first_note_offset=2, pickup=2, source=ELIAS),
    Piece("elias-16", "Mendelssohn_Elijah16", "Elias No. 16: Das Feuer fiel herab",
          MENDELSSOHN, "4/4", "e", 152, first_note_offset=5.75, source=ELIAS_CHORUS),
    Piece("elias-20", "Mendelssohn_Elijah20", "Elias No. 20: Dank sei dir, Gott",
          MENDELSSOHN, "3/4", "E-", 126, first_note_offset=3, source=ELIAS),
]


@dataclass
class Segment:
    start: float  # seconds
    end: float
    midi: int


def channels(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """The left and right channel."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "2", "-ar", str(SR),
         "-f", "f32le", "-acodec", "pcm_f32le", "-"],
        check=True, capture_output=True).stdout
    both = np.frombuffer(raw, np.float32).reshape(-1, 2)
    return both[:, 0].copy(), both[:, 1].copy()


def segments(left: np.ndarray, y: np.ndarray, voice: Voice,
             lead_db: float | None = None) -> list[Segment]:
    """Notes of the right channel `y` as (start, end, pitch), cut at pitch changes,
    re-attacks and silences. Some tracks play the full mix on both channels while their
    voice rests; where the channels are (nearly) the same, the voice counts as silent.
    With `lead_db`, a note only counts where the right channel is, over the note, that
    many dB louder than the left."""
    db = loudness(y)
    side = loudness(y - left, ref=1.0) - loudness(y, ref=1.0)
    width = int(0.3 * SR / HOP) | 1  # frames; level differences flicker within a note
    mono = smoothed(side, width) < -MONO_DB
    lead = loudness(y, ref=1.0) - loudness(left, ref=1.0)
    f0, voiced, _ = librosa.pyin(
        y, sr=SR, frame_length=FRAME, hop_length=HOP,
        fmin=librosa.note_to_hz(voice.low), fmax=librosa.note_to_hz(voice.high))
    n = min(len(db), len(f0))
    active = (db[:n] > -SILENCE_DB) & voiced[:n] & ~mono[:n]
    midi = np.where(active, librosa.hz_to_midi(np.nan_to_num(f0[:n], nan=1.0)), np.nan)
    # frame labels: rounded pitch, -1 for silence; cut wherever the label changes, and
    # at attacks away from such changes (re-attacks of the same pitch)
    label = np.where(active, np.round(np.nan_to_num(midi, nan=0)), -1).astype(int)
    label = _smooth(label, 3)
    changes = [i for i in range(1, n) if label[i] != label[i - 1]]
    near = int(MIN_NOTE * 1.5 * SR / HOP)
    reattacks = [i for i in attacks(db) if i < n and label[i] >= 0
                 and all(abs(i - c) > near for c in changes)]
    cuts = sorted({0, n, *changes, *reattacks})
    out: list[Segment] = []
    for a, b, following in zip(cuts, cuts[1:], cuts[2:] + [n]):
        if label[a] < 0:
            continue
        end = b
        if b < n and label[b] < 0:
            # the pitch tracker gives up on a quiet tail before the sound does; follow the
            # sound to silence, which is the bottom of the release, then back to its top
            while end < following and db[end] > -SILENCE_DB:
                end += 1
            while end - 1 > a + 1 and db[end - 1] - db[end - 3] < -RELEASE_DB:
                end -= 1
        if lead_db is not None and np.median(lead[a:b]) < lead_db:
            continue
        if (end - a) * HOP / SR >= MIN_NOTE:
            out.append(Segment(a * HOP / SR, end * HOP / SR,
                               int(round(np.nanmedian(midi[a:b])))))
    return out


def smoothed(x: np.ndarray, width: int) -> np.ndarray:
    """Running median over `width` frames (odd)."""
    padded = np.pad(x, width // 2, mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(padded, width), axis=1)


def loudness(y: np.ndarray, ref: float | None = None) -> np.ndarray:
    """dB relative to `ref` (by default the loudest frame), over a window short enough to
    see the dip before a quick re-attack and the drop at a release."""
    rms = librosa.feature.rms(y=y, frame_length=FRAME // 4, hop_length=HOP)[0]
    return librosa.amplitude_to_db(rms, ref=np.max if ref is None else ref)


def attacks(db: np.ndarray) -> list[int]:
    """Frames where loudness jumps: rendered notes decay steadily, so a rise is a new note."""
    lag = 3
    rise = np.zeros_like(db)
    rise[lag:] = db[lag:] - db[:-lag]
    wait = int(MIN_NOTE * SR / HOP)
    peaks = librosa.util.peak_pick(rise, pre_max=wait, post_max=wait, pre_avg=1,
                                   post_avg=1, delta=0.0, wait=wait)
    return [int(i) - lag + 1 for i in peaks if rise[i] > ATTACK_DB]


def _smooth(label: np.ndarray, width: int) -> np.ndarray:
    """Absorb runs shorter than `width` frames into the run before them."""
    out = label.copy()
    i = 0
    while i < len(out):
        j = i
        while j < len(out) and out[j] == out[i]:
            j += 1
        if j - i < width and i > 0:
            out[i:j] = out[i - 1]
        i = j
    return out


def fit_grid(times: np.ndarray, quarter_guess: float) -> tuple[float, float]:
    """Sixteenth-note period and phase that put the onsets closest to grid points."""
    best = (0.0, quarter_guess / 4, 0.0)
    for q in np.linspace(quarter_guess * 0.9, quarter_guess * 1.1, 4001):
        u = q / 4
        z = np.exp(2j * np.pi * times / u).mean()
        if abs(z) > best[0]:
            best = (abs(z), u, (np.angle(z) / (2 * np.pi)) * u % u)
    return best[1], best[2]


FIFTHS = {"F": -1, "C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5}


def _fifths(p: pitch.Pitch) -> int:
    return FIFTHS[p.step] + 7 * int(p.alter)


def written_length(sounding: float, room: int | None) -> int:
    """Sixteenths a note is written for, from how many it sounds and how many there are
    until the next note (None: no next note).

    A note that sounds into the next one, give or take a sixteenth, lasts until it. The
    renders release other notes early, by a quarter of their length up to a sixteenth
    (a quarter sounds for about 3.3 sixteenths, a half for 6.5); notes longer than a
    quarter are written in eighths."""
    if room is not None and room - round(sounding) <= 1:
        return room
    est = sounding + min(1.0, sounding / 4)
    w = max(1, round(est) if est < 4 else 2 * round(est / 2))
    return w if room is None else min(w, room)


@dataclass
class Placed:
    start: int  # sixteenths from the first bar line
    end: int
    midi: int


def spell(voices: list[list[Placed]], k: key.Key) -> list[list[pitch.Pitch]]:
    """Diatonic notes (and a minor key's raised sixth and seventh) as the key has them.
    Of the others, a note with only one spelling in the key's neighbourhood on the line
    of fifths takes that one (G#, not Ab, in D minor). Otherwise a note that next rises
    a semitone is sharp, and the rest take the spelling closer on the line of fifths to
    the key's notes the other voices sing meanwhile (D# under a B major chord, Eb under
    a C minor one), or to the key itself when the voice sings alone."""
    names = {p.pitchClass: p.name for p in k.getScale().getPitches()}
    if k.mode == "minor":
        for degree in (6, 7):
            p = k.pitchFromDegree(degree).transpose(1)
            names.setdefault(p.pitchClass, p.name)
    # one step beyond the diatonic span each way; in minor up to the leading tones of
    # the dominant and of its dominant (G# and D# in D minor)
    low = k.sharps - 2
    high = k.sharps + (10 if k.mode == "minor" else 6)
    near = lambda q: low <= _fifths(q) <= high
    diatonic = [[_fifths(pitch.Pitch(names[n.midi % 12])) if n.midi % 12 in names else None
                 for n in notes] for notes in voices]

    out = []
    for vi, notes in enumerate(voices):
        spelled = []
        for i, n in enumerate(notes):
            p = pitch.Pitch(midi=n.midi)
            if n.midi % 12 in names:
                p.name = names[n.midi % 12]
                spelled.append(p)
                continue
            sharp = p if p.alter > 0 else p.getEnharmonic()
            flat = sharp.getEnharmonic()
            around = [f for vj, other in enumerate(voices) if vj != vi
                      for o, f in zip(other, diatonic[vj])
                      if f is not None and o.start < n.end and o.end > n.start]
            later = [o.midi for o in notes[i + 1:] if o.midi != n.midi][:1]
            if near(sharp) != near(flat):
                p = sharp if near(sharp) else flat
            elif later and later[0] == n.midi + 1:
                p = sharp
            else:
                centre = sum(around) / len(around) if around else (low + high) / 2
                p = sharp if abs(_fifths(sharp) - centre) <= abs(_fifths(flat) - centre) else flat
            spelled.append(p)
        out.append(spelled)
    return out


def build(piece: Piece, src: Path) -> tuple[stream.Score, list[str]]:
    problems: list[str] = []
    found = {suffix: segments(*channels(src / f"{piece.stem}{suffix}.mp3"), v, piece.lead_db)
             for suffix, v in piece.voices}
    starts = np.array([s.start for segs in found.values() for s in segs])
    u, phase = fit_grid(starts, 60 / piece.bpm)
    k = key.Key(piece.key)

    def ticks(t: float) -> int:
        return int(round((t - phase) / u))

    bar_start = min(ticks(s) for s in starts) - round(piece.first_note_offset * 4)

    placed: list[list[Placed]] = []
    for suffix, v in piece.voices:
        notes = []
        segs = found[suffix]
        for s, nxt in zip(segs, segs[1:] + [None]):
            off = (s.start - phase) / u - round((s.start - phase) / u)
            if abs(off) > 0.3 and abs(off) * u > GRID_SLACK:
                problems.append(f"{v.name} {s.start:.2f}s: onset {off:+.2f} sixteenths off the grid")
            a = ticks(s.start) - bar_start
            room = None if nxt is None else ticks(nxt.start) - bar_start - a
            b = a + written_length((s.end - s.start) / u, room)
            if b <= a:
                problems.append(f"{v.name} {s.start:.2f}s: {s.midi} shorter than a sixteenth, dropped")
                continue
            notes.append(Placed(a, b, s.midi))
        placed.append(notes)

    score = stream.Score()
    score.metadata = metadata.Metadata(title=piece.title, composer=piece.composer)
    for (_, v), notes, pitches in zip(piece.voices, placed, spell(placed, k)):
        part = stream.Part()
        part.partName = v.name
        inst = instrument.Vocalist()
        inst.partName = v.name
        inst.instrumentAbbreviation = part.partAbbreviation = v.abbreviation
        part.insert(0, inst)
        part.insert(0, v.clef())
        part.insert(0, key.KeySignature(k.sharps))
        part.insert(0, meter.TimeSignature(piece.time_signature))
        part.insert(0, tempo.MetronomeMark(number=round(60 / (4 * u))))
        cursor = 0
        for n, p in zip(notes, pitches):
            if n.start > cursor:
                part.insert(cursor / 4, note.Rest(quarterLength=(n.start - cursor) / 4))
            part.insert(n.start / 4, note.Note(p, quarterLength=(n.end - n.start) / 4))
            cursor = n.end
        score.insert(0, part)
    score = score.makeNotation()
    if piece.pickup:
        bar = meter.TimeSignature(piece.time_signature).barDuration.quarterLength
        as_pickup(score, bar - piece.pickup)
    return score, problems


def as_pickup(score: stream.Score, missing: float) -> None:
    """Shorten every part's first bar by `missing` quarter notes of leading rest, making
    it a pickup, and number the bars from 0."""
    for part in score.parts:
        measures = list(part.getElementsByClass(stream.Measure))
        first = measures[0]
        for r in list(first.notesAndRests):
            end = r.offset + r.quarterLength
            if r.offset >= missing:
                first.setElementOffset(r, r.offset - missing)
            elif not r.isRest:
                raise ValueError(f"{part.partName}: a note starts before the pickup")
            elif end <= missing:
                first.remove(r)
            else:
                r.quarterLength = end - missing
                first.setElementOffset(r, 0)
        first.paddingLeft = missing
        for m in measures[1:]:
            part.setElementOffset(m, m.offset - missing)
        for m in measures:
            m.number -= 1


def add_source(path: Path, text: str) -> None:
    """Note in the MusicXML what the score was made from (music21 cannot write it)."""
    xml = path.read_text(encoding="utf-8")
    xml = xml.replace("</encoding>", f"</encoding>\n    <source>{escape(text)}</source>", 1)
    path.write_text(xml, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", type=Path, default=ROOT / "custom_pieces" / "sources")
    ap.add_argument("--out", type=Path, default=ROOT / "custom_pieces")
    ap.add_argument("names", nargs="*")
    args = ap.parse_args()
    for piece in PIECES:
        if args.names and piece.name not in args.names:
            continue
        score, problems = build(piece, args.src)
        path = args.out / f"{piece.name}.musicxml"
        score.write("musicxml", fp=path)
        add_source(path, piece.source)
        print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
        for p in problems:
            print("   ", p)


if __name__ == "__main__":
    main()
