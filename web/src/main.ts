import * as Tone from "tone";
import { audioContext, canChooseOutput, setOutputDevice } from "./audio";
import { DevicePicker } from "./devices";
import { fetchLevel, type LevelRequest } from "./level";
import { Trace } from "./overlay";
import { Mic } from "./pitch";
import { Score } from "./score";
import { Instruments } from "./synth";
import { Player } from "./transport";

const $ = <T extends HTMLElement>(sel: string) => document.querySelector(sel) as T;
const form = $<HTMLFormElement>("#level");
const status = $<HTMLParagraphElement>("#status");
const playButton = $<HTMLButtonElement>("#play");
const micButton = $<HTMLButtonElement>("#mic");
const readout = $<HTMLOutputElement>("#sung");
const inputLevel = $<HTMLMeterElement>("#input-level");
const inputPicker = new DevicePicker($("#input"), "audioinput", "mockingbird.input-device");
const outputPicker = new DevicePicker($("#output"), "audiooutput", "mockingbird.output-device");
const sliders = {
  voice: $<HTMLInputElement>("#voice"),
  piano: $<HTMLInputElement>("#piano"),
  tempo: $<HTMLInputElement>("#tempo"),
};

const instruments = new Instruments();
const player = new Player(instruments);
const score = new Score($("#paper"));
const trace = new Trace();
let mic: Mic | null = null;
let loaded = false;
let tempoTouched = false;

const FORM_KEY = "mockingbird.level-form";

function restoreForm(): void {
  try {
    const saved = JSON.parse(localStorage.getItem(FORM_KEY) ?? "{}") as Record<string, string>;
    for (const [name, value] of Object.entries(saved)) {
      const field = form.elements.namedItem(name) as HTMLSelectElement | null;
      if (field) field.value = value;
    }
  } catch {
    // storage unavailable: keep the defaults
  }
}

function readForm(): LevelRequest {
  const data = Object.fromEntries(new FormData(form)) as Record<string, string>;
  try {
    localStorage.setItem(FORM_KEY, JSON.stringify(data));
  } catch {
    // storage unavailable: nothing to remember
  }
  return { tonic: data.tonic, mode: data.mode, voice: data.voice, difficulty: Number(data.difficulty) };
}

async function newLevel(): Promise<void> {
  status.textContent = "Generating…";
  try {
    const { level, abc } = await fetchLevel(readForm());
    if (!tempoTouched) sliders.tempo.value = String(level.tempo_bpm);
    applyTempo();
    player.load(level);
    score.render(abc, level);
    if (score.svg) trace.attach(score.svg);
    loaded = true;
    playButton.disabled = false;
    status.textContent = `Level ${level.id} · difficulty score ${level.difficulty_score?.toFixed(1) ?? "?"}`;
  } catch (e) {
    status.textContent = `Could not generate a level: ${e instanceof Error ? e.message : e}`;
  }
}

function applyVolume(which: "voice" | "piano"): void {
  const slider = sliders[which];
  instruments.setVolume(which, Number(slider.value) / 100);
  (slider.nextElementSibling as HTMLOutputElement).value = `${slider.value}%`;
}

function applyTempo(): void {
  player.bpm = Number(sliders.tempo.value);
  (sliders.tempo.nextElementSibling as HTMLOutputElement).value = `${sliders.tempo.value}`;
}

function nudge(slider: HTMLInputElement, delta: number): void {
  slider.value = String(Number(slider.value) + delta); // the browser clamps to min/max
  slider.dispatchEvent(new Event("input"));
}

async function togglePlay(): Promise<void> {
  if (!loaded) return;
  if (!player.playing && player.audibleTicks() === 0) trace.clear();
  await player.toggle();
}

async function restart(): Promise<void> {
  if (!loaded) return;
  trace.clear();
  await player.restart();
}

async function openMic(): Promise<void> {
  mic?.close();
  mic = null;
  try {
    await Tone.start();
    mic = await Mic.open(audioContext, inputPicker.value);
    status.textContent = `Listening on ${mic.label}. Use headphones so the piano stays out of the mic.`;
    // device names are only readable once permission is granted
    await Promise.all([inputPicker.refresh(), outputPicker.refresh()]);
  } catch (e) {
    const reason = e instanceof DOMException && e.name === "NotAllowedError"
      ? "permission denied; allow the microphone for this page in the browser's site settings"
      : e instanceof Error ? `${e.name}: ${e.message}` : String(e);
    status.textContent = `Could not open the microphone (${reason}).`;
  }
  showMicState();
}

function closeMic(): void {
  mic?.close();
  mic = null;
  showMicState();
}

function showMicState(): void {
  micButton.textContent = mic ? "Mic on" : "Mic off";
  micButton.classList.toggle("on", mic !== null);
  inputLevel.hidden = mic === null;
  if (!mic) readout.value = "";
}

async function toggleMic(): Promise<void> {
  if (mic) closeMic();
  else await openMic();
}

async function chooseOutput(): Promise<void> {
  try {
    await setOutputDevice(outputPicker.value);
  } catch (e) {
    status.textContent = `Could not switch output: ${e instanceof Error ? e.message : e}`;
  }
}

const NOTE_NAMES = ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"];

function showSung(midi: number | null): void {
  if (midi === null) {
    readout.value = "–";
    return;
  }
  const nearest = Math.round(midi);
  const cents = Math.round((midi - nearest) * 100);
  const name = NOTE_NAMES[((nearest % 12) + 12) % 12] + (Math.floor(nearest / 12) - 1);
  readout.value = `${name} ${cents >= 0 ? "+" : "−"}${Math.abs(cents)}¢`;
}

/** Place the sung pitch against the note that was sounding when it was sung. The
 *  singer follows what they hear, so its capture time is mapped back through both
 *  the input and the output latency. */
function traceSung(sung: Mic, midi: number, time: number): void {
  const ticks = player.heardTicksAt(time - sung.reportedLatency);
  const target = score.targetAt(ticks);
  if (!target) return;
  const off = midi - target.pitch;
  const folded = off - 12 * Math.round(off / 12); // octave errors don't count
  const y = target.headY - folded * (score.staffStep / 2);
  trace.add(ticks, target.index, score.xAt(ticks), y, folded * 100);
}

// Pitch is sampled on a fixed clock, independent of the display's frame rate.
const PITCH_INTERVAL_MS = 10;

function listen(): void {
  if (!mic) return;
  const { db, pitch } = mic.read();
  inputLevel.value = db;
  showSung(pitch?.midi ?? null);
  if (pitch && loaded && player.playing) traceSung(mic, pitch.midi, pitch.time);
}

function frame(): void {
  if (loaded) score.moveTo(player.audibleTicks());
  playButton.textContent = player.playing ? "Pause" : "Play";
  requestAnimationFrame(frame);
}

sliders.voice.addEventListener("input", () => applyVolume("voice"));
sliders.piano.addEventListener("input", () => applyVolume("piano"));
sliders.tempo.addEventListener("input", () => { tempoTouched = true; applyTempo(); });
playButton.addEventListener("click", togglePlay);
micButton.addEventListener("click", toggleMic);
$("#input").addEventListener("change", () => { if (mic) openMic(); });
$("#output").addEventListener("change", chooseOutput);
navigator.mediaDevices.addEventListener("devicechange", () => {
  inputPicker.refresh();
  outputPicker.refresh();
});
form.addEventListener("submit", e => { e.preventDefault(); newLevel(); });

document.addEventListener("keydown", e => {
  if (e.target instanceof HTMLSelectElement || e.ctrlKey || e.metaKey || e.altKey) return;
  const actions: Record<string, () => void> = {
    " ": togglePlay,
    r: restart,
    m: toggleMic,
    "+": () => nudge(sliders.tempo, 5),
    "=": () => nudge(sliders.tempo, 5),
    "-": () => nudge(sliders.tempo, -5),
    g: newLevel,
    "[": () => nudge(sliders.voice, -10),
    "]": () => nudge(sliders.voice, 10),
    ";": () => nudge(sliders.piano, -10),
    "'": () => nudge(sliders.piano, 10),
  };
  const action = actions[e.key.toLowerCase()];
  if (!action) return;
  e.preventDefault();
  (document.activeElement as HTMLElement | null)?.blur();
  action();
});

restoreForm();
if (!canChooseOutput) $("#output-choice").hidden = true;
Promise.all([inputPicker.refresh(), outputPicker.refresh()]).then(() => {
  if (outputPicker.value) chooseOutput();
});
applyVolume("voice");
applyVolume("piano");
applyTempo();
Tone.loaded().then(() => { status.textContent = "Ready. Press G for a new level."; });
requestAnimationFrame(frame);
setInterval(listen, PITCH_INTERVAL_MS);
