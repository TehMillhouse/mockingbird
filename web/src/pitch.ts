import { PitchDetector } from "pitchy";

const WINDOW = 2048;
const MIN_CLARITY = 0.9;
const MIN_HZ = 60;
const MAX_HZ = 1400;

export interface PitchReading {
  /** Fractional MIDI pitch. */
  midi: number;
  /** AudioContext time the analysed window is centred on. */
  time: number;
}

/** Microphone input with McLeod pitch detection on the most recent window. */
export class Mic {
  private readonly buffer = new Float32Array(WINDOW);
  private readonly detector = PitchDetector.forFloat32Array(WINDOW);

  private constructor(
    private readonly ctx: BaseAudioContext,
    private readonly stream: MediaStream,
    private readonly source: MediaStreamAudioSourceNode,
    private readonly analyser: AnalyserNode,
  ) {
    this.detector.minVolumeDecibels = -45;
  }

  static async open(ctx: BaseAudioContext & { createMediaStreamSource(s: MediaStream): MediaStreamAudioSourceNode }): Promise<Mic> {
    // the browser's voice processing smears pitch and fights sustained notes
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = WINDOW;
    source.connect(analyser);
    return new Mic(ctx, stream, source, analyser);
  }

  get label(): string {
    return this.stream.getAudioTracks()[0]?.label ?? "microphone";
  }

  /** Input latency the browser reports for the track, if any. */
  get reportedLatency(): number {
    const settings = this.stream.getAudioTracks()[0]?.getSettings() as MediaTrackSettings & { latency?: number };
    return settings?.latency ?? 0;
  }

  read(): PitchReading | null {
    this.analyser.getFloatTimeDomainData(this.buffer);
    const [hz, clarity] = this.detector.findPitch(this.buffer, this.ctx.sampleRate);
    if (clarity < MIN_CLARITY || hz < MIN_HZ || hz > MAX_HZ) return null;
    return {
      midi: 69 + 12 * Math.log2(hz / 440),
      time: this.ctx.currentTime - WINDOW / 2 / this.ctx.sampleRate,
    };
  }

  close(): void {
    this.source.disconnect();
    this.stream.getTracks().forEach(t => t.stop());
  }
}
