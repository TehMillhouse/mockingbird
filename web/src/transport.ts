import * as Tone from "tone";
import "./audio";
import { type Level, totalTicks } from "./level";
import type { Instruments } from "./synth";

// Tone's default resolution is 192 PPQ, exactly 8 of its ticks per level tick.
const TONE_PER_LEVEL_TICK = Tone.getTransport().PPQ / 24;

const toneTicks = (ticks: number) => `${ticks * TONE_PER_LEVEL_TICK}i`;
const midiNote = (pitch: number) => Tone.Frequency(pitch, "midi").toNote();

/** Schedules a level on Tone's transport. Everything is placed in ticks, so a tempo
 *  change takes effect immediately for all notes that have not started yet. */
export class Player {
  private readonly transport = Tone.getTransport();
  private length = 0;
  private endedAt: number | null = null;

  constructor(private readonly instruments: Instruments) {}

  load(level: Level): void {
    this.stop();
    this.transport.cancel(0);
    this.length = totalTicks(level);

    for (const n of mergeTies(level)) {
      this.at(n.start, time => {
        this.instruments.voice.triggerAttackRelease(midiNote(n.pitch), durationSeconds(n.duration), time);
      });
    }
    for (const ev of level.accompaniment) {
      this.at(ev.start, time => {
        this.instruments.piano.triggerAttackRelease(ev.pitches.map(midiNote), durationSeconds(ev.duration), time, 0.6);
      });
    }
    this.at(this.length, time => {
      this.endedAt = time;
      this.transport.stop(time);
    });
  }

  /** Schedule at a level tick. After a scheduled stop, Tone keeps working through its
   *  lookahead window with the position already reset to 0, so events at tick 0 would
   *  fire again past the end; those calls are dropped here. */
  private at(ticks: number, callback: (time: number) => void): void {
    this.transport.schedule(time => {
      if (this.endedAt === null || time < this.endedAt) callback(time);
    }, toneTicks(ticks));
  }

  get playing(): boolean {
    return this.transport.state === "started";
  }

  async toggle(): Promise<void> {
    await Tone.start();
    if (this.playing) {
      this.transport.pause();
      this.instruments.silence();
    } else {
      this.start();
    }
  }

  stop(): void {
    this.transport.stop();
    this.instruments.silence();
  }

  async restart(): Promise<void> {
    this.stop();
    await Tone.start();
    this.start();
  }

  private start(): void {
    this.endedAt = null;
    this.transport.start();
  }

  set bpm(value: number) {
    this.transport.bpm.value = value;
  }

  /** Output latency as the browser reports it; often missing or too low. */
  get outputLatency(): number {
    const raw = Tone.getContext().rawContext as AudioContext;
    return (raw.outputLatency || 0) + (raw.baseLatency || 0);
  }

  /** The level tick reaching the speakers at an AudioContext time. */
  heardTicksAt(time: number): number {
    const ticks = this.transport.getTicksAtTime(time - this.outputLatency) / TONE_PER_LEVEL_TICK;
    return Math.min(Math.max(ticks, 0), this.length);
  }

  /** The level tick reaching the speakers now. */
  audibleTicks(): number {
    if (!this.playing) return this.transport.ticks / TONE_PER_LEVEL_TICK;
    return this.heardTicksAt(Tone.getContext().immediate());
  }
}

/** Seconds for a duration in ticks at the current tempo. */
function durationSeconds(ticks: number): number {
  return Tone.Ticks(ticks * TONE_PER_LEVEL_TICK).toSeconds();
}

/** Melody notes as sounding events: tied notes of the same pitch become one. */
function mergeTies(level: Level): { start: number; duration: number; pitch: number }[] {
  const out: { start: number; duration: number; pitch: number }[] = [];
  let t = 0;
  let tiedFromPrevious = false;
  for (const n of level.melody) {
    if (n.pitch !== null) {
      const last = out[out.length - 1];
      if (tiedFromPrevious && last && last.pitch === n.pitch) last.duration += n.duration;
      else out.push({ start: t, duration: n.duration, pitch: n.pitch });
    }
    tiedFromPrevious = n.tie;
    t += n.duration;
  }
  return out;
}
