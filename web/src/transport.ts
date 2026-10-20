import * as Tone from "tone";
import "./audio";
import { TICKS_PER_QUARTER } from "./level";
import { makeClicker } from "./synth";

// Tone's default resolution is 192 PPQ, exactly 8 of its ticks per level tick.
const TONE_PER_LEVEL_TICK = Tone.getTransport().PPQ / TICKS_PER_QUARTER;

const toneTicks = (ticks: number) => `${ticks * TONE_PER_LEVEL_TICK}i`;
const midiNote = (pitch: number) => Tone.Frequency(pitch, "midi").toNote();

export interface NoteEvent {
  start: number;
  duration: number;
  pitches: number[];
}

/** One instrument's notes. `articulate` shortens each note a little, for synth voices
 *  on which a repeated pitch would otherwise sound like one held note. */
export interface Track {
  events: NoteEvent[];
  play: (notes: string[], seconds: number, time: number) => void;
  articulate?: boolean;
}

export interface Bar {
  start: number;
  duration: number;
  meter: string;
}

export interface TempoChange {
  start: number;
  bpm: number;
}

/** Everything the player needs, in ticks (24 per quarter). */
export interface Arrangement {
  length: number;
  bars: Bar[];
  tempos: TempoChange[];
  tracks: Track[];
  /** Release every sounding note, on pause and stop. */
  silence: () => void;
}

/** Schedules an arrangement on Tone's transport. Everything is placed in ticks, so a
 *  tempo change takes effect immediately for all notes that have not started yet.
 *
 *  Every start is preceded by a count-in. The player keeps its own playback position
 *  and starts the transport from it once the count-in is over. */
export class Player {
  private readonly transport = Tone.getTransport();
  private arrangement: Arrangement = { length: 0, bars: [], tempos: [], tracks: [], silence: () => {} };
  private scale = 1;
  /** Where the next start begins, in ticks. */
  private position = 0;
  /** While active: AudioContext times the count-in begins and the transport starts. */
  private countFrom = 0;
  private startsAt: number | null = null;
  private stoppedAt: number | null = null;
  private countBar = 4 * TICKS_PER_QUARTER;
  private countBeat = TICKS_PER_QUARTER;
  private clicker: Tone.Synth | null = null;

  load(arrangement: Arrangement): void {
    this.stop();
    this.transport.cancel(0);
    this.arrangement = arrangement;

    for (const track of arrangement.tracks) {
      for (const ev of track.events) {
        const notes = ev.pitches.map(midiNote);
        this.at(ev.start, time => {
          const seconds = durationSeconds(ev.duration);
          track.play(notes, track.articulate ? articulated(seconds) : seconds, time);
        });
      }
    }
    for (const change of arrangement.tempos.slice(1)) {
      this.at(change.start, time => this.transport.bpm.setValueAtTime(change.bpm * this.scale, time));
    }
    this.at(arrangement.length, time => {
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
    this.applyTempo(0);
  }

  /** Schedule at a tick. After a stop, Tone keeps working through its lookahead
   *  window with the position reset to 0, so events at tick 0 would fire again;
   *  calls at or after the last stop are dropped. */
  private at(ticks: number, callback: (time: number) => void): void {
    this.transport.schedule(time => {
      if (this.stoppedAt === null || time < this.stoppedAt) callback(time);
    }, toneTicks(ticks));
  }

  /** Counting in or playing. */
  get active(): boolean {
    return this.startsAt !== null;
  }

  /** Playing the music itself, past the count-in. */
  get playing(): boolean {
    return this.startsAt !== null && Tone.getContext().immediate() >= this.startsAt;
  }

  /** Playback speed relative to the written tempo. */
  set tempoScale(value: number) {
    this.scale = value;
    this.applyTempo(this.ticksAgo(0));
  }

  async toggle(): Promise<void> {
    if (this.active) this.pause();
    else await this.play();
  }

  async play(): Promise<void> {
    await Tone.start();
    if (this.active) return;
    this.applyTempo(this.position);
    // a full bar, plus the part of the current bar before the start: the count-in then
    // begins on a downbeat and a pickup or mid-bar start enters on its own beat
    const bar = this.barAt(this.position);
    [this.countBar, this.countBeat] = meterTicks(bar?.meter ?? "4/4");
    const intoBar = bar ? Math.max(0, this.countBar - (bar.start + bar.duration - this.position)) : 0;
    const lead = this.countBar + intoBar;
    this.clicker?.dispose();
    this.clicker = makeClicker();
    this.countFrom = Tone.now();
    for (let t = 0; t < lead; t += this.countBeat) {
      const downbeat = t % this.countBar === 0;
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

  /** Move to a tick; if active, count in again from there. */
  async seek(ticks: number): Promise<void> {
    const wasActive = this.active;
    this.halt();
    this.position = Math.min(Math.max(ticks, 0), this.arrangement.length);
    if (wasActive) await this.play();
  }

  private halt(): void {
    // Transport.stop also cancels a start still pending after a count-in
    this.stoppedAt = Tone.getContext().immediate();
    this.transport.stop();
    this.clicker?.dispose();
    this.clicker = null;
    this.startsAt = null;
    this.arrangement.silence();
  }

  private barAt(ticks: number): Bar | undefined {
    return this.arrangement.bars.filter(b => b.start <= ticks).pop() ?? this.arrangement.bars[0];
  }

  /** Set the transport to the scaled tempo in force at a tick. */
  private applyTempo(ticks: number): void {
    const change = this.arrangement.tempos.filter(t => t.start <= ticks).pop() ?? this.arrangement.tempos[0];
    if (change) this.transport.bpm.value = change.bpm * this.scale;
  }

  /** Output latency as the browser reports it; often missing or too low. */
  get reportedOutputLatency(): number {
    const raw = Tone.getContext().rawContext as AudioContext;
    return (raw.outputLatency || 0) + (raw.baseLatency || 0);
  }

  /** The tick the transport was at at an AudioContext time. */
  ticksAt(time: number): number {
    const ticks = this.transport.getTicksAtTime(time) / TONE_PER_LEVEL_TICK;
    return Math.min(Math.max(ticks, 0), this.arrangement.length);
  }

  /** The tick that was playing `delay` seconds ago; the start position during the
   *  count-in and while stopped. */
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
    const beat = Math.floor((time - this.countFrom) / durationSeconds(this.countBeat));
    return (beat % (this.countBar / this.countBeat)) + 1;
  }
}

/** Bar and counted beat in ticks: dotted quarters in compound meters (6/8, 9/8,
 *  12/8), else the meter's own unit. */
function meterTicks(meter: string): [number, number] {
  const [num, den] = meter.split("/").map(Number);
  const unit = (4 * TICKS_PER_QUARTER) / den;
  const compound = den === 8 && num % 3 === 0 && num > 3;
  return [num * unit, compound ? 3 * unit : unit];
}

/** How long a voice holds a note of `seconds`: a little short, so repeated pitches are
 *  heard as separate notes rather than one held note. */
function articulated(seconds: number): number {
  return seconds - Math.min(0.08, 0.12 * seconds);
}

/** Seconds for a duration in ticks at the current tempo. */
function durationSeconds(ticks: number): number {
  return Tone.Ticks(ticks * TONE_PER_LEVEL_TICK).toSeconds();
}
