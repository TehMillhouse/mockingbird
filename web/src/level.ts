// Mirrors mockingbird/schema.py. Times are ticks, 24 per quarter note.
export const TICKS_PER_QUARTER = 24;

export interface Note {
  pitch: number | null;
  duration: number;
  tie: boolean;
}

export interface AccompEvent {
  start: number;
  duration: number;
  pitches: number[];
}

export interface Level {
  id: string;
  tonic: string;
  mode: "major" | "minor";
  meter: string;
  voice: "S" | "A" | "T" | "B";
  difficulty: number;
  bars: number;
  tempo_bpm: number;
  pickup_ticks: number;
  melody: Note[];
  phrase_ends: number[];
  accompaniment: AccompEvent[];
  difficulty_score: number | null;
}

export interface LevelRequest {
  tonic: string;
  mode: string;
  voice: string;
  difficulty: number;
}

export async function fetchLevel(req: LevelRequest): Promise<{ level: Level; abc: string }> {
  // relative, so the app works under any path prefix
  const r = await fetch("levels", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error(await r.text());
  const level: Level = await r.json();
  const abc = await (await fetch(`levels/${level.id}/export?fmt=abc`)).text();
  return { level, abc };
}

export function totalTicks(level: Level): number {
  return level.melody.reduce((t, n) => t + n.duration, 0);
}
