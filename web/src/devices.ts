import { listDevices } from "./audio";

/** A <select> of audio devices of one kind, remembering the choice across visits.
 *  Labels only appear once the page has microphone permission, so it is refreshed
 *  after the mic opens and whenever devices come and go. */
export class DevicePicker {
  constructor(
    private readonly select: HTMLSelectElement,
    private readonly kind: "audioinput" | "audiooutput",
    private readonly storageKey: string,
  ) {
    this.select.addEventListener("change", () => this.remember());
  }

  get value(): string {
    return this.select.value;
  }

  /** The chosen device's name as listed. */
  get label(): string {
    return this.select.selectedOptions[0]?.text ?? "System default";
  }

  /** The stored choice, before the device list is known. */
  get saved(): string {
    try {
      return localStorage.getItem(this.storageKey) ?? "";
    } catch {
      return "";
    }
  }

  async refresh(): Promise<void> {
    const devices = await listDevices(this.kind);
    const wanted = this.select.value || this.saved;
    const noun = this.kind === "audioinput" ? "Microphone" : "Output";
    const options = [new Option("System default", "")];
    devices
      // Chrome on Windows lists the default and communications devices again as aliases
      .filter(d => d.deviceId !== "default" && d.deviceId !== "communications")
      .forEach((d, i) => options.push(new Option(d.label || `${noun} ${i + 1}`, d.deviceId)));
    this.select.replaceChildren(...options);
    this.select.value = options.some(o => o.value === wanted) ? wanted : "";
  }

  private remember(): void {
    try {
      localStorage.setItem(this.storageKey, this.select.value);
    } catch {
      // storage unavailable: the choice lasts for this visit only
    }
  }
}
