"""Constraint and export tests using a tiny randomly initialised model (CPU)."""
import pytest
import torch
from music21 import converter

from mockingbird import tokenizer as tk
from mockingbird.export.formats import to_abc, to_midi, to_musicxml
from mockingbird.generate.constraints import ConstraintState
from mockingbird.generate.sampler import sample
from mockingbird.generate.service import LevelGenerator
from mockingbird.model import MelodyModel, ModelConfig
from mockingbird.schema import GenerateRequest, Phrase
from mockingbird.theory import VOICE_RANGES, bar_ticks, is_diatonic


@pytest.fixture(scope="module")
def tiny_model():
    torch.manual_seed(0)
    return MelodyModel(ModelConfig(n_layer=2, d_model=64, n_head=2, d_ff=128, max_len=512, dropout=0.0)).eval()


@pytest.mark.parametrize("mode,meter,voice,difficulty,bars", [
    ("major", "4/4", "S", 1, 4), ("minor", "3/4", "B", 2, 6), ("major", "6/8", "T", 3, 3),
    ("minor", "2/4", "A", 5, 8),
])
def test_constrained_samples_are_well_formed(tiny_model, mode, meter, voice, difficulty, bars):
    prefix = tk.prefix_tokens(mode, meter, difficulty, "folk", voice)
    state = ConstraintState(mode=mode, meter=meter, voice=voice, difficulty=difficulty, bars=bars)
    seqs = sample(tiny_model, prefix, n=4, max_new=400, device="cpu", temperature=1.5,
                  mask_fn=lambda r, toks: state.allowed(toks), seed=1)
    for s in seqs:
        dec = tk.decode(s)
        assert s[-1] == tk.tid(tk.EOS)
        assert dec.complete_bars == bars and dec.trailing_ticks == 0
        assert dec.phrase.total_ticks() == bars * bar_ticks(meter)
        pitched = [n.pitch for n in dec.phrase.notes if n.pitch is not None]
        if pitched:
            lo, hi = VOICE_RANGES[voice]
            assert max(pitched) - min(pitched) <= hi - lo
            if difficulty <= 2:
                assert all(is_diatonic(p, mode) for p in pitched)
        names = [tk.VOCAB[t] for t in s]
        remain = [n for n in names if n.startswith("REMAIN")]
        assert remain == [f"REMAIN_{k}" for k in range(min(bars, tk.COUNTDOWN), 0, -1)]
        assert names[names.index("REMAIN_1"):].count("BAR") == 1
        assert dec.phrase.is_ending
        # re-encoding the decoded phrase reproduces the stream: grammar was respected
        assert tk.encode(dec.phrase, difficulty=difficulty, range_bucket=voice) == s


def test_finish_places_melody_in_voice_range_and_exports(tiny_model, tmp_path):
    gen = LevelGenerator.__new__(LevelGenerator)
    q = 24
    notes = [dict(pitch=p, duration=q) for p in (60, 62, 64, 65, 67, 65, 64, 62)] * 2
    phrase = Phrase(mode="major", meter="4/4", style="folk", notes=notes)
    for voice in "SATB":
        req = GenerateRequest(tonic="Eb", mode="major", meter="4/4", voice=voice, difficulty=2, bars=4)
        level = gen.finish(phrase, req)
        lo, hi = VOICE_RANGES[voice]
        ps = [n.pitch for n in level.melody if n.pitch is not None]
        assert lo <= min(ps) and max(ps) <= hi
        assert all(c.symbol[0] in "EABDGCF" for c in level.chords)
        assert level.chords[0].symbol == "Eb"
        abc = to_abc(level)
        assert "K:Eb" in abc and "V:2" in abc
        melody_line = abc.split("V:1\n")[1].split("V:2")[0]
        assert melody_line.count("|") == 4
        # music21 splits ABC voice headers into extra empty parts; only check content
        reparsed = converter.parse(abc, format="abc")
        acc_chords = [c for c in reparsed.recurse().getElementsByClass("Chord")
                      if c.__class__.__name__ == "Chord"]  # skip ChordSymbol, a Chord subclass
        assert acc_chords and max(p.midi for c in acc_chords for p in c.pitches) < min(ps)
        melody_notes = [n.pitch.midi for n in reparsed.recurse().notes if n.isNote]
        written = 12 if voice == "T" else 0  # tenor is written an octave up for the treble-8 clef
        assert melody_notes[:len(ps)] == [p + written for p in ps]
        xml = to_musicxml(level)
        score = converter.parse(xml, format="musicxml")
        melody = [n.pitch.midi for n in score.parts[0].recurse().notes if n.isNote]
        assert melody == ps
        assert len(to_midi(level)) > 100


def test_third_identical_bar_is_blocked():
    prefix = tk.prefix_tokens("major", "2/4", 3, "folk", "S")
    bar = ["P60", "D24", "P62", "D24", "BAR"]
    twice = prefix + [tk.tid(t) for t in bar * 2]
    state = ConstraintState(mode="major", meter="2/4", voice="S", difficulty=3, bars=8)
    # after two identical bars and P60 D24 P62, the D24 that would complete a third copy is masked
    partial = twice + [tk.tid(t) for t in ("P60", "D24", "P62")]
    allowed = state.allowed(partial)
    assert not allowed[tk.tid("D24")]
    assert allowed[tk.tid("D12")]
    # a different pitch keeps every fitting duration available
    other = twice + [tk.tid(t) for t in ("P60", "D24", "P64")]
    assert state.allowed(other)[tk.tid("D24")]
    # only one bar so far: repeating it once more is fine
    once = prefix + [tk.tid(t) for t in bar] + [tk.tid(t) for t in ("P60", "D24", "P62")]
    assert state.allowed(once)[tk.tid("D24")]


def test_final_note_must_be_longest_in_last_bar():
    from mockingbird.generate.service import _final_note_is_longest
    from mockingbird.schema import Note, Phrase

    def ph(durs):
        notes = [Note(pitch=60, duration=24)] * 4 + [Note(pitch=62 + i, duration=d) for i, d in enumerate(durs)]
        return Phrase(mode="major", meter="4/4", style="folk", notes=notes)

    assert _final_note_is_longest(ph([24, 24, 48]))
    assert _final_note_is_longest(ph([48, 48]))
    assert not _final_note_is_longest(ph([48, 12, 12, 12, 12]))
    assert not _final_note_is_longest(ph([24, 48, 24]))
