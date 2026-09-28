import * as Tone from "tone";
import "./audio";

const SALAMANDER = "https://tonejs.github.io/audio/salamander/";

function salamanderUrls(): Record<string, string> {
  const urls: Record<string, string> = { A0: "A0.mp3", C8: "C8.mp3" };
  for (let octave = 1; octave <= 7; octave++) {
    for (const name of ["C", "D#", "F#", "A"]) {
      urls[`${name}${octave}`] = `${name.replace("#", "s")}${octave}.mp3`;
    }
  }
  return urls;
}

/** A short click for count-ins and calibration, straight to the output. */
export function makeClicker(): Tone.Synth {
  return new Tone.Synth({
    oscillator: { type: "square" },
    envelope: { attack: 0.001, decay: 0.03, sustain: 0, release: 0.01 },
    volume: -8,
  }).toDestination();
}

/** The two sound sources, each behind its own gain so the mix changes live. */
export class Instruments {
  readonly voiceGain = new Tone.Gain(1).toDestination();
  readonly pianoGain = new Tone.Gain(1).toDestination();
  readonly voice = new Tone.Synth({
    oscillator: { type: "triangle" },
    // a short release, so the gap before a repeated note stays audible
    envelope: { attack: 0.03, decay: 0.1, sustain: 0.8, release: 0.04 },
  }).connect(this.voiceGain);
  readonly piano = new Tone.Sampler({ urls: salamanderUrls(), baseUrl: SALAMANDER, release: 1 })
    .connect(this.pianoGain);

  /** Volume in 0..1 from a slider; squared so the slider feels even. */
  setVolume(which: "voice" | "piano", volume: number): void {
    const gain = which === "voice" ? this.voiceGain : this.pianoGain;
    gain.gain.rampTo(volume * volume, 0.03);
  }

  silence(): void {
    this.voice.triggerRelease();
    this.piano.releaseAll();
  }
}
