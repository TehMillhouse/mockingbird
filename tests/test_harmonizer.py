from mockingbird.harmonize.render import render, resolve_texture
from mockingbird.harmonize.viterbi import harmonize
from mockingbird.harmonize.voicing import _parallels, voice
from mockingbird.schema import Note

Q = 24


def twinkle_notes(shift: int = 0):
    p = [60, 60, 67, 67, 69, 69, 67, 65, 65, 64, 64, 62, 62, 60]
    d = [Q, Q, Q, Q, Q, Q, 2 * Q, Q, Q, Q, Q, Q, Q, 2 * Q]
    return [Note(pitch=a + shift, duration=b) for a, b in zip(p, d)]


def test_twinkle_gets_tonic_and_dominant_chords():
    chords = harmonize(twinkle_notes(), "4/4", "major", 0, offset=0, ending=True)
    romans = [c.roman for c in chords]
    assert romans[0] == "I" and romans[-1] == "I"
    assert any(r in ("V", "V7") for r in romans)
    assert chords[0].symbol == "C"
    # spans tile the melody exactly and start on beats
    assert sum(c.duration for c in chords) == 4 * 4 * Q  # four bars of 4/4
    assert all(c.start % Q == 0 for c in chords)
    assert all(a.start + a.duration == b.start for a, b in zip(chords, chords[1:]))
    assert len(chords) < 32  # merged spans, not one chord per beat


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


def test_voicing_is_below_melody_and_well_behaved():
    melody = twinkle_notes(shift=12)  # C5 .. A5, a soprano
    chords = harmonize(melody, "4/4", "major", 0, ending=True)
    voicings = voice(chords, melody, "major", 0, below_melody=True, ending=True)
    assert len(voicings) == len(chords)
    for c, v in zip(chords, voicings):
        assert v.bass <= v.tenor <= v.alto
        assert 36 <= v.bass <= 57
        # every accompaniment pitch is a chord tone
        pcs = {v.bass % 12, v.tenor % 12, v.alto % 12}
        assert pcs <= {(c.root_pc + i) % 12 for i in ((0, 4, 7, 10) if c.quality == "dom7" else (0, 4, 7) if c.quality == "maj" else (0, 3, 7) if c.quality == "min" else (0, 3, 6))}
    top = min(n.pitch for n in melody if n.pitch is not None)
    assert all(v.alto < top + 12 for v in voicings)
    # few parallel perfect intervals between consecutive voicings
    par = sum(_parallels(a.pitches(), b.pitches()) for a, b in zip(voicings, voicings[1:]))
    assert par <= 1
    # final chord in root position (tonic in the bass)
    assert voicings[-1].bass % 12 == 0


def test_textures_tile_the_melody_without_overlap():
    melody = twinkle_notes(shift=12)
    chords = harmonize(melody, "4/4", "major", 0, ending=True)
    voicings = voice(chords, melody, "major", 0)
    total = sum(n.duration for n in melody)
    for texture in ("chorale", "block", "oompah", "broken"):
        ev = render(chords, voicings, melody, "4/4", texture)
        assert ev and ev[0].start == 0
        assert all(a.start + a.duration == b.start for a, b in zip(ev, ev[1:]))
        assert ev[-1].start + ev[-1].duration == total
        assert max(p for e in ev for p in e.pitches) < min(n.pitch for n in melody if n.pitch is not None)
    assert render(chords, voicings, melody, "4/4", "none") == []
    assert resolve_texture("auto", "folk") == "oompah" and resolve_texture("block", "folk") == "block"
    chorale = render(chords, voicings, melody, "4/4", "chorale")
    assert len(chorale) >= len(chords)  # re-attacks at melody onsets
