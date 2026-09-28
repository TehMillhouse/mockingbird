import abcjs from "abcjs";
import { barTicks, type Level, TICKS_PER_QUARTER, totalTicks } from "./level";

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

/** A bar: its start tick, the system it is on, and the x of its left edge. */
interface Bar {
  ticks: number;
  line: number;
  left: number;
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
  private bars: Bar[] = [];
  private lines = new Map<number, { top: number; bottom: number }>();
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
    this.findBars(level);
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

  /** The start tick of the bar under a point on the page, or null outside the music.
   *  A bar reaches from halfway between its first onset and the previous note to the
   *  same point before the next bar; the first bar of a system reaches its start. */
  barAt(clientX: number, clientY: number): number | null {
    const ctm = this.svg?.getScreenCTM();
    if (!this.svg || !ctm) return null;
    const p = new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse());
    let line: number | null = null;
    let best = 30; // how far above or below a system a tap still counts, in SVG units
    for (const [n, { top, bottom }] of this.lines) {
      const distance = p.y < top ? top - p.y : p.y > bottom ? p.y - bottom : 0;
      if (distance < best) [line, best] = [n, distance];
    }
    const onLine = this.bars.filter(b => b.line === line);
    if (!onLine.length) return null;
    return (onLine.filter(b => b.left <= p.x).pop() ?? onLine[0]).ticks;
  }

  private findBars(level: Level): void {
    this.lines.clear();
    for (const on of this.onsets) {
      const span = this.lines.get(on.line);
      this.lines.set(on.line, {
        top: Math.min(span?.top ?? Infinity, on.top),
        bottom: Math.max(span?.bottom ?? -Infinity, on.top + on.height),
      });
    }
    const bar = barTicks(level.meter);
    const starts = new Set<number>([0]);
    for (let t = level.pickup_ticks || bar; t < totalTicks(level); t += bar) starts.add(t);
    this.bars = [];
    this.onsets.forEach((on, i) => {
      if (!starts.has(on.ticks)) return;
      const prev = this.onsets[i - 1];
      const left = prev && prev.line === on.line ? (prev.right + on.left) / 2 : -Infinity;
      this.bars.push({ ticks: on.ticks, line: on.line, left });
    });
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
