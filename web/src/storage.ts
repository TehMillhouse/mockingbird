/** Settings remembered in the browser, under "mockingbird.<key>". Storage can be
 *  unavailable (a private window, blocked site data): reads then return null and
 *  writes do nothing, so every setting needs a default. */

const PREFIX = "mockingbird.";

export function recall(key: string): string | null {
  try {
    return localStorage.getItem(PREFIX + key);
  } catch {
    return null;
  }
}

export function remember(key: string, value: string): void {
  try {
    localStorage.setItem(PREFIX + key, value);
  } catch {
    // nothing to remember it in
  }
}

/** A JSON object setting; an unreadable one counts as empty. */
export function recallJson<T extends object>(key: string): Partial<T> {
  try {
    const value = JSON.parse(recall(key) ?? "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

export function rememberJson(key: string, value: object): void {
  remember(key, JSON.stringify(value));
}
