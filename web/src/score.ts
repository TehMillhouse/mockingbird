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

/** A sung melody note: its tick span and where its note head sits. */
export interface Target {
  index: number;
  start: number;
  end: number;
  pitch: number;
  headY: number;
}

/** The rendered notation, plus a map from level ticks to positions on it.
 *  The map is in ticks, so it stays valid when the tempo changes. */
export class Score {
  svg: SVGSVGElement | null = null;
  /** Distance between adjacent staff positions (line to space), in SVG units. */
  staffStep = 4;
  private onsets: Onset[] = [];
  private targets: Target[] = [];
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

    this.svg = this.paper.querySelector("svg");
    this.cursor = this.svg ? this.svg.appendChild(document.createElementNS(SVG_NS, "line")) : null;
    this.cursor?.classList.add("cursor");
    this.findTargets(level);
    this.moveTo(0);
  }

  /** The melody note sounding at a tick, or null during rests and outside the tune. */
  targetAt(ticks: number): Target | null {
    const i = lastAtOrBefore(this.targets, t => t.start, ticks);
    const t = this.targets[i];
    return t && t.start <= ticks && ticks < t.end ? t : null;
  }

  /** x of a level tick: between two onsets on the same line it moves linearly; on the
   *  last onset of a line it runs across that note. */
  xAt(ticks: number): number {
    const i = this.indexAt(ticks);
    const on = this.onsets[i];
    if (!on) return 0;
    const next = this.onsets[i + 1];
    if (!next) return on.left;
    const frac = (ticks - on.ticks) / (next.ticks - on.ticks);
    const end = next.line === on.line ? next.left : on.right;
    return on.left + (end - on.left) * Math.min(Math.max(frac, 0), 1);
  }

  moveTo(ticks: number): void {
    const i = this.indexAt(ticks);
    if (i < 0 || !this.cursor) return;
    const on = this.onsets[i];
    const x = this.xAt(ticks);
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
    return lastAtOrBefore(this.onsets, o => o.ticks, ticks);
  }

  /** abcjs draws one note or rest group per melody entry, in order, on voice 0. */
  private findTargets(level: Level): void {
    this.targets = [];
    if (!this.svg) return;
    const groups = this.svg.querySelectorAll<SVGGElement>(".abcjs-note.abcjs-v0, .abcjs-rest.abcjs-v0");
    if (groups.length !== level.melody.length) {
      console.warn(`score has ${groups.length} melody elements for ${level.melody.length} notes`);
      return;
    }
    const staff = this.svg.querySelector<SVGGraphicsElement>(".abcjs-staff.abcjs-v0");
    if (staff) this.staffStep = staff.getBBox().height / 8; // five lines span eight steps
    let t = 0;
    level.melody.forEach((n, index) => {
      const head = groups[index].querySelector<SVGGraphicsElement>(".abcjs-notehead");
      if (n.pitch !== null && head) {
        const box = head.getBBox();
        this.targets.push({ index, start: t, end: t + n.duration, pitch: n.pitch, headY: box.y + box.height / 2 });
      }
      t += n.duration;
    });
  }
}

/** Index of the last item whose key is <= value (items sorted by key); 0 if none is,
 *  -1 if there are no items. */
function lastAtOrBefore<T>(items: T[], key: (item: T) => number, value: number): number {
  let lo = 0;
  let hi = items.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (key(items[mid]) <= value) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}
