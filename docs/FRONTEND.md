# Frontend

A browser app in `web/` (Vite, TypeScript). It fetches a level from the API, shows it as
sheet music and plays it. The singer's pitch is drawn over the notation itself, because
the point is learning to sight-sing from a score.

It covers notation, playback, a live mix, live tempo, the microphone pitch trace and
latency calibration. There is no separate score: the coloured trace is the feedback.

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
| `audio.ts` | The shared AudioContext and output routing |
| `devices.ts` | Input and output device pickers |
| `synth.ts` | Voice guide (mono synth) and piano (sampled), each behind its own gain node |
| `transport.ts` | Schedules the level on Tone.js's transport in ticks; tempo is the transport's BPM |
| `score.ts` | abcjs rendering, the ticks → score-position map, the cursor, melody note heads |
| `pitch.ts` | Microphone input and pitch detection |
| `overlay.ts` | The pitch trace drawn into the score's SVG |
| `latency.ts` | Calibration procedures and stored offsets |
| `main.ts` | Controls and keybinds |

Output device choice needs `AudioContext.setSinkId`, which only the native context
has, so where the browser supports it Tone.js runs on a native `AudioContext` instead
of its default wrapper. Elsewhere (Firefox) the wrapper stays, because Tone depends
on its polyfills there, and playback goes to the system default output. The input device
is chosen through `getUserMedia`'s `deviceId`. Both choices are remembered per
browser. Device names are only readable after microphone permission is granted, so
the lists are refreshed once the mic opens.

abcjs only draws; it never plays. Tone.js's 192 PPQ is exactly 8 of its ticks per level
tick (24 per quarter), so every event lands on an exact transport tick. A tempo change
therefore applies to every note that has not started yet.

## Ticks → position on the score

abcjs's `TimingCallbacks.noteTimings` gives each onset its time (at the ABC's `Q:`
tempo, which is the level's) and its SVG box. The times are converted to level ticks
and stored, so the map does not depend on the playback tempo. Between two onsets on
the same system the cursor moves linearly. On the last onset of a system it runs
across that note's width.

The cursor shows the tick that is heard when the frame is seen:
`transport.getTicksAtTime(currentTime − (A − V))` (see the latency model), not the
transport's lookahead position.

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
- **Time:** a reading is timestamped at the centre of its window and mapped to the
  tick the singer was hearing: `transport.getTicksAtTime(time − (A + I))`.

## Latency model

| Symbol | Latency | Notes |
|---|---|---|
| A | audio output: scheduled sound → ear | Around 200 ms extra on Bluetooth |
| V | visual: frame drawn → seen on screen | |
| I | input: sound at the mic → analysed pitch | Includes half the analysis window (about 21 ms for 2048 samples) |

Two combinations need calibrating:

- **A − V aligns the cursor with what is heard.** It is measured by tapping along with
  clicks, then along with flashes. The median tap delay after the clicks is A plus the
  tap latency; after the flashes it is V plus the tap latency. The tap latency cancels
  in the difference. Click times are converted to the performance clock through the
  same "now" pairing the cursor uses, so any constant skew between the clocks is
  calibrated away too.
- **A + I places the trace.** The singer follows what they hear, so a sung event is
  captured A + I after its scheduled time. It is measured by clapping along with
  clicks. Claps are detected as the first sample above four times the noise floor
  measured before the first click, and both clicks and claps are timed on the
  AudioContext clock. Over speakers the mic hears the clicks themselves, which
  measures the same thing.

Each run is 4 count-in clicks plus 12 counted ones, 0.6 s apart. Each counted stimulus
takes its nearest response, and at least 6 must be matched. The median is stored.

V does not affect the trace: trace x comes from the corrected capture time, not from
when a frame is drawn. Without calibration, A − V falls back to the browser's reported
`outputLatency + baseLatency`, and A + I to that plus the track's reported input
latency; these are often missing or wrong. Calibrated offsets are stored per device
label: A − V per output, A + I per output and input pair. Singing requires
headphones, so the backing does not reach the mic.
