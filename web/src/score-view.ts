/** What the practice machinery needs from rendered notation (abcjs for levels, OSMD for
 *  pieces). Positions are in the SVG's own units. */

/** A melody note the singer is meant to hit: its tick span and its note head. */
export interface Target {
  index: number;
  start: number;
  end: number;
  pitch: number;
  headY: number;
}

export interface ScoreView {
  readonly svg: SVGSVGElement | null;
  /** Distance between adjacent staff positions (line to space). */
  readonly staffStep: number;
  moveTo(ticks: number): void;
  xAt(ticks: number): number;
  targetAt(ticks: number): Target | null;
  /** The start tick of the bar under a point on the page, or null. */
  barAt(clientX: number, clientY: number): number | null;
  /** The systems from top to bottom. */
  systems(): ScoreSystem[];
}

/** A system (line of music) on the rendered score. */
export interface ScoreSystem {
  /** The top of its first staff. */
  top: number;
  /** The bottom of its last staff. */
  bottom: number;
  /** The tick its first bar starts at. */
  start: number;
  /** The tick its third bar starts at (the next system's start if it has fewer bars). */
  settled: number;
}

/** Systems from a score's bars (start tick and system id, in tick order) and the
 *  vertical extent of each system's staves. */
export function scoreSystems(bars: { ticks: number; system: number }[],
  spans: Map<number, { top: number; bottom: number }>): ScoreSystem[] {
  const barsBySystem = new Map<number, number[]>();
  for (const bar of bars) {
    const list = barsBySystem.get(bar.system) ?? [];
    list.push(bar.ticks);
    barsBySystem.set(bar.system, list);
  }
  const ids = [...barsBySystem.keys()].sort((a, b) => barsBySystem.get(a)![0] - barsBySystem.get(b)![0]);
  return ids.map((id, i) => {
    const ticks = barsBySystem.get(id)!;
    const next = ids[i + 1] === undefined ? undefined : barsBySystem.get(ids[i + 1])![0];
    return {
      top: spans.get(id)?.top ?? 0,
      bottom: spans.get(id)?.bottom ?? 0,
      start: ticks[0],
      settled: ticks[2] ?? next ?? Infinity,
    };
  });
}
