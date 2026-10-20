import * as Tone from "tone";
import { fetchLevel, type Level, levelBars, type LevelRequest, melodyEvents, totalTicks } from "./level";
import { Practice } from "./practice";
import { Score } from "./score";
import { Instruments } from "./synth";

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
const practice = new Practice(status, playButton, $("#paper"), $("#devices"));
const score = new Score($("#paper"));
let level: Level | null = null;
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

async function newLevel(kind: "generated" | "warmup" = "generated"): Promise<void> {
  status.textContent = "Generating…";
  try {
    const fetched = await fetchLevel(readForm(), kind);
    level = fetched.level;
    if (!tempoTouched) sliders.tempo.value = String(level.tempo_bpm);
    practice.player.load({
      length: totalTicks(level),
      bars: levelBars(level),
      tempos: [{ start: 0, bpm: level.tempo_bpm }],
      tracks: [
        {
          events: melodyEvents(level),
          play: (notes, seconds, time) => instruments.voice.triggerAttackRelease(notes[0], seconds, time),
          articulate: true,
        },
        {
          events: level.accompaniment,
          play: (notes, seconds, time) => instruments.piano.triggerAttackRelease(notes, seconds, time, 0.6),
        },
      ],
      silence: () => instruments.silence(),
    });
    applyTempo();
    score.render(fetched.abc, level);
    practice.attach(score);
    playButton.disabled = false;
    status.textContent = kind === "warmup"
      ? "Warm-up: scale, pedal-point runs up and down, arpeggio and thirds."
      : `Level ${level.id} · difficulty score ${level.difficulty_score?.toFixed(1) ?? "?"}`;
  } catch (e) {
    status.textContent = `Could not generate a level: ${e instanceof Error ? e.message : e}`;
  }
}

function applyVolume(which: "voice" | "piano"): void {
  const slider = sliders[which];
  instruments.setVolume(which, Number(slider.value) / 100);
  (slider.nextElementSibling as HTMLOutputElement).value = `${slider.value}%`;
}

/** The slider is in beats per minute; the player scales the level's written tempo. */
function applyTempo(): void {
  if (level) practice.player.tempoScale = Number(sliders.tempo.value) / level.tempo_bpm;
  (sliders.tempo.nextElementSibling as HTMLOutputElement).value = `${sliders.tempo.value}`;
}

function nudge(slider: HTMLInputElement, delta: number): void {
  slider.value = String(Number(slider.value) + delta); // the browser clamps to min/max
  slider.dispatchEvent(new Event("input"));
}

sliders.voice.addEventListener("input", () => applyVolume("voice"));
sliders.piano.addEventListener("input", () => applyVolume("piano"));
sliders.tempo.addEventListener("input", () => { tempoTouched = true; applyTempo(); });
$("#warmup").addEventListener("click", () => newLevel("warmup"));
form.addEventListener("submit", e => { e.preventDefault(); newLevel(); });

document.addEventListener("keydown", e => {
  if (practice.busy || e.target instanceof HTMLSelectElement || e.ctrlKey || e.metaKey || e.altKey) return;
  const actions: Record<string, () => void> = {
    ...practice.keys,
    "+": () => nudge(sliders.tempo, 5),
    "=": () => nudge(sliders.tempo, 5),
    "-": () => nudge(sliders.tempo, -5),
    g: () => newLevel(),
    w: () => newLevel("warmup"),
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
