import { calibrateAv, calibrateRoundTrip } from "./latency";
import type { Mic } from "./pitch";

const HTML = `
  <h2>Latency calibration</h2>
  <p id="cal-progress"></p>
  <section>
    <h3>Picture and sound</h3>
    <p>Lines the cursor up with what you hear. Tap <kbd>Space</kbd> (or the box) with each
      click, then with each flash.</p>
    <div id="flash">tap</div>
    <p><button id="cal-av" type="button">Start</button> <output id="cal-av-result"></output></p>
  </section>
  <section>
    <h3>Microphone</h3>
    <p>Lines your pitch trace up with the notes. Clap with each click, close to the microphone.</p>
    <p><button id="cal-rt" type="button">Start</button> <output id="cal-rt-result"></output></p>
  </section>
  <form method="dialog"><button>Close</button></form>`;

/** What the dialog needs from the page around it. */
export interface CalibrationHooks {
  /** Silence playback; called before each measurement. */
  stop(): void;
  /** The open microphone, opening it if needed; null if it cannot be opened. */
  mic(): Promise<Mic | null>;
  saveAv(seconds: number): void;
  saveRoundTrip(mic: Mic, seconds: number): void;
  /** Recompute the latencies in use and show them; called when the dialog opens and
   *  after each measurement. */
  refresh(): void;
}

/** A latency, and whether it was measured or is the browser's estimate. */
export interface Latency {
  seconds: number;
  calibrated: boolean;
}

/** The latency calibration dialog: measures picture-to-sound and microphone round
 *  trip latency for the current devices (see latency.ts). */
export class Calibration {
  private readonly dialog: HTMLDialogElement;

  constructor(opener: HTMLElement, private readonly hooks: CalibrationHooks) {
    this.dialog = document.body.appendChild(document.createElement("dialog"));
    this.dialog.id = "calibration";
    this.dialog.innerHTML = HTML;
    const $ = <T extends HTMLElement>(sel: string) => this.dialog.querySelector(sel) as T;
    opener.addEventListener("click", () => {
      hooks.refresh();
      this.progress("Wear the headphones you sing with.");
      this.dialog.showModal();
    });
    $("#cal-av").addEventListener("click", e => this.run(e.currentTarget as HTMLButtonElement, async () => {
      hooks.saveAv(await calibrateAv($("#flash"), m => this.progress(m)));
    }));
    $("#cal-rt").addEventListener("click", e => this.run(e.currentTarget as HTMLButtonElement, async () => {
      const mic = await hooks.mic();
      if (!mic) throw new Error("no microphone");
      hooks.saveRoundTrip(mic, await calibrateRoundTrip(mic, m => this.progress(m)));
    }));
  }

  get open(): boolean {
    return this.dialog.open;
  }

  /** Show the latencies in use; `roundTrip` is null while the microphone is off. */
  show(av: Latency, roundTrip: Latency | null): void {
    const text = (l: Latency) =>
      `${Math.round(l.seconds * 1000)} ms ${l.calibrated ? "(calibrated)" : "(browser estimate)"}`;
    (this.dialog.querySelector("#cal-av-result") as HTMLOutputElement).value = text(av);
    (this.dialog.querySelector("#cal-rt-result") as HTMLOutputElement).value =
      roundTrip ? text(roundTrip) : "turn the microphone on first";
  }

  private progress(message: string): void {
    (this.dialog.querySelector("#cal-progress") as HTMLElement).textContent = message;
  }

  private async run(button: HTMLButtonElement, measure: () => Promise<void>): Promise<void> {
    this.hooks.stop();
    const buttons = this.dialog.querySelectorAll("button");
    buttons.forEach(b => (b.disabled = true));
    try {
      await measure();
      this.progress("Saved.");
    } catch (e) {
      this.progress(`Calibration failed: ${e instanceof Error ? e.message : e}`);
    }
    buttons.forEach(b => (b.disabled = false));
    button.focus();
    this.hooks.refresh();
  }
}
