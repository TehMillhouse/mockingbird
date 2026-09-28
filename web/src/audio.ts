import * as Tone from "tone";

/** Output device selection needs `AudioContext.setSinkId`, which only the native
 *  context has; Tone's default context is a wrapper without it. Tone also depends on
 *  that wrapper where the native context lacks parts of the spec (Firefox has no
 *  `AudioListener` position params), so the native context is used only where
 *  `setSinkId` exists. Imported before any Tone node is created. */
export const canChooseOutput = "setSinkId" in AudioContext.prototype;
if (canChooseOutput) Tone.setContext(new Tone.Context(new AudioContext({ latencyHint: "interactive" })));

/** The context everything runs on: native or wrapped, the parts used here behave alike. */
export const audioContext = Tone.getContext().rawContext as unknown as AudioContext;

/** Route all playback to an output device; "" is the system default. */
export async function setOutputDevice(deviceId: string): Promise<void> {
  await (audioContext as AudioContext & { setSinkId(id: string): Promise<void> }).setSinkId(deviceId);
}

export async function listDevices(kind: "audioinput" | "audiooutput"): Promise<MediaDeviceInfo[]> {
  const all = await navigator.mediaDevices.enumerateDevices();
  return all.filter(d => d.kind === kind && d.deviceId !== "");
}
