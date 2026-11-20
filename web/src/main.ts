import * as Tone from "tone";
import { fetchLevel, type Level, levelBars, type LevelRequest, melodyEvents, totalTicks } from "./level";
import { $, bindKeys, nudge, showValue } from "./page";
import { Practice } from "./practice";
import { Score } from "./score";
import { recallJson, rememberJson } from "./storage";
import { Instruments } from "./synth";

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

const FORM_KEY = "level-form";

function restoreForm(): void {
  for (const [name, value] of Object.entries(recallJson<Record<string, string>>(FORM_KEY))) {
    const field = form.elements.namedItem(name) as HTMLSelectElement | null;
    if (field && typeof value === "string") field.value = value;
  }
}

function readForm(): LevelRequest {
  const data = Object.fromEntries(new FormData(form)) as Record<string, string>;
  rememberJson(FORM_KEY, data);
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
  showValue(slider, `${slider.value}%`);
}

/** The slider is in beats per minute; the player scales the level's written tempo. */
function applyTempo(): void {
  if (level) practice.player.tempoScale = Number(sliders.tempo.value) / level.tempo_bpm;
  showValue(sliders.tempo, sliders.tempo.value);
}

sliders.voice.addEventListener("input", () => applyVolume("voice"));
sliders.piano.addEventListener("input", () => applyVolume("piano"));
sliders.tempo.addEventListener("input", () => { tempoTouched = true; applyTempo(); });
$("#warmup").addEventListener("click", () => newLevel("warmup"));
form.addEventListener("submit", e => { e.preventDefault(); newLevel(); });

bindKeys(practice, sliders.tempo, {
  g: () => newLevel(),
  w: () => newLevel("warmup"),
  "[": () => nudge(sliders.voice, -10),
  "]": () => nudge(sliders.voice, 10),
  ";": () => nudge(sliders.piano, -10),
  "'": () => nudge(sliders.piano, 10),
});

restoreForm();
applyVolume("voice");
applyVolume("piano");
applyTempo();
Tone.loaded().then(() => { status.textContent = "Ready. Press G for a new level."; });
