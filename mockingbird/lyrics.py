"""Sung text on the parts of a music21 score.

Two jobs, both driven by a libretto written with hyphens at syllable breaks
("Jauch-zet, froh-lo-cket!"):

- underlay: put a text on a part's notes at given onsets, for scores without text;
- repair: fix a transcription's text, where word joins (begin/middle/end) are missing
  or a whole word sits under the first note of a melisma.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from music21 import note, stream

ELISION = "‿"  # undertie: two syllables sung on one note ("dich‿dein")
_CLOSING = re.compile(r"[,.;:!?]$")


def syllables(text: str) -> list[tuple[str, str]]:
    """(syllable, syllabic) pairs from words hyphenated at syllable breaks."""
    out = []
    for word in text.split():
        parts = word.split("-")
        for i, part in enumerate(parts):
            out.append((part, _syllabic(i, len(parts))))
    return out


def _syllabic(i: int, n: int) -> str:
    return "single" if n == 1 else "begin" if i == 0 else "end" if i == n - 1 else "middle"


def normalize(text: str) -> str:
    """Letters only, lower case, ß as ss: for comparing sung text with a libretto."""
    return re.sub(r"[^a-zäöü]", "", text.lower().replace("ß", "ss"))


@dataclass
class Libretto:
    """The words of a hyphenated text, by normalized spelling."""
    words: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def parse(cls, hyphenated: str) -> Libretto:
        words = {}
        for w in hyphenated.split():
            sylls = re.sub(r"[^\w-]", "", w).split("-")
            if key := normalize("".join(sylls)):
                words[key] = sylls
        return cls(words)

    def is_word(self, text: str) -> bool:
        return normalize(text) in self.words or (
            ELISION in text and all(normalize(t) in self.words for t in text.split(ELISION)))

    def starts_word(self, text: str) -> bool:
        key = normalize(text)
        return any(w.startswith(key) for w in self.words)

    def split(self, text: str) -> list[str] | None:
        """The syllables of a run of two or more consecutive syllables of one word
        ("lo-cket" from "locket"), or None if the text is not one."""
        key = normalize(text)
        for sylls in self.words.values():
            for i in range(len(sylls)):
                for j in range(i + 2, len(sylls) + 1):
                    if normalize("".join(sylls[i:j])) == key:
                        return sylls[i:j]
        return None


def word_spans(texts: list[str], libretto: Libretto) -> tuple[list[str], list[str]]:
    """Syllabic for a part's syllables in order, and the words the libretto lacks.

    From each syllable, the run is extended while the joined text still starts a
    libretto word and no syllable closes with punctuation; of the extensions the
    longest that is a whole word is taken ("Höch" + "ste", but "die" before "Ta-ge")."""
    syllabic: list[str] = []
    unknown: list[str] = []
    i = 0
    while i < len(texts):
        j, end = i, i if libretto.is_word(texts[i]) else None
        while (j + 1 < len(texts) and not _CLOSING.search(texts[j])
               and libretto.starts_word("".join(texts[i:j + 2]))):
            j += 1
            if libretto.is_word("".join(texts[i:j + 1])):
                end = j
        if end is None:
            end = j
            unknown.append(" ".join(texts[i:end + 1]))
        n = end - i + 1
        syllabic += [_syllabic(k, n) for k in range(n)]
        i = end + 1
    return syllabic, unknown


def sung_lyrics(part: stream.Part) -> list[note.Lyric]:
    """The first lyric of every note that has text, after dropping empty lyrics
    (melisma placeholders) and joining text split over several elements."""
    out = []
    for n in part.recurse().notes:
        kept = []
        for lyric in n.lyrics:
            text = "".join((lyric.text or "").split())
            if normalize(text):
                lyric.text = text
                kept.append(lyric)
        n.lyrics = kept[:1]
        out += n.lyrics
    return out


def join_words(part: stream.Part, libretto: Libretto) -> list[str]:
    """Set each lyric's syllabic from the libretto; returns the words it lacks."""
    lyrics = sung_lyrics(part)
    syllabic, unknown = word_spans([ly.text for ly in lyrics], libretto)
    for lyric, kind in zip(lyrics, syllabic):
        lyric.syllabic = kind
    return unknown


def spread_melisma_words(part: stream.Part, libretto: Libretto) -> int:
    """Where several syllables of a word sit under the first note of a melisma, its
    later syllables move to the last notes of the melisma (before the next syllable or
    rest). Returns how many were spread."""
    events = [x for x in part.recurse().notesAndRests if x.isRest or not _tied_over(x)]
    count = 0
    for i, n in enumerate(events):
        if n.isRest or len(n.lyrics) != 1:
            continue
        lyric = n.lyrics[0]
        text = "".join((lyric.text or "").split())
        sylls = libretto.split(text)
        if not sylls:
            continue
        free = []
        for x in events[i + 1:]:
            if x.isRest or any(normalize(ly.text or "") for ly in x.lyrics):
                break
            free.append(x)
        if len(free) < len(sylls) - 1:
            continue
        punctuation = text[len(text.rstrip(",.;:!?")):]
        targets = [n] + free[len(free) - (len(sylls) - 1):]
        for k, (x, syl) in enumerate(zip(targets, sylls)):
            if k == 0:
                syl = text[:len(syl)]  # the source's capitalisation
            if k == len(sylls) - 1:
                syl += punctuation
            new = lyric if k == 0 else copy.deepcopy(lyric)
            new.text = syl
            x.lyrics = [new]
        count += 1
    return count


def _tied_over(n: note.GeneralNote) -> bool:
    return n.tie is not None and n.tie.type in ("stop", "continue")


def onsets(part: stream.Part, tied_over: bool = False) -> dict[float, note.NotRest]:
    """Notes by offset in the part; tied-over notes only with tied_over=True."""
    return {float(n.getOffsetInHierarchy(part)): n for n in part.recurse().notes
            if tied_over or not _tied_over(n)}


def underlay(part: stream.Part, positions: list[float], text: list[tuple[str, str]]) -> list[str]:
    """Put syllable i on the part's note starting in [positions[i], positions[i + 1]),
    else on a syncopated note started since the previous position. A tied-over note
    may take a syllable: the singer changes the vowel on the held note, and the tie
    keeps it sounding once. Replaces the part's text; returns problems."""
    for n in part.recurse().notes:
        n.lyrics = []
    starts = sorted(onsets(part, tied_over=True).items())
    used: set[int] = set()
    bounds = positions + [float("inf")]
    problems = []
    for i, (syl, kind) in enumerate(text[:len(positions)]):
        lo, hi = positions[i], bounds[i + 1]
        prev = positions[i - 1] if i else -1.0
        here = [n for o, n in starts if lo <= o < hi and id(n) not in used]
        early = [n for o, n in starts if prev < o < lo and id(n) not in used and not _tied_over(n)]
        target = here[0] if here else early[-1] if early else None
        if target is None:
            problems.append(f"{part.partName}: no note for '{syl}' at {lo}")
            continue
        used.add(id(target))
        lyric = note.Lyric(text=syl, number=1)
        lyric.syllabic = kind
        target.lyrics = [lyric]
    return problems
