# Frontend

A browser app in `web/` (Vite, TypeScript). It fetches a level from the API, shows it as
sheet music and plays it. The singer's pitch is drawn over the notation itself, because
the point is learning to sight-sing from a score.

Built: notation, playback, live mix, live tempo, microphone pitch trace.
Not yet built: latency calibration, scoring.

## Running

```bash
uv run mb serve               # API on :8000
npm --prefix web install
npm --prefix web run dev      # app on :5173, API routes proxied to :8000
```

`npm --prefix web run build` writes `web/dist`. When that exists, `mb serve` serves it
at `/`; otherwise `/` falls back to the abcjs preview page in `tools/`.

## Architecture

The server only sends symbolic data: the level JSON and its ABC export. Everything
audible is synthesized in the browser from the level, never prerendered. This is what
makes the mix and tempo live: prerendered audio would need time-stretching for tempo
and separate stems for mixing.

| Module | Role |
|---|---|
| `level.ts` | Level types (mirrors `schema.py`), fetching |
| `synth.ts` | Voice guide (mono synth) and piano (sampled), each behind its own gain node |
| `transport.ts` | Schedules the level on Tone.js's transport in ticks; tempo is the transport's BPM |
| `score.ts` | abcjs rendering, the ticks → score-position map, the cursor, melody note heads |
| `pitch.ts` | Microphone input and pitch detection |
| `overlay.ts` | The pitch trace drawn into the score's SVG |
| `main.ts` | Controls and keybinds |

abcjs only draws; it never plays. Tone.js's 192 PPQ is exactly 8 of its ticks per level
tick (24 per quarter), so every event lands on an exact transport tick. A tempo change
therefore applies to every note that has not started yet.

## Ticks → position on the score

abcjs's `TimingCallbacks.noteTimings` gives each onset its time (at the ABC's `Q:`
tempo, which is the level's) and its SVG box. The times are converted to level ticks
and stored, so the map does not depend on the playback tempo. Between two onsets on
the same system the cursor moves linearly. On the last onset of a system it runs
across that note's width.

The cursor follows the tick currently reaching the speakers:
`transport.getTicksAtTime(currentTime − output latency)`, not the transport's
lookahead position.

## Pitch trace

- **Vertical position is relative to the target note:**
  y = note head y − (cents deviation / 100) × half a staff step.
  Enharmonic notes share a staff position, so absolute pitch → staff y is ambiguous;
  measuring against the target avoids that. It also handles the tenor `treble-8`
  clef, because the target's MIDI pitch already carries the octave.
- **Octave errors are folded:** the sung pitch is moved to the octave nearest the
  target before drawing and scoring.
- **Hits:** within ±50 cents counts as a hit, and the trace is coloured by deviation.
- **Detection:** McLeod pitch method (pitchy) on the latest 2048-sample
  `AnalyserNode` window, sampled every 10 ms on a timer, so the rate does not depend
  on the display. Readings below 0.9 clarity are dropped. The browser's echo
  cancellation, noise suppression and gain control are off, since they distort
  sustained pitch.
- **Target lookup:** abcjs draws one note or rest group per melody entry on voice 0,
  in order. Each sung note's head position comes from its group's note head; a
  staff step is an eighth of the five-line staff's height.
- **Time:** a reading is timestamped at the centre of its window. It is mapped to the
  tick the singer was hearing through input and output latency (see below). Until
  calibration exists, those are the browser's reported values.

## Latency model (design)

| Symbol | Latency | Notes |
|---|---|---|
| A | audio output: scheduled sound → ear | Around 200 ms extra on Bluetooth |
| V | visual: frame drawn → seen on screen | |
| I | input: sound at the mic → analysed pitch | Includes half the analysis window (about 21 ms for 2048 samples) |

Two combinations need calibrating:

- **A − V aligns the cursor with what is heard.** Measure it by tapping a key along with
  a click, then along with a flash. The keyboard's own latency cancels in the difference.
- **A + I places the trace and scores it.** The singer follows what they hear, so a
  sung event is captured A + I after its scheduled time. Measure it by singing or
  clapping along with a click.

V does not affect the trace: trace x comes from the corrected capture time, not from
when a frame is drawn. The browser's reported `outputLatency` / `baseLatency` are only
starting values; they are often missing or wrong. Calibrated offsets are stored per
input/output device label, because headphones and speakers differ. Singing requires
headphones, so the backing does not reach the mic.
