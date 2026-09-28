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

/** The two sound sources, each behind its own gain so the mix changes live. */
export class Instruments {
  readonly voiceGain = new Tone.Gain(1).toDestination();
  readonly pianoGain = new Tone.Gain(1).toDestination();
  readonly voice = new Tone.Synth({
    oscillator: { type: "triangle" },
    envelope: { attack: 0.03, decay: 0.1, sustain: 0.8, release: 0.15 },
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
