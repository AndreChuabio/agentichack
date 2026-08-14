/**
 * The caller's own Vercel AI Gateway key, held in the browser.
 *
 * Merit never stores this server-side: it lives in localStorage and rides on
 * the X-LLM-Key header of each request, which is the posture backend/byok.py
 * documents. Nothing here writes it to a cookie or sends it anywhere but the
 * Merit API.
 *
 * It is required only by the surfaces that read whole repositories, because a
 * repo bundle is capped at 600K tokens and a rush of users on Merit's key would
 * be a bill with no ceiling. Everything else falls back to Merit's key and is
 * capped instead, so most of the product works without ever setting this.
 */

const STORAGE_KEY = "merit.llm_key";

/** The stored key, or empty when there is none or we are server-side. */
export function getLlmKey(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    // Private browsing and blocked storage both throw rather than returning
    // null. Treat either as "no key" instead of breaking every request.
    return "";
  }
}

/** Store the key, or clear it when given an empty string. */
export function setLlmKey(key: string): void {
  if (typeof window === "undefined") return;
  try {
    const trimmed = key.trim();
    if (trimmed) {
      window.localStorage.setItem(STORAGE_KEY, trimmed);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // Nothing useful to do: the request will simply fall back to Merit's key
    // where that is allowed, and be refused where it is not.
  }
  for (const listener of listeners) listener();
}

// A minimal store so components can read this through useSyncExternalStore
// rather than copying it into React state inside an effect. localStorage does
// not exist during the server pass, so the server snapshot is always false and
// the client corrects it after hydration without a mismatch.
type Listener = () => void;
const listeners = new Set<Listener>();

/** Subscribe to key changes. Returns the unsubscribe function. */
export function subscribeLlmKey(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Whether a key is set, as a boolean rather than the key itself.
 *
 * A stable primitive, which useSyncExternalStore requires, and it means a
 * component can render the right state without ever holding the secret.
 */
export function hasLlmKey(): boolean {
  return Boolean(getLlmKey());
}

/** The server-render snapshot: no browser storage exists there. */
export function noLlmKey(): boolean {
  return false;
}
