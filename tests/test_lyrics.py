"""Sung text: syllables from a hyphenated libretto, word joins, melisma repairs, underlay."""
from music21 import note, stream, tie

from mockingbird import lyrics

LIBRETTO = lyrics.Libretto.parse(
    "Jauch-zet, froh-lo-cket, auf, prei-set die Ta-ge, rüh-met, was heu-te der Höch-ste ge-tan! "
    "Las-set das Za-gen, ver-ban-net die Kla-ge, wenn dich dein Zi-on mit Psal-men er-höht! "
    "Die-net dem Höch-sten")


def _part(*events):
    """A part of quarter notes on C4 (None: a quarter rest) with the given lyric texts."""
    part = stream.Part()
    for text in events:
        if text is None:
            part.append(note.Rest())
            continue
        n = note.Note("C4")
        if text:
            n.addLyric(text)
        part.append(n)
    return part


def _sung(part):
    return [(ly.text, ly.syllabic) for n in part.recurse().notes for ly in n.lyrics]


def test_syllables_from_hyphenated_words():
    assert lyrics.syllables("Höch-ste ge-tan! froh-lo-cket auf") == [
        ("Höch", "begin"), ("ste", "end"), ("ge", "begin"), ("tan!", "end"),
        ("froh", "begin"), ("lo", "middle"), ("cket", "end"), ("auf", "single")]


def test_word_spans_join_syllables_of_libretto_words():
    texts = ["Jauch", "zet,", "froh", "lo", "cket!", "die", "Ta", "ge", "der", "Höch", "ste", "ge", "tan!"]
    syllabic, unknown = lyrics.word_spans(texts, LIBRETTO)
    assert syllabic == ["begin", "end", "begin", "middle", "end", "single", "begin", "end",
                        "single", "begin", "end", "begin", "end"]
    assert unknown == []


def test_word_spans_prefer_the_longer_word():
    # "die" is a word, and so is "Dienet"
    syllabic, _ = lyrics.word_spans(["Die", "net", "dem", "Höch", "sten"], LIBRETTO)
    assert syllabic == ["begin", "end", "single", "begin", "end"]


def test_word_spans_stop_at_punctuation_and_report_unknown_words():
    syllabic, unknown = lyrics.word_spans(["Ta,", "ge", "Blub"], LIBRETTO)
    assert syllabic == ["single", "single", "single"]
    assert unknown == ["Ta,", "ge", "Blub"]


def test_elided_syllables_count_as_libretto_words():
    _, unknown = lyrics.word_spans(["wenn", f"dich{lyrics.ELISION}dein", "Zi", "on"], LIBRETTO)
    assert unknown == []


def test_join_words_drops_empty_placeholders():
    part = _part("Las", "", "set", "das")
    part.recurse().notes[1].addLyric("")  # a melisma placeholder
    assert lyrics.join_words(part, LIBRETTO) == []
    assert _sung(part) == [("Las", "begin"), ("set", "end"), ("das", "single")]


def test_whole_word_under_a_melisma_is_spread_to_its_end():
    part = _part("das", "Zagen,", "", "", "", None, "ver")
    assert lyrics.spread_melisma_words(part, LIBRETTO) == 1
    texts = [n.lyrics[0].text if n.lyrics else "" for n in part.recurse().notes]
    assert texts == ["das", "Za", "", "", "gen,", "ver"]


def test_part_of_a_word_is_spread_too():
    part = _part("froh", "locket!", "", "auf")
    lyrics.spread_melisma_words(part, LIBRETTO)
    assert [n.lyrics[0].text if n.lyrics else "" for n in part.recurse().notes] == ["froh", "lo", "cket!", "auf"]


def test_a_word_is_not_spread_beyond_its_melisma():
    part = _part("Zagen,", "ver")
    assert lyrics.spread_melisma_words(part, LIBRETTO) == 0


def test_underlay_uses_a_tied_over_note_and_keeps_the_tie():
    part = _part("", "", "")
    first, held, last = part.recurse().notes
    first.tie, held.tie = tie.Tie("start"), tie.Tie("stop")
    assert lyrics.underlay(part, [0.0, 1.0, 2.0], lyrics.syllables("Ky-ri-e")) == []
    assert _sung(part) == [("Ky", "begin"), ("ri", "middle"), ("e", "end")]
    assert held.tie.type == "stop"


def test_underlay_reports_a_syllable_without_a_note():
    part = _part("", "")
    part.partName = "Alto"
    problems = lyrics.underlay(part, [0.0, 0.5, 1.0], lyrics.syllables("a b c"))
    assert problems == ["Alto: no note for 'b' at 0.5"]
