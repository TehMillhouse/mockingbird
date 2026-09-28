import * as Tone from "tone";
import { audioContext } from "./audio";
import type { Mic } from "./pitch";
import { makeClicker } from "./synth";

/** Seconds between calibration clicks or flashes. */
const INTERVAL = 0.6;
const LEAD_IN = 4;
const COUNTED = 12;
const MIN_MATCHES = 6;
/** A tap belongs to the stimulus it is closest to, if it is within this. */
const TAP_WINDOW = 0.25;

/** Calibrated offsets in seconds, keyed by device labels, since each device has its
 *  own latency. */
export class LatencyStore {
  private static readonly KEY = "mockingbird.latency";

  /** A − V: how much later a sound is perceived than a frame drawn at the moment it
   *  was scheduled. */
  av(output: string): number | undefined {
    return this.load()[`av|${output}`];
  }

  /** A + I: from scheduling a sound to capturing a response to it at the mic. */
  roundTrip(output: string, input: string): number | undefined {
    return this.load()[`rt|${output}|${input}`];
  }

  saveAv(output: string, seconds: number): void {
    this.save(`av|${output}`, seconds);
  }

  saveRoundTrip(output: string, input: string, seconds: number): void {
    this.save(`rt|${output}|${input}`, seconds);
  }

  private load(): Record<string, number> {
    try {
      return JSON.parse(localStorage.getItem(LatencyStore.KEY) ?? "{}");
    } catch {
      return {};
    }
  }

  private save(key: string, seconds: number): void {
    try {
      localStorage.setItem(LatencyStore.KEY, JSON.stringify({ ...this.load(), [key]: seconds }));
    } catch {
      // storage unavailable: the calibration lasts for this visit only
    }
  }
}

export type Progress = (message: string) => void;

let clicker: Tone.Synth | null = null;

/** Schedule the click track; returns the AudioContext time of each click. The count-in
 *  clicks are pitched lower. */
function scheduleClicks(): number[] {
  clicker ??= makeClicker();
  const start = audioContext.currentTime + 0.6;
  const times = Array.from({ length: LEAD_IN + COUNTED }, (_, i) => start + i * INTERVAL);
  times.forEach((t, i) => clicker!.triggerAttackRelease(i < LEAD_IN ? "G5" : "C6", 0.02, t));
  return times;
}

const sleep = (ms: number) => new Promise(r => setTimeout(r, Math.max(0, ms)));

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Median delay of responses after the counted stimuli. Each stimulus takes its
 *  nearest response between `before` seconds earlier and `after` seconds later. */
function matchedDelay(stimuli: number[], responses: number[], before: number, after: number): number {
  const delays = stimuli.slice(LEAD_IN).flatMap(s => {
    const near = responses.filter(r => r >= s - before && r <= s + after);
    if (!near.length) return [];
    return [near.reduce((a, b) => (Math.abs(a - s) <= Math.abs(b - s) ? a : b)) - s];
  });
  if (delays.length < MIN_MATCHES) {
    throw new Error(`only ${delays.length} of ${COUNTED} were caught, try again`);
  }
  return median(delays);
}

/** Tap times (performance clock, seconds) from Space or presses on `pad`, until the
 *  performance clock reaches `untilMs`. */
async function collectTaps(pad: HTMLElement, untilMs: number): Promise<number[]> {
  const taps: number[] = [];
  const onKey = (e: KeyboardEvent) => {
    if (e.key !== " ") return;
    e.preventDefault();
    e.stopPropagation();
    if (!e.repeat) taps.push(e.timeStamp / 1000);
  };
  const onPointer = (e: PointerEvent) => taps.push(e.timeStamp / 1000);
  window.addEventListener("keydown", onKey, true);
  pad.addEventListener("pointerdown", onPointer);
  await sleep(untilMs - performance.now());
  window.removeEventListener("keydown", onKey, true);
  pad.removeEventListener("pointerdown", onPointer);
  return taps;
}

/** A − V from two tap runs: along with clicks (A plus tap latency), then along with
 *  flashes of `pad` (V plus tap latency). The tap latency cancels in the difference. */
export async function calibrateAv(pad: HTMLElement, progress: Progress): Promise<number> {
  await Tone.start();

  progress("Tap Space with each click. The first four count in.");
  const clicks = scheduleClicks();
  // the same mapping from the AudioContext clock the cursor uses: "now" on both
  const perfOffset = performance.now() / 1000 - audioContext.currentTime;
  const clickTimes = clicks.map(t => t + perfOffset);
  const audioTaps = await collectTaps(pad, (clickTimes[clickTimes.length - 1] + INTERVAL) * 1000);
  const audio = matchedDelay(clickTimes, audioTaps, TAP_WINDOW, TAP_WINDOW);

  progress("Now tap Space with each flash. The first four count in.");
  await sleep(1000);
  const total = LEAD_IN + COUNTED;
  const first = performance.now() + 600;
  const shown: number[] = [];
  const flash = (now: number) => {
    if (now >= first + shown.length * INTERVAL * 1000) {
      pad.classList.toggle("count-in", shown.length < LEAD_IN);
      pad.classList.add("lit");
      shown.push(now / 1000); // the frame this callback produces is the stimulus
      setTimeout(() => pad.classList.remove("lit"), 80);
    }
    if (shown.length < total) requestAnimationFrame(flash);
  };
  requestAnimationFrame(flash);
  const visualTaps = await collectTaps(pad, first + total * INTERVAL * 1000);
  const visual = matchedDelay(shown, visualTaps, TAP_WINDOW, TAP_WINDOW);

  return audio - visual;
}

/** A + I: clicks are played and claps detected at the mic, both on the AudioContext
 *  clock. Over speakers the mic hears the clicks themselves, which works as well. */
export async function calibrateRoundTrip(mic: Mic, progress: Progress): Promise<number> {
  await Tone.start();
  progress("Clap with each click, close to the microphone. The first four count in.");
  const clicks = scheduleClicks();
  const sr = audioContext.sampleRate;
  const onsets: number[] = [];
  let noise = 0;
  let lastEnd = 0;
  let lastOnset = -Infinity;
  const stopAt = clicks[clicks.length - 1] + INTERVAL;
  while (audioContext.currentTime < stopAt) {
    const { data, end } = mic.samples();
    // only the samples that arrived since the previous look
    const fresh = lastEnd ? Math.min(data.length, Math.round((end - lastEnd) * sr)) : data.length;
    for (let j = data.length - fresh; j < data.length; j++) {
      const t = end - (data.length - j) / sr;
      const amp = Math.abs(data[j]);
      if (t < clicks[0] - 0.1) {
        noise = Math.max(noise, amp); // the quiet before the first click sets the floor
      } else if (amp > Math.max(0.02, noise * 4) && t - lastOnset > 0.2) {
        onsets.push(t);
        lastOnset = t;
      }
    }
    lastEnd = end;
    await sleep(10);
  }
  return matchedDelay(clicks, onsets, 0.15, 0.45);
}
