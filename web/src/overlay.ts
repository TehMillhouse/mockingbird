const SVG_NS = "http://www.w3.org/2000/svg";
const HIT_CENTS = 50;
/** A pause in the trace longer than this (in ticks) starts a new line. */
const MAX_GAP_TICKS = 4;

/** The sung pitch, drawn onto the score as lines next to the target note heads. */
export class Trace {
  private layer: SVGGElement | null = null;
  private path: SVGPathElement | null = null;
  private d = "";
  private last: { ticks: number; note: number; hit: boolean; point: string } | null = null;

  attach(svg: SVGSVGElement): void {
    this.layer = svg.appendChild(document.createElementNS(SVG_NS, "g"));
    this.layer.classList.add("trace");
    this.last = null;
  }

  clear(): void {
    this.layer?.replaceChildren();
    this.last = null;
  }

  /** Add a point. `cents` is the octave-folded deviation from the target note. */
  add(ticks: number, note: number, x: number, y: number, cents: number): void {
    if (!this.layer) return;
    const hit = Math.abs(cents) <= HIT_CENTS;
    const point = `${x.toFixed(1)},${y.toFixed(1)}`;
    const last = this.last;
    const joined = last !== null && last.note === note && ticks >= last.ticks && ticks - last.ticks <= MAX_GAP_TICKS;
    if (joined && last.hit === hit && this.path) {
      this.d += ` L${point}`;
    } else {
      // a new path per colour; when only the colour changes it starts at the previous point
      this.path = this.layer.appendChild(document.createElementNS(SVG_NS, "path"));
      this.path.classList.add(hit ? "hit" : "miss");
      this.d = joined ? `M${last.point} L${point}` : `M${point}`;
    }
    this.path.setAttribute("d", this.d);
    this.last = { ticks, note, hit, point };
  }
}
