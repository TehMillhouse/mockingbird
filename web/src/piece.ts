import * as Tone from "tone";
import { OsmdScore } from "./osmd-score";
import { Practice } from "./practice";
import { PartInstruments, type Voicing } from "./synth";

/** Mirrors mockingbird/pieces.py. Times are ticks, 24 per quarter note. */
interface Piece {
  id: string;
  title: string;
  composer: string | null;
  parts: { index: number; name: string; sung: boolean; voice: string | null;
    events: { start: number; duration: number; pitches: number[] }[] }[];
  measures: { number: string; start: number; duration: number; meter: string }[];
  tempos: { start: number; bpm: number }[];
  verses: { number: string; incipit: string }[];
}

const $ = <T extends HTMLElement>(sel: string) => document.querySelector(sel) as T;
const status = $<HTMLParagraphElement>("#status");
const playButton = $<HTMLButtonElement>("#play");
const pieceSelect = $<HTMLSelectElement>("#piece");
const partSelect = $<HTMLSelectElement>("#part");
const verseSelect = $<HTMLSelectElement>("#verse");
const voicingSelect = $<HTMLSelectElement>("#voicing");
const sliders = {
  mine: $<HTMLInputElement>("#mine"),
  choir: $<HTMLInputElement>("#choir"),
  piano: $<HTMLInputElement>("#piano"),
  tempo: $<HTMLInputElement>("#tempo"),
};

const instruments = new PartInstruments();
const practice = new Practice(status, playButton, $("#paper"), $("#devices"));
const score = new OsmdScore($("#paper"));
let piece: Piece | null = null;
let musicxml = "";

const remember = (key: string, value: string) => {
  try { localStorage.setItem(`mockingbird.${key}`, value); } catch { /* storage unavailable */ }
};
const recall = (key: string) => {
  try { return localStorage.getItem(`mockingbird.${key}`); } catch { return null; }
};

async function loadPieceList(): Promise<void> {
  const list: { id: string; title: string; composer: string | null }[] = await (await fetch("pieces")).json();
  pieceSelect.replaceChildren(...list.map(p => new Option(p.composer ? `${p.title} (${p.composer})` : p.title, p.id)));
  if (!list.length) {
    status.textContent = "No pieces on the server yet.";
    return;
  }
  const saved = recall("piece");
  if (saved && list.some(p => p.id === saved)) pieceSelect.value = saved;
  await loadPiece(pieceSelect.value);
}

async function loadPiece(id: string): Promise<void> {
  status.textContent = "Loading…";
  practice.player.stop();
  const [data, xml] = await Promise.all([
    fetch(`pieces/${encodeURIComponent(id)}`).then(r => r.json() as Promise<Piece>),
    fetch(`pieces/${encodeURIComponent(id)}/musicxml`).then(r => r.text()),
  ]);
  piece = data;
  musicxml = xml;
  remember("piece", id);

  const sung = piece.parts.filter(p => p.sung);
  partSelect.replaceChildren(...sung.map(p => new Option(p.name, String(p.index))));
  // the same part name if this piece has it (e.g. "Tenore II"), else the same voice
  const name = recall("part-name");
  const voice = recall("voice");
  const preferred = sung.find(p => p.name === name) ?? sung.find(p => p.voice === voice) ?? sung[0];
  if (preferred) partSelect.value = String(preferred.index);

  verseSelect.replaceChildren(...piece.verses.map(v => new Option(v.incipit, v.number)));
  $("#verse-choice").hidden = piece.verses.length < 2;
  const verse = recall(`verse.${id}`);
  if (verse && piece.verses.some(v => v.number === verse)) verseSelect.value = verse;

  instruments.setup(piece.parts.map(p => p.sung));
  const last = piece.measures[piece.measures.length - 1];
  practice.player.load({
    length: last ? last.start + last.duration : 0,
    bars: piece.measures,
    tempos: piece.tempos,
    tracks: piece.parts.map(p => ({ events: p.events, play: instruments.play(p.index), articulate: p.sung })),
    silence: () => instruments.silence(),
  });
  applyMix();
  applyTempo();
  await render();
  playButton.disabled = false;
  status.textContent = `${piece.title}${piece.composer ? ` · ${piece.composer}` : ""}`;
}

/** The score with only the chosen lyric line, so the other language does not crowd it. */
function withVerse(xml: string, verse: string): string {
  if (!piece || piece.verses.length < 2) return xml;
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  doc.querySelectorAll("lyric").forEach(l => {
    if ((l.getAttribute("number") ?? "1") !== verse) l.remove();
  });
  return new XMLSerializer().serializeToString(doc);
}

async function render(): Promise<void> {
  if (!piece) return;
  await score.render(withVerse(musicxml, verseSelect.value), [myPart()]);
  practice.attach(score);
}

/** The index of the part being sung; parts map one to one onto OSMD's staves here,
 *  because every part has a single staff (a piano's two staves are two parts). */
function myPart(): number {
  return Number(partSelect.value);
}

function applyMix(): void {
  const volume = (s: HTMLInputElement) => Number(s.value) / 100;
  instruments.mix(myPart(), { mine: volume(sliders.mine), choir: volume(sliders.choir), piano: volume(sliders.piano) });
  for (const s of [sliders.mine, sliders.choir, sliders.piano]) {
    (s.nextElementSibling as HTMLOutputElement).value = `${s.value}%`;
  }
}

function applyTempo(): void {
  practice.player.tempoScale = Number(sliders.tempo.value) / 100;
  const bpm = piece ? Math.round((piece.tempos[0]?.bpm ?? 100) * Number(sliders.tempo.value) / 100) : null;
  (sliders.tempo.nextElementSibling as HTMLOutputElement).value =
    `${sliders.tempo.value}%${bpm !== null ? ` (♩ ${bpm})` : ""}`;
}

function nudge(slider: HTMLInputElement, delta: number): void {
  slider.value = String(Number(slider.value) + delta); // the browser clamps to min/max
  slider.dispatchEvent(new Event("input"));
}

pieceSelect.addEventListener("change", () => loadPiece(pieceSelect.value));
partSelect.addEventListener("change", () => {
  const part = piece?.parts[myPart()];
  if (part?.voice) remember("voice", part.voice);
  if (part) remember("part-name", part.name);
  applyMix();
  score.layout([myPart()]);
  practice.attach(score);
});
verseSelect.addEventListener("change", () => {
  if (piece) remember(`verse.${piece.id}`, verseSelect.value);
  render();
});
for (const s of [sliders.mine, sliders.choir, sliders.piano]) s.addEventListener("input", applyMix);

const savedVoicing = recall("voicing");
if (savedVoicing && [...voicingSelect.options].some(o => o.value === savedVoicing)) voicingSelect.value = savedVoicing;
instruments.voicing = voicingSelect.value as Voicing;
voicingSelect.addEventListener("change", () => {
  instruments.voicing = voicingSelect.value as Voicing;
  remember("voicing", voicingSelect.value);
});
sliders.tempo.addEventListener("input", applyTempo);

let resizeTimer: number | undefined;
let laidOutWidth = window.innerWidth;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    if (!piece || window.innerWidth === laidOutWidth) return;
    laidOutWidth = window.innerWidth;
    score.layout([myPart()]);
    practice.attach(score);
  }, 250);
});

document.addEventListener("keydown", e => {
  if (practice.busy || e.target instanceof HTMLSelectElement || e.ctrlKey || e.metaKey || e.altKey) return;
  const actions: Record<string, () => void> = {
    ...practice.keys,
    "+": () => nudge(sliders.tempo, 5),
    "=": () => nudge(sliders.tempo, 5),
    "-": () => nudge(sliders.tempo, -5),
  };
  const action = actions[e.key.toLowerCase()];
  if (!action) return;
  e.preventDefault();
  (document.activeElement as HTMLElement | null)?.blur();
  action();
});

loadPieceList().catch(e => { status.textContent = `Could not load pieces: ${e instanceof Error ? e.message : e}`; });
Tone.loaded();

// development builds only: the live objects, for checking behaviour from the console
if (import.meta.env.DEV) Object.assign(window, { mockingbird: { score, practice } });
