from pathlib import Path

import pytest
from music21 import corpus

from mockingbird import difficulty
from mockingbird.data.extract import extract_file
from mockingbird.data.filters import dedup, reject_reason
from mockingbird.data.segment import segment, bars_of
from mockingbird.schema import Note, Phrase
from mockingbird.tokenizer import normalize


@pytest.fixture(scope="module")
def bwv269():
    path = Path(corpus.getComposer("bach")[0]).parent / "bwv269.mxl"
    phrases, rejects = extract_file(path, "bach/bwv269", "chorale")
    return phrases, rejects


def test_bach_chorale_extraction(bwv269):
    phrases, rejects = bwv269
    assert rejects == []
    assert len(phrases) == 1
    ph = phrases[0]
    assert ph.mode == "major" and ph.original_tonic == "G" and ph.meter == "3/4"
    assert ph.pickup_ticks == 24  # one-quarter pickup
    assert ph.range_bucket == "S"
    # frame transposition: the final soprano note of this chorale is the tonic G -> C
    assert [n.pitch for n in ph.notes if n.pitch is not None][-1] % 12 == 0
    assert reject_reason(segment(ph)[0]) is None


def test_difficulty_is_monotonic():
    q = 24
    easy = Phrase(mode="major", meter="4/4", style="folk",
                  notes=[Note(pitch=p, duration=q) for p in (60, 62, 64, 65, 67, 65, 64, 62) * 2])
    hard = Phrase(mode="major", meter="4/4", style="folk",
                  notes=[Note(pitch=p, duration=d) for p, d in
                         zip((60, 70, 61, 72, 58, 69, 63, 75, 60, 71, 62, 73, 57, 68, 64, 76),
                             (12, 36, 6, 18, 24, 12, 12, 24, 6, 6, 36, 12, 18, 30, 12, 24))])
    assert difficulty.score(easy) < 15 < difficulty.score(hard)
    th = difficulty.Thresholds({"folk": [10, 20, 30, 40]})
    assert th.bucket(5, "folk") == 1 and th.bucket(25, "folk") == 3 and th.bucket(45, "folk") == 5
    assert th.bucket_range(3, "folk") == (20, 30)


def test_segment_splits_long_phrase_at_bar_boundaries():
    q = 24
    notes = [Note(pitch=60 + (i % 5), duration=q) for i in range(4 * 50)]  # 50 bars of 4/4
    ph = Phrase(mode="major", meter="4/4", style="renaissance", notes=notes, source="x")
    windows = segment(ph)
    assert len(windows) >= 2
    for w in windows:
        n_bars = len(bars_of(w))
        assert n_bars <= 32
        assert w.total_ticks() % 96 == 0
    assert windows[0].source == "x@0"


def test_dedup_removes_exact_copies():
    q = 24
    a = Phrase(mode="major", meter="4/4", style="folk", source="a",
               notes=[Note(pitch=p, duration=q) for p in (60, 62, 64, 65, 67, 65, 64, 62) * 2])
    b = a.model_copy(update={"source": "b"})
    kept, dropped = dedup([a, b])
    assert len(kept) == 1 and dropped == 1
