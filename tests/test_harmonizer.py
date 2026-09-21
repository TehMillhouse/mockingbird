from mockingbird.harmonize.render import render
from mockingbird.harmonize.viterbi import harmonize
from mockingbird.schema import Note

Q = 24


def twinkle_notes():
    p = [60, 60, 67, 67, 69, 69, 67, 65, 65, 64, 64, 62, 62, 60]
    d = [Q, Q, Q, Q, Q, Q, 2 * Q, Q, Q, Q, Q, Q, Q, 2 * Q]
    return [Note(pitch=a, duration=b) for a, b in zip(p, d)]


def test_twinkle_gets_tonic_and_dominant_chords():
    chords = harmonize(twinkle_notes(), "4/4", "major", 0, offset=0)
    romans = [c.roman for c in chords]
    assert len(chords) == 8  # one per half bar
    assert romans[0] == "I"
    assert romans[-1] == "I"
    assert any(r in ("V", "V7") for r in romans)
    assert chords[0].symbol == "C" and all(c.start % 48 == 0 for c in chords)


def test_symbols_follow_offset():
    chords = harmonize(twinkle_notes(), "4/4", "major", 0, offset=2)
    assert chords[0].symbol == "D"


def test_minor_melody_uses_minor_alphabet():
    m = [69, 71, 72, 74, 76, 77, 80, 81, 81, 80, 77, 76, 74, 72, 71, 69]
    chords = harmonize([Note(pitch=a, duration=Q) for a in m], "4/4", "minor", 0)
    assert chords[0].roman == "i"
    assert all(c.roman in {"i", "ii°", "III", "iv", "V", "V7", "VI", "VII", "vii°", "V/iv", "V/V"} for c in chords)


def test_pickup_gets_its_own_segment():
    notes = [Note(pitch=67, duration=Q)] + twinkle_notes()
    chords = harmonize(notes, "4/4", "major", pickup_ticks=Q)
    assert chords[0].start == 0 and chords[0].duration == Q
    assert chords[1].start == Q


def test_render_stays_below_melody():
    notes = twinkle_notes()
    chords = harmonize(notes, "4/4", "major", 0)
    for style in ("block", "arpeggio"):
        events = render(chords, notes, "4/4", style)
        assert events
        assert max(p for e in events for p in e.pitches) < min(n.pitch for n in notes)
        total = sum(e.duration for e in events)
        assert total == sum(n.duration for n in notes)
    assert render(chords, notes, "4/4", "none") == []
