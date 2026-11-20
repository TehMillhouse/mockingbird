import type { ScoreSystem, ScoreView } from "./score-view";
import { recall, remember } from "./storage";

/** Room left above a system's first staff when it is scrolled to the top, in staff
 *  steps: for bar numbers, high notes and markings drawn above it. */
const HEADROOM = 12;
/** How long a scroll takes; slower than the browser's smooth scroll, which is jarring
 *  to read along with. */
const SCROLL_MS = 700;
const TOLERANCE_PX = 2;
const STORAGE_KEY = "autoscroll";

/** Keeps the playing system near the top of the window, a system at a time.
 *
 *  The first system whose top is in the window counts as at the top. Once the first
 *  two bars of the system below it have been heard, that system is scrolled to the
 *  top; if the window cannot hold both systems, as soon as playback reaches it.
 *  Playback above the window brings its system back to the top. */
export class Autoscroll {
  enabled = true;
  private scrolling: { from: number; to: number; start: number; at: number } | null = null;

  /** `checkbox` turns it on and off; its state is remembered (on unless switched off). */
  constructor(checkbox: HTMLInputElement | null) {
    if (!checkbox) return;
    checkbox.checked = recall(STORAGE_KEY) !== "off";
    this.enabled = checkbox.checked;
    checkbox.addEventListener("change", () => {
      this.enabled = checkbox.checked;
      remember(STORAGE_KEY, checkbox.checked ? "on" : "off");
    });
  }

  /** Once per frame, with the tick being heard. */
  update(score: ScoreView | null, ticks: number, playing: boolean): void {
    if (this.enabled && playing && score) this.follow(score, ticks);
    this.step();
  }

  private follow(score: ScoreView, ticks: number): void {
    const ctm = score.svg?.getScreenCTM();
    const systems = score.systems();
    if (!ctm || !systems.length) return;
    const headroom = HEADROOM * score.staffStep;
    // the scroll position that puts a system at the top of the window
    const scrollFor = (s: ScoreSystem) => window.scrollY + new DOMPoint(0, s.top - headroom).matrixTransform(ctm).y;
    let top = systems.findIndex(s => scrollFor(s) >= window.scrollY - TOLERANCE_PX);
    if (top < 0) top = systems.length - 1;
    const after = systems.findIndex(s => s.start > ticks);
    const playing = Math.max(0, (after < 0 ? systems.length : after) - 1);
    // a system's room reaches to where the next one starts (its lyrics included); the
    // last one's as far below its last staff as is kept above the first
    const roomEnd = (i: number) => systems[i + 1]
      ? scrollFor(systems[i + 1])
      : scrollFor({ ...systems[i], top: systems[i].bottom + 2 * headroom });
    const fitsBelow = playing > 0 && roomEnd(playing) - scrollFor(systems[playing - 1]) <= window.innerHeight;
    const arrived = !fitsBelow || ticks >= systems[playing].settled;
    const wanted = playing < top || arrived ? playing : playing - 1;
    if (wanted === top || (wanted < top && playing >= top)) return;
    const limit = document.documentElement.scrollHeight - window.innerHeight;
    const y = Math.round(Math.min(Math.max(scrollFor(systems[wanted]), 0), limit));
    if (Math.abs(y - window.scrollY) < TOLERANCE_PX || this.scrolling?.to === y) return;
    this.scrolling = { from: window.scrollY, to: y, start: performance.now(), at: window.scrollY };
  }

  /** One frame of a scroll, eased in and out. Scrolling by hand ends it. */
  private step(): void {
    const s = this.scrolling;
    if (!s) return;
    if (Math.abs(window.scrollY - s.at) > TOLERANCE_PX) {
      this.scrolling = null;
      return;
    }
    const t = Math.min((performance.now() - s.start) / SCROLL_MS, 1);
    const eased = t < 0.5 ? 4 * t ** 3 : 1 - (2 - 2 * t) ** 3 / 2;
    window.scrollTo({ top: s.from + (s.to - s.from) * eased, behavior: "instant" });
    s.at = window.scrollY;
    if (t === 1) this.scrolling = null;
  }
}
