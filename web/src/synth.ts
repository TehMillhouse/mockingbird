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

const VOICE_SYNTH = {
  oscillator: { type: "triangle" as const },
  // a short release, so the gap before a repeated note stays audible
  envelope: { attack: 0.03, decay: 0.1, sustain: 0.8, release: 0.04 },
};

// "Choir Aahs" from the FluidR3 General MIDI soundfont (CC BY 3.0), rendered per note
// by the midi-js-soundfonts project. Each file is a 3.1 s sustained tone.
const CHOIR = "https://gleitz.github.io/midi-js-soundfonts/FluidR3_GM/choir_aahs-mp3/";
const CHOIR_LOWEST = 36; // C2
const CHOIR_HIGHEST = 84; // C6
const CHOIR_STEP = 3; // semitones between samples, so no note is shifted more than 1.5
const LOOP_START = 0.6; // seconds: past the onset
const LOOP_END = 2.9; // before the cut at the end of the file
const LOOP_CROSSFADE = 0.4;
const CHOIR_RMS = 0.4; // the samples' level, matched roughly to the synth voice
const CHOIR_RELEASE = 0.08;
const FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];

/** A sample whose end crossfades into its loop start, so sustaining it by looping
 *  between LOOP_START and LOOP_END has no seam; scaled to CHOIR_RMS. */
function loopable(buffer: AudioBuffer): AudioBuffer {
  const rate = buffer.sampleRate;
  const [start, end, fade] = [LOOP_START, LOOP_END, LOOP_CROSSFADE].map(s => Math.round(s * rate));
  const span = end - start;
  const out = Tone.getContext().rawContext.createBuffer(buffer.numberOfChannels, end, rate);
  let squares = 0;
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const src = buffer.getChannelData(c);
    for (let i = start; i < end; i++) squares += src[i] * src[i];
  }
  const scale = CHOIR_RMS / Math.sqrt(squares / (span * buffer.numberOfChannels) || 1);
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const src = buffer.getChannelData(c);
    const dst = out.getChannelData(c);
    for (let i = 0; i < end; i++) {
      let v = src[i];
      if (i >= end - fade) {
        // equal-power: the end of the loop turns into the audio just before its start
        const a = (i - (end - fade)) / fade;
        v = v * Math.cos(a * Math.PI / 2) + src[i - span] * Math.sin(a * Math.PI / 2);
      }
      dst[i] = v * scale;
    }
  }
  return out;
}

let choirSamples: Promise<{ midi: number; buffer: Tone.ToneAudioBuffer }[]> | null = null;

/** The choir samples, fetched once and shared by every part. */
function loadChoir(): Promise<{ midi: number; buffer: Tone.ToneAudioBuffer }[]> {
  choirSamples ??= Promise.all(
    Array.from({ length: Math.floor((CHOIR_HIGHEST - CHOIR_LOWEST) / CHOIR_STEP) + 1 }, (_, k) => {
      const midi = CHOIR_LOWEST + k * CHOIR_STEP;
      const name = `${FLAT_NAMES[midi % 12]}${Math.floor(midi / 12) - 1}`;
      return Tone.ToneAudioBuffer.fromUrl(`${CHOIR}${name}.mp3`)
        .then(b => ({ midi, buffer: new Tone.ToneAudioBuffer(loopable(b.get()!)) }));
    }));
  return choirSamples;
}

/** Sung "aah" notes of any length: a choir sample, repitched from the nearest one and
 *  looped while the note lasts. Plays nothing until the samples have arrived. */
class Choir {
  private samples: { midi: number; buffer: Tone.ToneAudioBuffer }[] = [];
  private readonly sounding = new Set<Tone.ToneBufferSource>();

  constructor(private readonly output: Tone.ToneAudioNode) {
    loadChoir().then(s => { this.samples = s; }, () => { /* stays silent; the synth remains */ });
  }

  get ready(): boolean {
    return this.samples.length > 0;
  }

  triggerAttackRelease(notes: string[], seconds: number, time: number): void {
    for (const note of notes) {
      const midi = Tone.Frequency(note).toMidi();
      const sample = this.samples.reduce((a, b) => Math.abs(b.midi - midi) < Math.abs(a.midi - midi) ? b : a);
      const source = new Tone.ToneBufferSource({
        url: sample.buffer,
        loop: true,
        loopStart: LOOP_START,
        loopEnd: LOOP_END,
        playbackRate: 2 ** ((midi - sample.midi) / 12),
        fadeIn: 0.02,
        fadeOut: CHOIR_RELEASE,
        curve: "linear",
      }).connect(this.output);
      source.onended = () => {
        this.sounding.delete(source);
        source.dispose();
      };
      this.sounding.add(source);
      source.start(time).stop(time + seconds);
    }
  }

  releaseAll(): void {
    for (const source of this.sounding) source.stop();
  }

  dispose(): void {
    this.releaseAll();
  }
}

/** Which sung parts sound as a choir and which as the plain synth voice. */
export type Voicing = "all-sung" | "mine-sung" | "mine-synth" | "all-synth";

/** A choir piece's sound: per sung part a choir voice and a synth voice behind one gain,
 *  and one piano for the accompaniment staves. The voicing can change during playback. */
export class PartInstruments {
  private readonly pianoGain = new Tone.Gain(1).toDestination();
  private readonly piano = new Tone.Sampler({ urls: salamanderUrls(), baseUrl: SALAMANDER, release: 1 })
    .connect(this.pianoGain);
  private voices: { synth: Tone.PolySynth; choir: Choir; gain: Tone.Gain }[] = [];
  private sung: boolean[] = [];
  private mine = -1;
  voicing: Voicing = "mine-synth";

  /** Set up for a piece's parts, in order. */
  setup(sung: boolean[]): void {
    this.voices.forEach(v => { v.synth.dispose(); v.choir.dispose(); v.gain.dispose(); });
    this.sung = sung;
    this.voices = sung.map(() => {
      const gain = new Tone.Gain(1).toDestination();
      return { gain, synth: new Tone.PolySynth(Tone.Synth, VOICE_SYNTH).connect(gain), choir: new Choir(gain) };
    });
  }

  /** How part `index` sounds. */
  play(index: number): (notes: string[], seconds: number, time: number) => void {
    if (!this.sung[index]) return (notes, seconds, time) => this.piano.triggerAttackRelease(notes, seconds, time, 0.6);
    const { synth, choir } = this.voices[index];
    return (notes, seconds, time) => {
      const sung = this.voicing === "all-sung"
        || (this.voicing === "mine-sung" && index === this.mine)
        || (this.voicing === "mine-synth" && index !== this.mine);
      (sung && choir.ready ? choir : synth).triggerAttackRelease(notes, seconds, time);
    };
  }

  /** Volumes in 0..1 from sliders, squared so the sliders feel even. */
  mix(mine: number, volumes: { mine: number; choir: number; piano: number }): void {
    this.mine = mine;
    this.voices.forEach((v, i) => {
      const volume = i === mine ? volumes.mine : volumes.choir;
      v.gain.gain.rampTo(volume * volume, 0.03);
    });
    this.pianoGain.gain.rampTo(volumes.piano * volumes.piano, 0.03);
  }

  silence(): void {
    this.voices.forEach(v => { v.synth.releaseAll(); v.choir.releaseAll(); });
    this.piano.releaseAll();
  }
}

/** The two sound sources, each behind its own gain so the mix changes live. */
export class Instruments {
  readonly voiceGain = new Tone.Gain(1).toDestination();
  readonly pianoGain = new Tone.Gain(1).toDestination();
  readonly voice = new Tone.Synth(VOICE_SYNTH).connect(this.voiceGain);
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
