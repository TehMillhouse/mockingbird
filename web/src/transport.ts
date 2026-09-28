import * as Tone from "tone";
import "./audio";
import { type Level, TICKS_PER_QUARTER, totalTicks } from "./level";
import { type Instruments, makeClicker } from "./synth";

// Tone's default resolution is 192 PPQ, exactly 8 of its ticks per level tick.
const TONE_PER_LEVEL_TICK = Tone.getTransport().PPQ / TICKS_PER_QUARTER;

const toneTicks = (ticks: number) => `${ticks * TONE_PER_LEVEL_TICK}i`;
const midiNote = (pitch: number) => Tone.Frequency(pitch, "midi").toNote();

/** Schedules a level on Tone's transport. Everything is placed in ticks, so a tempo
 *  change takes effect immediately for all notes that have not started yet.
 *
 *  Every start is preceded by a bar of clicks. The player keeps its own playback
 *  position and starts the transport from it once the count-in is over. */
export class Player {
  private readonly transport = Tone.getTransport();
  private length = 0;
  private barTicks = 4 * TICKS_PER_QUARTER;
  private beatTicks = TICKS_PER_QUARTER;
  private pickup = 0;
  /** Where the next start begins, in level ticks. */
  private position = 0;
  /** While active: AudioContext times the count-in begins and the transport starts. */
  private countFrom = 0;
  private startsAt: number | null = null;
  private stoppedAt: number | null = null;
  private clicker: Tone.Synth | null = null;

  constructor(private readonly instruments: Instruments) {}

  load(level: Level): void {
    this.stop();
    this.transport.cancel(0);
    this.length = totalTicks(level);
    [this.barTicks, this.beatTicks] = meterTicks(level.meter);
    this.pickup = level.pickup_ticks;

    for (const n of mergeTies(level)) {
      this.at(n.start, time => {
        this.instruments.voice.triggerAttackRelease(midiNote(n.pitch), articulated(durationSeconds(n.duration)), time);
      });
    }
    for (const ev of level.accompaniment) {
      this.at(ev.start, time => {
        this.instruments.piano.triggerAttackRelease(ev.pitches.map(midiNote), durationSeconds(ev.duration), time, 0.6);
      });
    }
    this.at(this.length, time => {
      this.stoppedAt = time;
      this.transport.stop(time);
      // the callback runs ahead of time; the player is idle once the end is reached
      const started = this.startsAt;
      setTimeout(() => {
        if (this.startsAt !== started) return;
        this.startsAt = null;
        this.position = 0;
      }, Math.max(0, (time - Tone.getContext().currentTime) * 1000));
    });
  }

  /** Schedule at a level tick. After a stop, Tone keeps working through its
   *  lookahead window with the position reset to 0, so events at tick 0 would fire
   *  again; calls at or after the last stop are dropped. */
  private at(ticks: number, callback: (time: number) => void): void {
    this.transport.schedule(time => {
      if (this.stoppedAt === null || time < this.stoppedAt) callback(time);
    }, toneTicks(ticks));
  }

  /** Counting in or playing. */
  get active(): boolean {
    return this.startsAt !== null;
  }

  /** Playing the level itself, past the count-in. */
  get playing(): boolean {
    return this.startsAt !== null && Tone.getContext().immediate() >= this.startsAt;
  }

  async toggle(): Promise<void> {
    if (this.active) this.pause();
    else await this.play();
  }

  async play(): Promise<void> {
    await Tone.start();
    if (this.active) return;
    // a full bar, plus the part of the current bar before the start: the count-in then
    // begins on a downbeat and a pickup or mid-bar start enters on its own beat
    const barShift = this.pickup ? this.barTicks - this.pickup : 0;
    const lead = this.barTicks + ((this.position + barShift) % this.barTicks);
    this.clicker?.dispose();
    this.clicker = makeClicker();
    this.countFrom = Tone.now();
    for (let t = 0; t < lead; t += this.beatTicks) {
      const downbeat = t % this.barTicks === 0;
      this.clicker.triggerAttackRelease(downbeat ? "C6" : "G5", 0.02, this.countFrom + durationSeconds(t));
    }
    this.startsAt = this.countFrom + durationSeconds(lead);
    this.stoppedAt = null;
    this.transport.start(this.startsAt, toneTicks(this.position));
  }

  /** Stop and keep the position; the next start counts in from there. */
  pause(): void {
    if (!this.active) return;
    if (this.playing) this.position = this.ticksAt(Tone.getContext().immediate());
    this.halt();
  }

  stop(): void {
    this.halt();
    this.position = 0;
  }

  /** Play from the beginning, counting in, whether or not it was playing. */
  async restart(): Promise<void> {
    this.stop();
    await this.play();
  }

  /** Move to a level tick; if active, count in again from there. */
  async seek(ticks: number): Promise<void> {
    const wasActive = this.active;
    this.halt();
    this.position = Math.min(Math.max(ticks, 0), this.length);
    if (wasActive) await this.play();
  }

  private halt(): void {
    // Transport.stop also cancels a start still pending after a count-in
    this.stoppedAt = Tone.getContext().immediate();
    this.transport.stop();
    this.clicker?.dispose();
    this.clicker = null;
    this.startsAt = null;
    this.instruments.silence();
  }

  set bpm(value: number) {
    this.transport.bpm.value = value;
  }

  /** Output latency as the browser reports it; often missing or too low. */
  get reportedOutputLatency(): number {
    const raw = Tone.getContext().rawContext as AudioContext;
    return (raw.outputLatency || 0) + (raw.baseLatency || 0);
  }

  /** The level tick the transport was at at an AudioContext time. */
  ticksAt(time: number): number {
    const ticks = this.transport.getTicksAtTime(time) / TONE_PER_LEVEL_TICK;
    return Math.min(Math.max(ticks, 0), this.length);
  }

  /** The level tick that was playing `delay` seconds ago; the start position during
   *  the count-in and while stopped. */
  ticksAgo(delay: number): number {
    if (this.startsAt === null) return this.position;
    const time = Tone.getContext().immediate() - delay;
    return time < this.startsAt ? this.position : this.ticksAt(time);
  }

  /** The count-in beat heard `delay` seconds ago (1 = first beat of a bar), or null
   *  outside the count-in. */
  countInBeat(delay: number): number | null {
    if (this.startsAt === null) return null;
    const time = Tone.getContext().immediate() - delay;
    if (time < this.countFrom || time >= this.startsAt) return null;
    const beat = Math.floor((time - this.countFrom) / durationSeconds(this.beatTicks));
    return (beat % (this.barTicks / this.beatTicks)) + 1;
  }
}

/** Bar and counted beat in level ticks: dotted quarters in compound meters (6/8,
 *  9/8, 12/8), else the meter's own unit. */
function meterTicks(meter: string): [number, number] {
  const [num, den] = meter.split("/").map(Number);
  const unit = (4 * TICKS_PER_QUARTER) / den;
  const compound = den === 8 && num % 3 === 0 && num > 3;
  return [num * unit, compound ? 3 * unit : unit];
}

/** How long the voice guide holds a note of `seconds`: a little short, so repeated
 *  pitches are heard as separate notes rather than one held note. */
function articulated(seconds: number): number {
  return seconds - Math.min(0.08, 0.12 * seconds);
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
