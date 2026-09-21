"""Chord alphabet per mode, expressed in the C-major / A-minor frame."""
from __future__ import annotations

from dataclasses import dataclass

from ..theory import PC_NAMES


@dataclass(frozen=True)
class ChordType:
    roman: str
    root_pc: int  # in the frame
    quality: str  # maj | min | dim | dom7
    is_dominant: bool = False
    is_secondary: bool = False

    @property
    def pcs(self) -> frozenset[int]:
        r = self.root_pc
        if self.quality == "maj":
            return frozenset({r, (r + 4) % 12, (r + 7) % 12})
        if self.quality == "min":
            return frozenset({r, (r + 3) % 12, (r + 7) % 12})
        if self.quality == "dim":
            return frozenset({r, (r + 3) % 12, (r + 6) % 12})
        if self.quality == "dom7":
            return frozenset({r, (r + 4) % 12, (r + 7) % 12, (r + 10) % 12})
        raise ValueError(self.quality)

    def symbol(self, offset: int) -> str:
        """Concert-pitch chord symbol after transposing the frame up by `offset`."""
        root = PC_NAMES[(self.root_pc + offset) % 12]
        if self.quality == "maj":
            return root
        if self.quality == "min":
            return root + "m"
        if self.quality == "dim":
            return root + "dim"
        return root + "7"


MAJOR: tuple[ChordType, ...] = (
    ChordType("I", 0, "maj"),
    ChordType("ii", 2, "min"),
    ChordType("iii", 4, "min"),
    ChordType("IV", 5, "maj"),
    ChordType("V", 7, "maj", is_dominant=True),
    ChordType("V7", 7, "dom7", is_dominant=True),
    ChordType("vi", 9, "min"),
    ChordType("vii°", 11, "dim"),
    ChordType("V/V", 2, "maj", is_secondary=True),
    ChordType("V/ii", 9, "maj", is_secondary=True),
)

# A-minor frame: i = A, V = E major (harmonic minor dominant)
MINOR: tuple[ChordType, ...] = (
    ChordType("i", 9, "min"),
    ChordType("ii°", 11, "dim"),
    ChordType("III", 0, "maj"),
    ChordType("iv", 2, "min"),
    ChordType("V", 4, "maj", is_dominant=True),
    ChordType("V7", 4, "dom7", is_dominant=True),
    ChordType("VI", 5, "maj"),
    ChordType("VII", 7, "maj"),
    ChordType("vii°", 8, "dim"),
    ChordType("V/iv", 9, "maj", is_secondary=True),
    ChordType("V/V", 11, "maj", is_secondary=True),
)


def alphabet(mode: str) -> tuple[ChordType, ...]:
    return MAJOR if mode == "major" else MINOR
