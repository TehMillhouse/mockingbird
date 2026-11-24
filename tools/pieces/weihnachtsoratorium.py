"""Build the Weihnachtsoratorium (BWV 248, parts I-III) practice pieces.

    python tools/pieces/weihnachtsoratorium.py [--cpdl DIR] [--out DIR] [numbers...]

Chorales come from the music21 corpus, which has the notes but the hymn's text (or
none) instead of the oratorio's: the libretto below is laid under every voice.
Choruses come from CPDL editions (the .mxl files in --cpdl): their text is repaired
against the libretto, and a da capo is written out.

Lines starting with a number report each piece; anything indented below is a
problem to look at.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
from pathlib import Path

from music21 import converter, corpus, expressions, metadata, spanner, stream, tempo

from mockingbird import lyrics

ROOT = Path(__file__).resolve().parents[2]
COMPOSER = "Johann Sebastian Bach"


@dataclass
class Chorale:
    no: int
    corpus_id: str
    title: str
    bpm: float  # quarter notes
    # where the soprano's syllables start: "corpus" where the corpus text has the same
    # metre and is placed right, else "beats" (one per quarter-beat onset)
    positions: str
    text: str
    # the last soprano note repeats the one before on the same syllable
    last_note_held: bool = False


@dataclass
class Chorus:
    no: int
    source: str  # file name in the CPDL directory
    title: str
    bpm: float
    da_capo: bool
    text: str
    # (wrong syllable, next syllable starts with, right syllable): source typos
    fixes: tuple[tuple[str, str, str], ...] = ()


CHORALES = [
    Chorale(5, "bwv248.5", "Wie soll ich dich empfangen", 60, "beats",
            "Wie soll ich dich emp-fan-gen und wie be-gegn ich dir? "
            "O al-ler Welt Ver-lan-gen, o mei-ner See-len Zier! "
            "O Je-su, Je-su, set-ze mir selbst die Fa-ckel bei, "
            "da-mit, was dich er-göt-ze, mir kund und wis-send sei!"),
    Chorale(9, "bwv248.9-1", "Ach mein herzliebes Jesulein", 72, "corpus",
            "Ach mein herz-lie-bes Je-su-lein, mach dir ein rein sanft Bet-te-lein, "
            "zu ruhn in mei-nes Her-zens Schrein, dass ich nim-mer ver-ges-se dein."),
    Chorale(12, "bwv248.12-2", "Brich an, o schönes Morgenlicht", 60, "beats",
            "Brich an, o schö-nes Mor-gen-licht, und lass den Him-mel ta-gen! "
            "Du Hir-ten-volk, er-schre-cke nicht, weil dir die En-gel sa-gen, "
            "dass die-ses schwa-che Knä-be-lein soll un-ser Trost und Freu-de sein, "
            "da-zu den Sa-tan zwin-gen und letzt-lich Frie-den brin-gen!"),
    Chorale(17, "bwv248.17", "Schaut hin, dort liegt im finstern Stall", 60, "beats",
            "Schaut hin, dort liegt im fin-stern Stall, des Herr-schaft ge-het ü-ber-all! "
            "Da Spei-se vor-mals sucht ein Rind, da ru-het itzt der Jung-frau'n Kind."),
    Chorale(23, "bwv248.23-2", "Wir singen dir in deinem Heer", 84, "corpus",
            "Wir sin-gen dir in dei-nem Heer aus al-ler Kraft Lob, Preis und Ehr, "
            "dass du, o lang ge-wünsch-ter Gast, dich nun-mehr ein-ge-stel-let hast."),
    Chorale(28, "bwv248.28", "Dies hat er alles uns getan", 66, "beats",
            "Dies hat er al-les uns ge-tan, sein groß Lieb zu zei-gen an; "
            "des freu sich al-le Chri-sten-heit und dank ihm des in E-wig-keit. "
            "Ky-ri-e-leis!", last_note_held=True),
    Chorale(33, "bwv248.33-3", "Ich will dich mit Fleiß bewahren", 66, "corpus",
            "Ich will dich mit Fleiß be-wah-ren, ich will dir le-ben hier, "
            "dir will ich ab-fah-ren. Mit dir will ich end-lich schwe-ben "
            "vol-ler Freud oh-ne Zeit dort im an-dern Le-ben."),
    # the melody repeats its first line, and the corpus repeats its text there too
    Chorale(35, "bwv248.35-3", "Seid froh dieweil", 66, "corpus",
            "Seid froh die-weil, seid froh die-weil, dass eu-er Heil "
            "ist hie ein Gott und auch ein Mensch ge-bo-ren, "
            "der, wel-cher ist der Herr und Christ in Da-vids Stadt, von vie-len aus-er-ko-ren."),
]

CHORUSES = [
    Chorus(1, "Bach_Weihnachtsoratorium_1_-_Jauchzet,_frohlocket.mxl", "Jauchzet, frohlocket", 92, True,
           "Jauch-zet, froh-lo-cket, auf, prei-set die Ta-ge, rüh-met, was heu-te der Höch-ste ge-tan! "
           "Las-set das Za-gen, ver-ban-net die Kla-ge, stim-met voll Jauch-zen und Fröh-lich-keit an! "
           "Die-net dem Höch-sten mit herr-li-chen Chö-ren, lasst uns den Na-men des Herr-schers ver-eh-ren!"),
    Chorus(21, "Bach_Weihnachtsoratorium_21_-_Ehre_sei_Gott.mxl", "Ehre sei Gott in der Höhe", 76, False,
           "Eh-re sei Gott in der Hö-he und Frie-de auf Er-den und den Men-schen ein Wohl-ge-fal-len."),
    Chorus(24, "Bach_Weihnachtsoratorium_24_-_Herrscher_des_Himmels.mxl",
           "Herrscher des Himmels, erhöre das Lallen", 84, False,
           "Herr-scher des Him-mels, er-hö-re das Lal-len, lass dir die mat-ten Ge-sän-ge ge-fal-len, "
           "wenn dich dein Zi-on mit Psal-men er-höht! Hö-re der Her-zen froh-lo-cken-des Prei-sen, "
           "wenn wir dir jet-zo die Ehr-furcht er-wei-sen, weil uns-re Wohl-fahrt be-fe-sti-get steht.",
           fixes=(("dichdein", "", f"dich{lyrics.ELISION}dein"),)),
    Chorus(26, "Bach_Weihnachtsoratorium_26_-_Lasset_uns_nun_gehen_gen_Bethlehem.mxl",
           "Lasset uns nun gehen gen Bethlehem", 112, False,
           "Las-set uns nun ge-hen gen Beth-le-hem und die Ge-schich-te se-hen, die da ge-sche-hen ist, "
           "die uns der Herr kund-ge-tan hat.",
           fixes=(("ge", "Beth", "gen"),)),
]

SUNG = {"Soprano", "Alto", "Tenor", "Bass"}


def soprano_positions(part: stream.Part, chorale: Chorale) -> list[float]:
    starts = sorted(lyrics.onsets(part).items())
    if chorale.positions == "corpus":
        positions = [o for o, n in starts if n.lyrics]
    else:  # on a quarter beat within the bar
        positions = [o for o, n in starts if float(n.offset).is_integer()]
    return positions[:-1] if chorale.last_note_held else positions


def build_chorale(c: Chorale) -> tuple[stream.Score, list[str]]:
    score = corpus.parse("bach/" + c.corpus_id)
    if score.recurse().getElementsByClass("Repeat"):
        score = score.expandRepeats()
    soprano = next(p for p in score.parts if p.partName == "Soprano")
    positions = soprano_positions(soprano, c)
    text = lyrics.syllables(c.text)
    problems = [] if len(positions) == len(text) else [
        f"soprano has {len(positions)} syllable onsets, the text {len(text)} syllables"]
    for part in score.parts:
        if part.partName in SUNG:
            problems += lyrics.underlay(part, positions, text)
        else:
            for n in part.recurse().notes:
                n.lyrics = []
    return score, problems


def build_chorus(c: Chorus, cpdl: Path) -> tuple[stream.Score, list[str]]:
    score = converter.parse(cpdl / c.source)
    libretto = lyrics.Libretto.parse(c.text)
    problems = []
    for part in score.parts:
        lyrics.spread_melisma_words(part, libretto)
        fix_typos(part, c.fixes)
        unknown = lyrics.join_words(part, libretto)
        if unknown:
            problems.append(f"{part.partName}: not in the libretto: {unknown[:8]}")
    split_off_last_rest_bar(score)
    if c.da_capo:
        write_out_da_capo(score)
    return score, problems


def split_off_last_rest_bar(score: stream.Score) -> None:
    """Leave the last bar of every multi-bar rest on its own, so that playback can be
    started a bar before the voice comes in."""
    for sp in list(score.recurse().getElementsByClass(spanner.MultiMeasureRest)):
        rests = sp.getSpannedElements()
        if len(rests) < 2:
            continue
        last = rests[-1]
        bar = last.getContextByClass(stream.Measure)
        sp.spannerStorage.remove(last)
        # the source hides the rests inside a multi-bar rest and squeezes their bars
        last.style.hideObjectOnPrint = False
        last.style.absoluteX = None
        if bar is not None:
            bar.layoutWidth = None
        if len(rests) == 2:
            sp.activeSite.remove(sp)
        else:
            sp.numRests = len(rests) - 1


def fix_typos(part: stream.Part, fixes: tuple[tuple[str, str, str], ...]) -> None:
    sung = lyrics.sung_lyrics(part)
    for lyric, following in zip(sung, sung[1:] + [None]):
        for wrong, before, right in fixes:
            if lyric.text == wrong and (not before or (following and following.text.startswith(before))):
                lyric.text = right


def write_out_da_capo(score: stream.Score) -> None:
    """Append bars 1 to the bar with the fermata (the Fine) to every part."""
    for text in list(score.recurse().getElementsByClass(expressions.TextExpression)):
        if "capo" in text.content.lower():
            text.activeSite.remove(text)
    for part in score.parts:
        measures = list(part.getElementsByClass(stream.Measure))
        fine = next(m.number for m in measures
                    if any(isinstance(e, expressions.Fermata) for n in m.notesAndRests for e in n.expressions))
        last = measures[-1]
        for barline in list(last.getElementsByClass("Barline")):
            last.remove(barline)
        last.rightBarline = "light-light"
        number = last.number
        for m in measures:
            if m.number > fine:
                break
            again = copy.deepcopy(m)
            number += 1
            again.number = number
            if m.number == 1:
                for cls in ("TimeSignature", "KeySignature", "Clef", "MetronomeMark"):
                    for x in list(again.getElementsByClass(cls)):
                        again.remove(x)
            part.append(again)
        part.getElementsByClass(stream.Measure)[-1].rightBarline = "final"


def finish(score: stream.Score, no: int, title: str, bpm: float, out: Path) -> Path:
    score.metadata = metadata.Metadata()
    score.metadata.title = f"Weihnachtsoratorium Nr. {no}: {title}"
    score.metadata.movementName = score.metadata.title
    score.metadata.composer = COMPOSER
    for mark in list(score.recurse().getElementsByClass(tempo.MetronomeMark)):
        mark.activeSite.remove(mark)
    score.parts[0].getElementsByClass(stream.Measure)[0].insert(0, tempo.MetronomeMark(number=bpm, referent=1.0))
    path = out / f"wo-{no:02d}-{slug(title)}.musicxml"
    score.write("musicxml", fp=path)
    return path


def slug(title: str) -> str:
    s = title.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return "-".join("".join(c if c.isalnum() else " " for c in s).split())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("numbers", nargs="*", type=int, help="only these numbers")
    parser.add_argument("--cpdl", type=Path, default=ROOT / "pieces" / "sources" / "cpdl")
    parser.add_argument("--out", type=Path, default=ROOT / "pieces")
    args = parser.parse_args()
    wanted = set(args.numbers)
    for c in CHORALES:
        if not wanted or c.no in wanted:
            score, problems = build_chorale(c)
            report(finish(score, c.no, c.title, c.bpm, args.out), problems)
    for c in CHORUSES:
        if not wanted or c.no in wanted:
            if not (args.cpdl / c.source).exists():
                print(f"{c.no}: no {c.source} in {args.cpdl}, skipped")
                continue
            score, problems = build_chorus(c, args.cpdl)
            report(finish(score, c.no, c.title, c.bpm, args.out), problems)


def report(path: Path, problems: list[str]) -> None:
    print(path.name)
    for p in problems:
        print("   ", p)


if __name__ == "__main__":
    main()
