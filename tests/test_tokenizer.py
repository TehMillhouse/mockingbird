from hypothesis import given, settings, strategies as st

from mockingbird import tokenizer as tk
from mockingbird.schema import Note, Phrase
from mockingbird.theory import DURATIONS, METERS, PITCH_MAX, PITCH_MIN, bar_ticks


def twinkle() -> Phrase:
    q = 24
    p = [60, 60, 67, 67, 69, 69, 67, 65, 65, 64, 64, 62, 62, 60]
    d = [q, q, q, q, q, q, 2 * q, q, q, q, q, q, q, 2 * q]
    notes = [Note(pitch=pp, duration=dd) for pp, dd in zip(p, d)]
    return Phrase(mode="major", meter="4/4", style="folk", notes=notes, difficulty=1,
                  range_bucket="S")


def test_vocab_is_unique_and_small():
    assert len(set(tk.VOCAB)) == len(tk.VOCAB)
    assert tk.VOCAB_SIZE < 100


def test_twinkle_round_trip_and_bars():
    ph = twinkle()
    toks = tk.encode(ph)
    names = [tk.VOCAB[t] for t in toks]
    assert names[:6] == ["BOS", "MODE_major", "METER_4_4", "DIFF_1", "STYLE_folk", "RANGE_S"]
    assert names.count("BAR") == 4
    assert names[-1] == "EOS"
    dec = tk.decode(toks)
    assert dec.phrase.notes == ph.notes
    assert dec.complete_bars == 4 and dec.trailing_ticks == 0


def test_normalize_splits_crossing_note_with_tie():
    ph = Phrase(mode="major", meter="2/4", style="folk", difficulty=2, range_bucket="A",
                notes=[Note(pitch=60, duration=24), Note(pitch=62, duration=48),
                       Note(pitch=64, duration=24)])
    norm = tk.normalize(ph)
    assert [n.duration for n in norm.notes] == [24, 24, 24, 24]
    assert [n.tie for n in norm.notes] == [False, True, False, False]
    assert tk.merge_ties(norm.notes) == ph.notes
    dec = tk.decode(tk.encode(norm))
    assert dec.phrase.notes == norm.notes


def test_pickup_round_trip():
    ph = Phrase(mode="minor", meter="3/4", style="chorale", difficulty=3, range_bucket="T",
                pickup_ticks=24,
                notes=[Note(pitch=69, duration=24)] + [Note(pitch=71, duration=24)] * 6)
    toks = tk.encode(tk.normalize(ph))
    names = [tk.VOCAB[t] for t in toks]
    assert names[6] == "PICKUP"
    dec = tk.decode(toks)
    assert dec.phrase.pickup_ticks == 24
    assert dec.complete_bars == 2
    assert dec.phrase.notes == tk.normalize(ph).notes


@st.composite
def phrases(draw):
    meter = draw(st.sampled_from(METERS))
    bt = bar_ticks(meter)
    pickup = draw(st.sampled_from([0] + [t for t in range(3, bt, 3)]))
    bars = draw(st.integers(min_value=1, max_value=6))
    notes = []
    total = pickup + bars * bt
    pos = 0
    while pos < total:
        room = min(total - pos, 192)
        dur = draw(st.integers(min_value=1, max_value=room // 3)) * 3
        pitch = draw(st.one_of(st.none(), st.integers(min_value=PITCH_MIN, max_value=PITCH_MAX)))
        tie = draw(st.booleans()) and pitch is not None and pos + dur < total
        notes.append(Note(pitch=pitch, duration=dur, tie=tie))
        pos += dur
    return Phrase(mode=draw(st.sampled_from(["major", "minor"])), meter=meter,
                  style=draw(st.sampled_from(["folk", "chorale", "renaissance"])),
                  difficulty=draw(st.integers(1, 5)), range_bucket=draw(st.sampled_from("SATB")),
                  pickup_ticks=pickup, notes=notes)


@settings(max_examples=300, deadline=None)
@given(phrases())
def test_random_phrase_round_trip(ph):
    norm = tk.normalize(ph)
    assert all(n.duration in DURATIONS for n in norm.notes)
    toks = tk.encode(norm)
    dec = tk.decode(toks)
    assert dec.phrase.notes == norm.notes
    assert dec.phrase.pickup_ticks == ph.pickup_ticks
    assert dec.trailing_ticks == 0
    assert dec.phrase.total_ticks() == ph.total_ticks()
    merged = merge_rests(tk.merge_ties(norm.notes))
    orig = merge_rests(tk.merge_ties(ph.notes))
    assert [(n.pitch, n.duration) for n in merged] == [(n.pitch, n.duration) for n in orig]


def merge_rests(notes):
    out = []
    for n in notes:
        if out and out[-1].pitch is None and n.pitch is None:
            out[-1] = Note(pitch=None, duration=out[-1].duration + n.duration)
        else:
            out.append(n)
    return out


def test_countdown_only_for_endings():
    ph = twinkle()
    assert not any(n.startswith("REMAIN") for n in (tk.VOCAB[t] for t in tk.encode(ph)))
    ending = ph.model_copy(update={"is_ending": True})
    names = [tk.VOCAB[t] for t in tk.encode(ending)]
    remain = [n for n in names if n.startswith("REMAIN")]
    assert remain == ["REMAIN_4", "REMAIN_3", "REMAIN_2", "REMAIN_1"]  # a 4-bar phrase
    assert names[6] == "REMAIN_4"  # right after the prefix
    i = names.index("REMAIN_1")
    assert names[i - 1] == "BAR" and names[i + 1].startswith("P") and names[i:].count("BAR") == 1
    dec = tk.decode(tk.encode(ending))
    assert dec.phrase.is_ending and dec.phrase.notes == ending.notes


def test_countdown_with_pickup_and_partial_last_bar():
    ph = Phrase(mode="major", meter="4/4", style="folk", difficulty=1, range_bucket="S",
                pickup_ticks=24, is_ending=True,
                notes=[Note(pitch=67, duration=24)] + [Note(pitch=60, duration=24)] * 4
                + [Note(pitch=60, duration=72)])
    names = [tk.VOCAB[t] for t in tk.encode(ph)]
    # bars: pickup, one full bar, 72-tick final bar -> countdown 3, 2, 1
    assert [n for n in names if n.startswith("REMAIN")] == ["REMAIN_3", "REMAIN_2", "REMAIN_1"]
    assert names[names.index("REMAIN_1") + 1:names.index("REMAIN_1") + 3] == ["P60", "D72"]
    assert tk.decode(tk.encode(ph)).phrase.is_ending
