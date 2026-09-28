"""Phrase boundaries of Essen tunes from the raw ABC text.

The Essen ABC files write one phrase per line of the tune body; music21 drops the
line structure when parsing. This module tokenises each tune body just far enough to
know how many quarter notes each line covers, giving phrase-end offsets (in quarter
lengths from the tune start) that are matched against the parsed notes.
"""
from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path

NOTE_RE = re.compile(r"""
    (?P<acc>[\^_=]*)
    (?P<pitch>[A-Ga-gz])
    (?P<oct>[,']*)
    (?P<num>\d*)
    (?P<slash>/*)
    (?P<den>\d*)
""", re.VERBOSE)
SKIP_RE = re.compile(r"""\|+\]?|:\||\|:|\[\||\]|"[^"]*"|!\w+!|\(\d|\)|-|\s+|>|<|\{[^}]*\}|~|\.|[HLMNOPSTuv]""")


def _note_length(m: re.Match, unit: Fraction) -> Fraction:
    num = int(m.group("num")) if m.group("num") else 1
    slashes = m.group("slash")
    den = int(m.group("den")) if m.group("den") else (2 ** len(slashes) if slashes else 1)
    return unit * Fraction(num, den)


def phrase_ends_for_body(lines: list[str], unit: Fraction) -> list[Fraction]:
    """Cumulative quarter-length offsets at the end of every body line."""
    ends: list[Fraction] = []
    total = Fraction(0)
    for line in lines:
        i = 0
        line_len = Fraction(0)
        while i < len(line):
            m = NOTE_RE.match(line, i)
            if m and m.group("pitch"):
                line_len += _note_length(m, unit)
                i = m.end()
                continue
            m2 = SKIP_RE.match(line, i)
            if m2 and m2.end() > i:
                i = m2.end()
                continue
            i += 1  # unknown character: ignore
        if line_len > 0:
            total += line_len
            ends.append(total)
    return ends


def parse_file(path: Path) -> list[list[Fraction]]:
    """Per tune (in file order): phrase-end offsets in quarter lengths."""
    text = path.read_text(encoding="latin-1")
    tunes = re.split(r"(?m)^X:", text)[1:]
    out: list[list[Fraction]] = []
    for t in tunes:
        unit = Fraction(1, 8)
        body: list[str] = []
        in_header = True
        for line in t.splitlines()[1:]:  # first line is the tune number
            line = line.rstrip()
            if not line or line.startswith("%"):
                continue
            if in_header:
                hm = re.match(r"^([A-Za-z]):\s*(.*)$", line)
                if hm:
                    if hm.group(1) == "L" and "/" in hm.group(2):
                        a_, b_ = hm.group(2).split("/")
                        unit = Fraction(int(a_), int(b_))
                    if hm.group(1) == "K":
                        in_header = False
                    continue
                in_header = False  # tune without K: line
            body.append(line)
        # unit is in whole notes; convert to quarter lengths
        out.append(phrase_ends_for_body(body, unit * 4))
    return out
