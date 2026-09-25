"""Internal JSON format for melodies and levels. Renderer-agnostic by design."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .theory import Mode, Style, Voice


class Note(BaseModel):
    """A note or rest. `pitch` is MIDI (concert or frame, depending on container).
    `tie` means this note is tied into the following note."""

    pitch: int | None
    duration: int = Field(gt=0)
    tie: bool = False

    @property
    def is_rest(self) -> bool:
        return self.pitch is None


class Phrase(BaseModel):
    """A monophonic melody in the C-major / A-minor frame, as used for training.
    Bar lines are implicit: they follow from `pickup_ticks`, the meter and the
    cumulative durations. Notes never cross a bar line."""

    mode: Mode
    meter: str
    style: Style
    notes: list[Note]
    pickup_ticks: int = 0
    is_ending: bool = False  # the last bar is the last bar of the original piece
    phrase_ends: list[int] = []  # tick offsets where phrases end (the last one is the total length)
    cadences: list[str] = []  # cadence label per phrase end (see harmonize.cadence), same length
    range_bucket: Voice | None = None
    difficulty: int | None = None
    source: str = ""
    original_tonic: str | None = None

    def total_ticks(self) -> int:
        return sum(n.duration for n in self.notes)


class Chord(BaseModel):
    start: int
    duration: int
    root_pc: int  # concert pitch class in a Level; frame pitch class straight from the harmonizer
    quality: str  # maj | min | dim | dom7
    roman: str
    symbol: str  # concert-pitch chord symbol, e.g. "G7"


class AccompEvent(BaseModel):
    start: int
    duration: int
    pitches: list[int]


class Level(BaseModel):
    id: str
    tonic: str
    mode: Mode
    meter: str
    voice: Voice
    difficulty: int
    bars: int
    tempo_bpm: int = 100
    pickup_ticks: int = 0
    melody: list[Note]  # concert pitch
    phrase_ends: list[int] = []  # tick offsets of phrase ends
    cadences: list[str] = []  # cadence type chosen at each phrase end
    chords: list[Chord] = []
    accompaniment: list[AccompEvent] = []
    difficulty_score: float | None = None
    seed: int | None = None


class GenerateRequest(BaseModel):
    tonic: str = "C"
    mode: Mode = "major"
    meter: str = "4/4"
    voice: Voice = "S"
    difficulty: int = Field(default=2, ge=1, le=5)
    bars: int = Field(default=8, ge=1, le=32)
    style: Style | None = None
    accompaniment: str = "auto"  # auto | chorale | block | oompah | broken | none
    phrase_bars: int = Field(default=4, ge=1, le=32)
    tempo_bpm: int = 100
    seed: int | None = None
