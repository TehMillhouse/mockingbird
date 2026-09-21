# Mockingbird

Sight-singing trainer for a classical choir. This repository currently holds the
level-generation backend: a small locally trained melody model, a rule-based
harmonizer, exporters (ABC, MusicXML, MIDI) and an HTTP API with a development preview
page. The playing UI, microphone scoring and backing singer are future milestones.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and, for GPU training, an NVIDIA card with a
CUDA 12.8 driver (CPU works for generation, slower for training).

```bash
uv sync --all-groups
```

## Pipeline

```bash
uv run mb data build          # corpora -> data/processed/{train,val}.jsonl  (~5 min)
uv run mb train               # -> models/melody-v1.pt                       (~15 min on GPU)
uv run mb generate --tonic D --mode major --voice S --difficulty 2 --bars 8 --out level.abc
uv run mb serve               # API on http://127.0.0.1:8000, preview page at /
uv run pytest
```

`mb generate --out` also accepts `.musicxml`, `.mid` and `.json`.

### Training data

The music21 corpora ship with the package. OpenScore Lieder is an optional extra:
clone it into `data/external/Lieder` (about 850 MB; `git clone --depth 1
https://github.com/OpenScore/Lieder data/external/Lieder`) and the build picks it up.
Its MuseScore files are read directly with the `ms3` package; the ~180 MuseScore 2
files in the corpus are skipped.

| Source | Style tag | What is used |
| --- | --- | --- |
| Essen Folksong Collection (European files; the Chinese `han*` files are skipped) | `folk` | whole tunes |
| Bach chorales | `chorale` | soprano line |
| Palestrina masses, Monteverdi madrigals, Josquin | `renaissance` | top voice |
| OpenScore Lieder (1,300 songs, CC0) | `lied` | vocal staff |

Extraction picks the top vocal part, merges bars that the source split around repeat
signs, halves old-notation meters (4/2 becomes 4/4), ends a section at any bar with
tuplets, drops unsupported meters, and trims rest-only bars (piano intros) from the
ends of every window. The key is read from the final of the lowest voice (melody
final for monophonic tunes) with the mode taken from the third above it; modal pieces
therefore land in the nearest major or minor frame with their characteristic degrees
as accidentals. Every melody is transposed so the tonic is C (major) or A (minor) and
cut into windows of at most 32 bars. Filters, dedup and per-file reject reasons are
written next to the output (`data/processed/rejects.tsv`, `stats.json`).

### Token format

```
BOS MODE_major METER_4_4 DIFF_2 STYLE_chorale RANGE_S [PICKUP]
P67 D24 P67 D24 P69 D24 P71 D24 BAR ... EOS
```

Pitches are absolute MIDI numbers in the C/A frame, durations are ticks (24 per
quarter), `BAR` closes every bar and `TIE` joins a note to the next. In windows that
really contain the last bar of the source piece, each of the last four bars starts
with a countdown token `REMAIN_4` … `REMAIN_1`, so the model learns how endings are
prepared; generation forces the countdown at the requested bar count. The key tonic
is never a token: it is applied on export. Difficulty buckets are calibrated to
quintiles of the training data per style (`models/difficulty_thresholds.json`).

### Generation

The model (a 5M-parameter GPT-style decoder) samples eight candidates under logit
masks that guarantee the token grammar, exact bar fill, the requested bar count, a
pitch span that fits the voice, a leap cap per difficulty and, for levels 1 and 2,
diatonic pitches only. Candidates are scored with the difficulty function, checked
against a 12-note n-gram index of the training set (no verbatim copies), harmonized
with a Viterbi search over functional chords (one per half bar in 4/4, per bar
otherwise), rendered as block chords or arpeggios below the melody, and transposed
into the requested key and voice range.

### API

```
POST /levels                      {tonic, mode, meter, voice, difficulty, bars, style?, accompaniment?, tempo_bpm?, seed?}
GET  /levels/{id}                 level JSON
GET  /levels/{id}/export?fmt=abc|musicxml|midi
GET  /health
GET  /                            preview page (abcjs playback: Space play/pause, R restart, +/- tempo, G generate)
```

The level JSON (`mockingbird/schema.py`) is the renderer-independent contract for any
future frontend.

## Layout

```
mockingbird/
  theory.py, schema.py, tokenizer.py, difficulty.py
  data/        sources, extract, segment, filters, build
  model.py, train.py
  generate/    constraints, sampler, service
  harmonize/   chords, viterbi, render
  export/      to_music21, formats
  api/app.py, cli.py
tools/abc_preview.html
tests/
```
