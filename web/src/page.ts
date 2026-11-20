/** What the two pages (the level trainer and the piece practice page) share around
 *  their Practice: element lookup, sliders and keyboard shortcuts. */
import type { Practice } from "./practice";

export const $ = <T extends HTMLElement>(sel: string) => document.querySelector(sel) as T;

/** Move a slider by `delta` (the browser clamps to its range) as if it was dragged. */
export function nudge(slider: HTMLInputElement, delta: number): void {
  slider.value = String(Number(slider.value) + delta);
  slider.dispatchEvent(new Event("input"));
}

/** Show a slider's value in the <output> right after it. */
export function showValue(slider: HTMLInputElement, text: string): void {
  (slider.nextElementSibling as HTMLOutputElement).value = text;
}

/** Keyboard shortcuts: the practice keys (Space, R, M), + and − on the tempo slider, and
 *  the page's own. Ignored while a dialog is open, in a drop-down and with Ctrl, Alt or
 *  Cmd held, so the browser's shortcuts keep working. */
export function bindKeys(practice: Practice, tempo: HTMLInputElement, keys: Record<string, () => void>): void {
  const actions: Record<string, () => void> = {
    ...practice.keys,
    "+": () => nudge(tempo, 5),
    "=": () => nudge(tempo, 5),
    "-": () => nudge(tempo, -5),
    ...keys,
  };
  document.addEventListener("keydown", e => {
    if (practice.busy || e.target instanceof HTMLSelectElement || e.ctrlKey || e.metaKey || e.altKey) return;
    const action = actions[e.key.toLowerCase()];
    if (!action) return;
    e.preventDefault();
    (document.activeElement as HTMLElement | null)?.blur();
    action();
  });
}
