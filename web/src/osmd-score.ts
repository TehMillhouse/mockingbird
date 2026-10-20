import { OpenSheetMusicDisplay } from "opensheetmusicdisplay";
import { TICKS_PER_QUARTER } from "./level";
import type { ScoreView, Target } from "./practice";

const SVG_NS = "http://www.w3.org/2000/svg";
const TICKS_PER_WHOLE = 4 * TICKS_PER_QUARTER;

/** A moment some note starts at, on one system, in SVG units. */
interface Onset {
  ticks: number;
  system: number;
  x: number;
  /** Where the cursor is by the next onset: its x, or the end of the system. */
  end: number;
  heads: Element[];
}

interface Bar {
  ticks: number;
  system: number;
  left: number;
  right: number;
}

// The parts of OSMD's graphical model used here; its typings do not export them all.
interface GNote {
  sourceNote: { halfTone: number; Length: { RealValue: number }; isRest(): boolean; IsCueNote: boolean; IsGraceNote?: boolean };
  getNoteheadSVGs?(): Element[];
}
interface GMeasure {
  parentSourceMeasure: { AbsoluteTimestamp: { RealValue: number } };
  staffEntries: { relInMeasureTimestamp: { RealValue: number }; graphicalVoiceEntries: { notes: GNote[] }[] }[];
  ParentStaffLine?: { ParentMusicSystem: object; PositionAndShape: Box };
  PositionAndShape: Box;
}
interface Box {
  AbsolutePosition: { x: number; y: number };
  BorderLeft: number;
  BorderRight: number;
}

/** A MusicXML score rendered by OpenSheetMusicDisplay, with ticks mapped onto it. */
export class OsmdScore implements ScoreView {
  svg: SVGSVGElement | null = null;
  staffStep = 5;
  private readonly osmd: OpenSheetMusicDisplay;
  private onsets: Onset[] = [];
  private bars: Bar[] = [];
  private systems = new Map<number, { top: number; bottom: number }>();
  private targets: Target[] = [];
  private cursor: SVGLineElement | null = null;
  private current = -1;
  private staves: number[] = [];

  constructor(private readonly container: HTMLElement) {
    this.osmd = new OpenSheetMusicDisplay(container, {
      autoResize: false,
      backend: "svg",
      drawTitle: false,
      drawComposer: false,
      drawCredits: false,
      drawPartNames: true,
    });
  }

  /** Render a score; `staves` are the staff indices of the part being sung. */
  async render(xml: string, staves: number[]): Promise<void> {
    await this.osmd.load(xml);
    this.layout(staves);
  }

  /** Lay the loaded score out again, e.g. for a new width or another sung part. */
  layout(staves: number[]): void {
    this.staves = staves;
    this.osmd.render();
    this.build();
  }

  private build(): void {
    this.svg = this.container.querySelector("svg");
    this.onsets = [];
    this.bars = [];
    this.systems.clear();
    this.targets = [];
    this.current = -1;
    if (!this.svg) return;
    const ctm = this.svg.getScreenCTM()?.inverse();
    if (!ctm) return;
    // OSMD lays out in units of a staff space; on screen that is 10 px at zoom 1
    const svgRect = this.svg.getBoundingClientRect();
    const toUser = (cx: number, cy: number) => new DOMPoint(cx, cy).matrixTransform(ctm);
    const unit = 10 * this.osmd.Zoom;
    const origin = toUser(svgRect.left, svgRect.top);
    const scale = toUser(svgRect.left + unit, svgRect.top).x - origin.x;
    const ux = (u: number) => origin.x + u * scale;
    const uy = (u: number) => origin.y + u * scale;
    this.staffStep = scale / 2;

    const systemIds = new Map<object, number>();
    const byTicks = new Map<number, Onset>();
    const measureList = this.osmd.GraphicSheet.MeasureList as unknown as (GMeasure | undefined)[][];
    for (const row of measureList) {
      for (const [staff, gm] of row.entries()) {
        if (!gm?.ParentStaffLine) continue;
        const sysObj = gm.ParentStaffLine.ParentMusicSystem;
        if (!systemIds.has(sysObj)) systemIds.set(sysObj, systemIds.size);
        const system = systemIds.get(sysObj)!;
        const lineTop = uy(gm.ParentStaffLine.PositionAndShape.AbsolutePosition.y);
        const span = this.systems.get(system);
        this.systems.set(system, {
          top: Math.min(span?.top ?? Infinity, lineTop),
          bottom: Math.max(span?.bottom ?? -Infinity, lineTop + 4 * scale),
        });
        const start = Math.round(gm.parentSourceMeasure.AbsoluteTimestamp.RealValue * TICKS_PER_WHOLE);
        if (staff === 0) {
          const box = gm.PositionAndShape;
          this.bars.push({
            ticks: start, system,
            left: ux(box.AbsolutePosition.x + box.BorderLeft),
            right: ux(box.AbsolutePosition.x + box.BorderRight),
          });
        }
        for (const entry of gm.staffEntries) {
          const ticks = start + Math.round(entry.relInMeasureTimestamp.RealValue * TICKS_PER_WHOLE);
          for (const note of entry.graphicalVoiceEntries.flatMap(v => v.notes)) {
            const heads = note.getNoteheadSVGs?.() ?? [];
            if (!heads.length) continue;
            const r = heads[0].getBoundingClientRect();
            const head = toUser(r.left, r.top + r.height / 2);
            const onset = byTicks.get(ticks);
            if (onset) {
              onset.heads.push(...heads);
            } else {
              byTicks.set(ticks, { ticks, system, x: head.x, end: head.x, heads: [...heads] });
            }
            const src = note.sourceNote;
            if (this.staves.includes(staff) && !src.isRest() && !src.IsCueNote && !src.IsGraceNote) {
              this.targets.push({
                index: this.targets.length, start: ticks,
                end: ticks + Math.round(src.Length.RealValue * TICKS_PER_WHOLE),
                pitch: src.halfTone + 12, headY: head.y,
              });
            }
          }
        }
      }
    }
    this.onsets = [...byTicks.values()].sort((a, b) => a.ticks - b.ticks);
    this.bars.sort((a, b) => a.ticks - b.ticks);
    this.targets.sort((a, b) => a.start - b.start);
    this.onsets.forEach((on, i) => {
      const next = this.onsets[i + 1];
      const bar = this.bars.filter(b => b.ticks <= on.ticks).pop();
      on.end = next && next.system === on.system ? next.x : bar?.right ?? on.x;
    });

    this.cursor = this.svg.appendChild(document.createElementNS(SVG_NS, "line"));
    this.cursor.classList.add("cursor");
    this.moveTo(0);
  }

  targetAt(ticks: number): Target | null {
    const t = this.targets.filter(t => t.start <= ticks).pop();
    return t && ticks < t.end ? t : null;
  }

  xAt(ticks: number): number {
    const i = this.indexAt(ticks);
    const on = this.onsets[i];
    if (!on) return 0;
    const next = this.onsets[i + 1];
    const span = (next ? next.ticks : on.ticks + TICKS_PER_QUARTER) - on.ticks;
    const frac = Math.min(Math.max((ticks - on.ticks) / span, 0), 1);
    return on.x + (on.end - on.x) * frac;
  }

  moveTo(ticks: number): void {
    const i = this.indexAt(ticks);
    const on = this.onsets[i];
    if (!on || !this.cursor) return;
    const x = String(this.xAt(ticks));
    const span = this.systems.get(on.system);
    this.cursor.setAttribute("x1", x);
    this.cursor.setAttribute("x2", x);
    this.cursor.setAttribute("y1", String(span?.top ?? 0));
    this.cursor.setAttribute("y2", String(span?.bottom ?? 0));
    if (i !== this.current) {
      this.onsets[this.current]?.heads.forEach(h => h.classList.remove("playing"));
      on.heads.forEach(h => h.classList.add("playing"));
      this.current = i;
    }
  }

  barAt(clientX: number, clientY: number): number | null {
    const ctm = this.svg?.getScreenCTM();
    if (!ctm) return null;
    const p = new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse());
    let system: number | null = null;
    let best = 3 * this.staffStep * 2; // how far above or below a system a tap still counts
    for (const [n, { top, bottom }] of this.systems) {
      const distance = p.y < top ? top - p.y : p.y > bottom ? p.y - bottom : 0;
      if (distance < best) [system, best] = [n, distance];
    }
    const onSystem = this.bars.filter(b => b.system === system);
    if (!onSystem.length) return null;
    return (onSystem.filter(b => b.left <= p.x).pop() ?? onSystem[0]).ticks;
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
