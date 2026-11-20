import * as Tone from "tone";
import { audioContext, canChooseOutput, setOutputDevice } from "./audio";
import { Autoscroll } from "./autoscroll";
import { Calibration } from "./calibration";
import { DevicePicker } from "./devices";
import { LatencyStore } from "./latency";
import { Trace } from "./overlay";
import { Mic } from "./pitch";
import type { ScoreView } from "./score-view";
import { Player } from "./transport";

const DEVICES_HTML = `
  <label>Microphone <select id="input"></select></label>
  <button id="mic" type="button">Mic off</button>
  <meter id="input-level" min="-80" max="0" low="-60" high="-6" optimum="-20" value="-80" hidden title="Input level"></meter>
  <output id="sung"></output>
  <label id="output-choice">Output <select id="output"></select></label>
  <button id="calibrate" type="button">Calibrate</button>`;

const NOTE_NAMES = ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"];
// Pitch is sampled on a fixed clock, independent of the display's frame rate.
const PITCH_INTERVAL_MS = 10;

/** Playback, microphone, pitch trace, latency calibration and autoscroll around one
 *  rendered score at a time; shared by the level trainer and the piece practice page. */
export class Practice {
  readonly player = new Player();
  readonly trace = new Trace();
  private score: ScoreView | null = null;
  private mic: Mic | null = null;
  private readonly latencies = new LatencyStore();
  /** Current offsets in seconds, from calibration or else the browser's estimates. */
  private readonly latency = { av: 0, avCalibrated: false, roundTrip: 0, roundTripCalibrated: false };
  private readonly calibration: Calibration;
  private readonly autoscroll: Autoscroll;
  private readonly inputPicker: DevicePicker;
  private readonly outputPicker: DevicePicker;
  private readonly el: { micButton: HTMLButtonElement; readout: HTMLOutputElement; inputLevel: HTMLMeterElement };

  constructor(
    private readonly status: HTMLElement,
    private readonly playButton: HTMLButtonElement,
    paper: HTMLElement,
    devices: HTMLElement,
  ) {
    devices.innerHTML = DEVICES_HTML;
    const $ = <T extends HTMLElement>(sel: string) => document.querySelector(sel) as T;
    this.el = { micButton: $("#mic"), readout: $("#sung"), inputLevel: $("#input-level") };
    this.inputPicker = new DevicePicker($("#input"), "audioinput", "input-device");
    this.outputPicker = new DevicePicker($("#output"), "audiooutput", "output-device");
    this.autoscroll = new Autoscroll(document.querySelector<HTMLInputElement>("#autoscroll"));
    this.calibration = new Calibration($("#calibrate"), {
      stop: () => this.player.stop(),
      mic: async () => {
        if (!this.mic) await this.openMic();
        return this.mic;
      },
      saveAv: seconds => this.latencies.saveAv(this.outputLabel(), seconds),
      saveRoundTrip: (mic, seconds) => this.latencies.saveRoundTrip(this.outputLabel(), mic.label, seconds),
      refresh: () => this.refreshLatency(),
    });

    playButton.addEventListener("click", () => this.togglePlay());
    paper.addEventListener("click", e => this.seekToBar(e));
    this.el.micButton.addEventListener("click", () => this.toggleMic());
    $("#input").addEventListener("change", () => { if (this.mic) this.openMic(); });
    $("#output").addEventListener("change", () => this.chooseOutput());
    navigator.mediaDevices.addEventListener("devicechange", () => {
      this.inputPicker.refresh();
      this.outputPicker.refresh();
    });

    if (!canChooseOutput) $("#output-choice").hidden = true;
    Promise.all([this.inputPicker.refresh(), this.outputPicker.refresh()]).then(() => {
      if (this.outputPicker.value) this.chooseOutput();
      else this.refreshLatency();
    });
    requestAnimationFrame(() => this.frame());
    setInterval(() => this.listen(), PITCH_INTERVAL_MS);
  }

  /** Show a newly rendered score; the trace is drawn into it. */
  attach(score: ScoreView): void {
    this.score = score;
    if (score.svg) this.trace.attach(score.svg);
  }

  get loaded(): boolean {
    return this.score !== null;
  }

  /** Whether page key bindings should be ignored (a dialog is open). */
  get busy(): boolean {
    return this.calibration.open;
  }

  /** Space, R and M, for the page's key handler. */
  readonly keys: Record<string, () => void> = {
    " ": () => this.togglePlay(),
    r: () => this.restart(),
    m: () => this.toggleMic(),
  };

  async togglePlay(): Promise<void> {
    if (!this.loaded) return;
    if (!this.player.active) this.trace.clearFrom(this.player.ticksAgo(0));
    await this.player.toggle();
  }

  async restart(): Promise<void> {
    if (!this.loaded) return;
    this.trace.clear();
    await this.player.restart();
  }

  /** Tapping a bar moves playback there; while playing it counts in again from it. */
  private async seekToBar(e: MouseEvent): Promise<void> {
    const ticks = this.score?.barAt(e.clientX, e.clientY);
    if (ticks === null || ticks === undefined) return;
    this.trace.clearFrom(ticks);
    await this.player.seek(ticks);
  }

  private async openMic(): Promise<void> {
    this.mic?.close();
    this.mic = null;
    try {
      await Tone.start();
      this.mic = await Mic.open(audioContext, this.inputPicker.value);
      this.status.textContent = `Listening on ${this.mic.label}. Use headphones so the piano stays out of the mic.`;
      // device names are only readable once permission is granted
      await Promise.all([this.inputPicker.refresh(), this.outputPicker.refresh()]);
      this.refreshLatency();
    } catch (e) {
      const reason = e instanceof DOMException && e.name === "NotAllowedError"
        ? "permission denied; allow the microphone for this page in the browser's site settings"
        : e instanceof Error ? `${e.name}: ${e.message}` : String(e);
      this.status.textContent = `Could not open the microphone (${reason}).`;
    }
    this.showMicState();
  }

  private async toggleMic(): Promise<void> {
    if (this.mic) {
      this.mic.close();
      this.mic = null;
      this.showMicState();
    } else {
      await this.openMic();
    }
  }

  private showMicState(): void {
    this.el.micButton.textContent = this.mic ? "Mic on" : "Mic off";
    this.el.micButton.classList.toggle("on", this.mic !== null);
    this.el.inputLevel.hidden = this.mic === null;
    if (!this.mic) this.el.readout.value = "";
  }

  private async chooseOutput(): Promise<void> {
    try {
      await setOutputDevice(this.outputPicker.value);
    } catch (e) {
      this.status.textContent = `Could not switch output: ${e instanceof Error ? e.message : e}`;
    }
    this.refreshLatency();
  }

  private outputLabel(): string {
    return canChooseOutput ? this.outputPicker.label : "System default";
  }

  private refreshLatency(): void {
    const reported = this.player.reportedOutputLatency;
    const av = this.latencies.av(this.outputLabel());
    this.latency.av = av ?? reported;
    this.latency.avCalibrated = av !== undefined;
    const roundTrip = this.mic ? this.latencies.roundTrip(this.outputLabel(), this.mic.label) : undefined;
    this.latency.roundTrip = roundTrip ?? reported + (this.mic?.reportedLatency ?? 0);
    this.latency.roundTripCalibrated = roundTrip !== undefined;
    this.calibration.show(
      { seconds: this.latency.av, calibrated: this.latency.avCalibrated },
      this.mic ? { seconds: this.latency.roundTrip, calibrated: this.latency.roundTripCalibrated } : null);
  }

  private showSung(midi: number | null): void {
    if (midi === null) {
      this.el.readout.value = "–";
      return;
    }
    const nearest = Math.round(midi);
    const cents = Math.round((midi - nearest) * 100);
    const name = NOTE_NAMES[((nearest % 12) + 12) % 12] + (Math.floor(nearest / 12) - 1);
    this.el.readout.value = `${name} ${cents >= 0 ? "+" : "−"}${Math.abs(cents)}¢`;
  }

  /** Place the sung pitch against the note that was sounding when it was sung. The
   *  singer follows what they hear, so its capture time is mapped back through both
   *  the input and the output latency. */
  private traceSung(midi: number, time: number): void {
    if (!this.score) return;
    const ticks = this.player.ticksAt(time - this.latency.roundTrip);
    const target = this.score.targetAt(ticks);
    if (!target) return;
    const off = midi - target.pitch;
    const folded = off - 12 * Math.round(off / 12); // octave errors don't count
    const y = target.headY - folded * (this.score.staffStep / 2);
    this.trace.add(ticks, target.index, this.score.xAt(ticks), y, folded * 100);
  }

  private listen(): void {
    if (!this.mic) return;
    const { db, pitch } = this.mic.read();
    this.el.inputLevel.value = db;
    this.showSung(pitch?.midi ?? null);
    if (pitch && this.player.playing) this.traceSung(pitch.midi, pitch.time);
  }

  private frame(): void {
    // what is heard when this frame is seen was scheduled A − V ago
    const heard = this.player.ticksAgo(this.latency.av);
    this.score?.moveTo(heard);
    this.autoscroll.update(this.score, heard, this.player.playing);
    const beat = this.player.countInBeat(this.latency.av);
    this.playButton.textContent = beat !== null ? String(beat) : this.player.active ? "Pause" : "Play";
    requestAnimationFrame(() => this.frame());
  }
}
