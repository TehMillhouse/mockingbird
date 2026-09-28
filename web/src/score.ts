import abcjs from "abcjs";
import { type Level, TICKS_PER_QUARTER } from "./level";

const SVG_NS = "http://www.w3.org/2000/svg";

/** A note or rest onset on the rendered score, in level ticks and SVG coordinates. */
interface Onset {
  ticks: number;
  line: number;
  left: number;
  right: number;
  top: number;
  height: number;
  elements: Element[];
}

/** The rendered notation, plus a map from level ticks to positions on it.
 *  The map is in ticks, so it stays valid when the tempo changes. */
export class Score {
  private onsets: Onset[] = [];
  private cursor: SVGLineElement | null = null;
  private current = -1;

  constructor(private readonly paper: HTMLElement) {}

  render(abc: string, level: Level): void {
    const visual = abcjs.renderAbc(this.paper, abc, { responsive: "resize", add_classes: true })[0];
    // abcjs times the tune at the ABC's own Q: header, which is the level's tempo
    const ticksPerMs = (level.tempo_bpm / 60000) * TICKS_PER_QUARTER;
    const timing = new abcjs.TimingCallbacks(visual, {});
    const byTicks = new Map<number, Onset>();
    for (const ev of timing.noteTimings) {
      if (ev.type !== "event" || ev.left === undefined) continue;
      const ticks = Math.round(ev.milliseconds * ticksPerMs);
      const elements = (ev.elements ?? []).flat() as unknown as Element[];
      const known = byTicks.get(ticks);
      if (known) {
        known.elements.push(...elements);
        continue;
      }
      byTicks.set(ticks, {
        ticks,
        line: ev.line ?? 0,
        left: ev.left,
        right: ev.left + (ev.width ?? 0),
        top: ev.top ?? 0,
        height: ev.height ?? 0,
        elements,
      });
    }
    this.onsets = [...byTicks.values()].sort((a, b) => a.ticks - b.ticks);
    this.current = -1;

    const svg = this.paper.querySelector("svg");
    this.cursor = svg ? (svg.appendChild(document.createElementNS(SVG_NS, "line")) as SVGLineElement) : null;
    this.cursor?.classList.add("cursor");
    this.moveTo(0);
  }

  /** Put the cursor at a level tick: between two onsets on the same line it moves
   *  linearly; on the last onset of a line it runs across that note. */
  moveTo(ticks: number): void {
    const i = this.indexAt(ticks);
    if (i < 0 || !this.cursor) return;
    const on = this.onsets[i];
    const next = this.onsets[i + 1];
    let x = on.left;
    if (next) {
      const frac = (ticks - on.ticks) / (next.ticks - on.ticks);
      const end = next.line === on.line ? next.left : on.right;
      x = on.left + (end - on.left) * Math.min(frac, 1);
    }
    this.cursor.setAttribute("x1", String(x));
    this.cursor.setAttribute("x2", String(x));
    this.cursor.setAttribute("y1", String(on.top));
    this.cursor.setAttribute("y2", String(on.top + on.height));
    if (i !== this.current) {
      this.onsets[this.current]?.elements.forEach(el => el.classList.remove("playing"));
      on.elements.forEach(el => el.classList.add("playing"));
      this.current = i;
    }
  }

  private indexAt(ticks: number): number {
    let lo = 0;
    let hi = this.onsets.length - 1;
    if (hi < 0) return -1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (this.onsets[mid].ticks <= ticks) lo = mid;
      else hi = mid - 1;
    }
    return lo;
  }
}
