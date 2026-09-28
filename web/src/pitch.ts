import { PitchDetector } from "pitchy";

const WINDOW = 2048;
const MIN_CLARITY = 0.9;
const MIN_HZ = 60;
const MAX_HZ = 1400;
/** Quieter windows are not analysed; low enough for a condenser mic at arm's length. */
export const MIN_DB = -60;

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
    private readonly ctx: AudioContext,
    private readonly stream: MediaStream,
    private readonly source: MediaStreamAudioSourceNode,
    private readonly analyser: AnalyserNode,
  ) {
    this.detector.minVolumeDecibels = MIN_DB;
  }

  /** Open an input device; "" is the system default. */
  static async open(ctx: AudioContext, deviceId: string): Promise<Mic> {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
        // the browser's voice processing smears pitch and fights sustained notes
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = WINDOW;
    source.connect(analyser);
    return new Mic(ctx, stream, source, analyser);
  }

  private get track(): MediaStreamTrack | undefined {
    return this.stream.getAudioTracks()[0];
  }

  get label(): string {
    return this.track?.label ?? "microphone";
  }

  get deviceId(): string {
    return this.track?.getSettings().deviceId ?? "";
  }

  /** Input latency the browser reports for the track, if any. */
  get reportedLatency(): number {
    const settings = this.track?.getSettings() as (MediaTrackSettings & { latency?: number }) | undefined;
    return settings?.latency ?? 0;
  }

  /** Level of the latest window in dBFS (RMS), and its pitch if it has a clear one. */
  read(): { db: number; pitch: PitchReading | null } {
    this.analyser.getFloatTimeDomainData(this.buffer);
    let sum = 0;
    for (const v of this.buffer) sum += v * v;
    const db = 10 * Math.log10(sum / WINDOW || 1e-12);
    const [hz, clarity] = this.detector.findPitch(this.buffer, this.ctx.sampleRate);
    if (clarity < MIN_CLARITY || hz < MIN_HZ || hz > MAX_HZ) return { db, pitch: null };
    return {
      db,
      pitch: { midi: 69 + 12 * Math.log2(hz / 440), time: this.ctx.currentTime - WINDOW / 2 / this.ctx.sampleRate },
    };
  }

  close(): void {
    this.source.disconnect();
    this.stream.getTracks().forEach(t => t.stop());
  }
}
