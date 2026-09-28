import * as Tone from "tone";
import { fetchLevel, type LevelRequest } from "./level";
import { Score } from "./score";
import { Instruments } from "./synth";
import { Player } from "./transport";

const $ = <T extends HTMLElement>(sel: string) => document.querySelector(sel) as T;
const form = $<HTMLFormElement>("#level");
const status = $<HTMLParagraphElement>("#status");
const playButton = $<HTMLButtonElement>("#play");
const sliders = {
  voice: $<HTMLInputElement>("#voice"),
  piano: $<HTMLInputElement>("#piano"),
  tempo: $<HTMLInputElement>("#tempo"),
};

const instruments = new Instruments();
const player = new Player(instruments);
const score = new Score($("#paper"));
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
  await player.toggle();
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
form.addEventListener("submit", e => { e.preventDefault(); newLevel(); });

document.addEventListener("keydown", e => {
  if (e.target instanceof HTMLSelectElement || e.ctrlKey || e.metaKey || e.altKey) return;
  const actions: Record<string, () => void> = {
    " ": togglePlay,
    r: () => { if (loaded) player.restart(); },
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
applyVolume("voice");
applyVolume("piano");
applyTempo();
Tone.loaded().then(() => { status.textContent = "Ready. Press G for a new level."; });
requestAnimationFrame(frame);
