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

PDMX (public-domain MuseScore uploads, CC BY 4.0) is the second optional extra: put
`PDMX.csv` and `mxl.tar.gz` from the Zenodo record into `data/external/pdmx/` and run
`uv run mb data prepare-pdmx`, which selects vocal scores (lyrics, no license
conflict, deduplicated, classical or religious genre) and extracts only those.

| Source | Style tag | What is used |
| --- | --- | --- |
| Essen Folksong Collection (European files; the Chinese `han*` files are skipped) | `folk` | whole tunes |
| Bach chorales | `chorale` | soprano line |
| Palestrina masses, Monteverdi madrigals, Josquin | `renaissance` | top voice |
| OpenScore Lieder (1,300 songs, CC0) | `lied` | vocal staff |
| PDMX vocal subset (~17,000 hymns, part-songs, madrigals, anthems) | `choral` | highest part with lyrics |

Extraction picks the top vocal part (the highest part carrying lyrics, else by part
name, else the highest non-instrumental part), merges bars that the source split around repeat
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
prepared; generation forces the countdown at the requested bar count. Phrase ends
(from source phrase marks, fermatas, lyric punctuation, double bars and long rests)
get the same treatment: `PHRASE_END_IN_4` … `PHRASE_END_IN_1` open the bars before a
phrase end and `CAD_PAC|IAC|HC|SUB|DEC|OTHER` opens the bar containing it, so generation can
request a phrase plan (`phrase_bars`, `cadences`). The key tonic is never a token: it
is applied on export. Difficulty buckets are calibrated to
quintiles of the training data per style (`models/difficulty_thresholds.json`).

### Model variants

`mb train` exposes the architecture switches used for ablations, all recorded in the
checkpoint so generation needs no extra flags:

- `--pos learned|rope|none`: learned absolute positions (default), rotary, or none.
- `--metric-emb` (default on): add embeddings for each token's bar index and tick within
  the bar, both derived from the token stream (`tokenizer.metric_positions`). Same
  validation loss as without, but faster convergence and cleaner endings.
- `--arch looped --n-core 2 --loop-center 3 --loop-jitter 1`: prelude block, a shared
  core block group run `loop_center` times (jittered during training, with a learned
  per-iteration embedding), then a coda block. `--sandwich-norm` adds a LayerNorm on
  each residual branch output, which keeps repeated blocks stable.

`tools/compare_runs.py` tabulates runs; `tools/cadence_metric.py --model <ckpt>`
measures endings.

### Generation

The model (a 1.8M-parameter looped decoder with metric RoPE and metric embeddings; see
"Model variants") samples eight candidates under logit
masks that guarantee the token grammar, exact bar fill, the requested bar count, a
pitch span that fits the voice, a leap cap per difficulty and, for levels 1 and 2,
diatonic pitches only. Candidates are scored with the difficulty function, checked
against a 12-note n-gram index of the training set (no verbatim copies) and
transposed into the requested key and voice range.

### Accompaniment

Rule-based, in three stages (`mockingbird/harmonize`):

1. `viterbi.py` fits functional chords beat by beat (diatonic triads, V7, a few
   secondary dominants) with a change cost that is small on strong beats and large on
   weak ones, so the harmonic rhythm follows the melody but changes land on the beat;
   for endings the last bars are biased towards pre-dominant, dominant, tonic.
2. `voicing.py` voice-leads bass, tenor and alto under the melody by a second Viterbi
   pass over candidate voicings: smooth inner motion, bass by step or contrary to the
   tune, no parallel fifths or octaves with any voice, complete chords, no doubled
   leading tone, root position preferred with a cadential six-four allowed.
3. `render.py` realises a texture: `chorale` (voices re-attack with the melody),
   `oompah` (bass on strong beats, chords between), `broken` (bass-tenor-alto-tenor
   eighths), `block`, or `none`. `auto` picks by style.

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

## History and backlog

`docs/RETROSPECTIVE.md` records which ideas were tried, dropped or adopted, and lists
untried ideas with the problem each one addresses.

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
