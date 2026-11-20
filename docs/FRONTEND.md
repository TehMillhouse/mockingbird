# Frontend

A browser app in `web/` (Vite, TypeScript) with two pages on one set of practice
machinery:

- **Sight-singing trainer** (`index.html`): generated levels and the warm-up, one sung
  line over a piano part, rendered with abcjs.
- **Choir pieces** (`piece.html`): real pieces from MusicXML with all their parts and
  lyrics, rendered with OpenSheetMusicDisplay (OSMD). You pick your part; the other
  voices and the piano play along.

Both show the sheet music, play it with a live mix and tempo, count in, start from a
tapped bar, and draw the singer's pitch over the notation itself, because the point is
singing from a score. There is no separate score: the coloured trace is the feedback.

## Running

```bash
uv run mb serve               # API on :8000
npm --prefix web install
npm --prefix web run dev      # app on :5173, API routes proxied to :8000
```

`npm --prefix web run build` writes `web/dist`. When that exists, `mb serve` serves it
at `/`; otherwise `/` falls back to the abcjs preview page in `tools/`. Setting
`MOCKINGBIRD_WEB` points it at a built app elsewhere. Asset and API URLs are
relative, so the app also works behind a proxy under a path prefix (see
`DEPLOY.md`).

## Architecture

The server only sends symbolic data: the level JSON and its ABC export. Everything
audible is synthesized in the browser from the level, never prerendered. This is what
makes the mix and tempo live: prerendered audio would need time-stretching for tempo
and separate stems for mixing.

| Module | Role |
|---|---|
| `practice.ts` | What both pages share: player, microphone, pitch trace, devices, calibration, cursor, keys; the `ScoreView` interface a renderer implements |
| `level.ts` | Level types (mirrors `schema.py`), fetching, level → bars and melody events |
| `audio.ts` | The shared AudioContext and output routing |
| `devices.ts` | Input and output device pickers |
| `synth.ts` | Voice guide (mono synth) and piano (sampled) for levels; per sung part of a piece a choir sampler and a synth; each part behind its own gain node |
| `transport.ts` | Schedules an arrangement (tracks, bars, tempo map) on Tone.js's transport in ticks; count-in, pause and seeking |
| `score.ts` | `ScoreView` for levels: abcjs rendering, ticks → positions, cursor, melody note heads |
| `osmd-score.ts` | `ScoreView` for pieces: the same from OSMD's layout |
| `pitch.ts` | Microphone input and pitch detection |
| `overlay.ts` | The pitch trace drawn into the score's SVG |
| `latency.ts` | Calibration procedures and stored offsets |
| `main.ts`, `piece.ts` | Each page's own controls |

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

## Starting, count-in and seeking

The player keeps its own playback position. Every start (Play, resume after a pause,
restart, or a jump to a bar while playing) is preceded by clicks: one full bar plus
the part of the current bar before the start, so the count begins on a downbeat and a
pickup or a mid-bar resume enters on its own beat. The downbeat click is pitched
higher. Beats are the meter's unit, or dotted quarters in 6/8, 9/8 and 12/8. The
transport is started at the audio time the count-in ends, with the position as its
offset; stopping during the count-in cancels that pending start. The Play button
shows the count.

Tapping a bar moves the position to the bar's start, and counts in from there if it
was playing. A bar reaches from halfway between its first onset and the previous
note to the same point before the next bar. The pitch trace from that bar on is
removed, so the next pass draws on a clean score.

The warm-up (`POST /levels/warmup`) is a fixed sequence of exercises on scale
degrees: the scale up and down, steps out from the tonic and back, the same down
from the upper tonic as a pedal point, the tonic arpeggio, and thirds. It is placed in
the chosen key, mode and voice with the octave centred in the voice's range, and
harmonized like a generated level.

## Choir pieces

The server reads MusicXML files from `$MOCKINGBIRD_PIECES` (by default
`data/external/practice`) and serves two things per piece: playback data (each part's
notes in ticks with ties merged, the bars, the tempo map, which parts are sung and the
closest voice for each, the lyric lines) and the score itself as MusicXML. Finale
writes some syllable joins as a lyric syllable consisting only of a soft hyphen plus an
elision; those are removed before the score is served. Repeats are not expanded, so
playback follows the score as written, like the rendered page. A file without a title
is named after itself.

The page keeps only the chosen lyric line (e.g. German or English) in the MusicXML it
hands to OSMD. Each part is one staff here (a piano's two staves are two parts), so
part indices are staff indices. Mix: your part, the other voices together, and the
piano. Tempo is a percentage of the written tempo map. Your part, its voice, the
voicing and each piece's text choice are remembered in the browser.

Voicing picks how sung parts sound: all as a choir, only your part as a choir and the
others as the synth, the reverse, or all as the synth; it can change during playback;
the accompaniment is always the sampled piano. The default is your part as the synth
over a choir, which keeps your line distinct. The choir is "Choir Aahs" from the
FluidR3 General MIDI soundfont (Frank Wen, CC BY 3.0) as rendered per note by the
midi-js-soundfonts project, one sample every three semitones from C2 to C6. Each file
is a 3.1 s sustained tone that ends abruptly, so on load its tail is crossfaded into
the audio before 0.6 s and the note loops between 0.6 s and 2.9 s for as long as it
lasts. The samples are scaled to a common level. Until they have arrived, sung parts
use the synth.

Tied notes sound once, also where a syllable falls on the tied-over note (an inner
voice holding its pitch while the text moves on); only notes without a tie are
sounded again.

OSMD lays out in staff spaces; a bar's ticks come from its measure's absolute
timestamp, an onset's from the bar plus the staff entry's offset. Positions are read
from the rendered note heads and converted to the SVG's own units, so the overlay does
not depend on OSMD's internal scaling. The score is laid out again when the window's
width changes or another part is chosen.

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
