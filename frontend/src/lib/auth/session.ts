/**
 * The browser side of a session. The session itself is an httpOnly cookie
 * the server sets after the emailed code checks out -- page scripts can't
 * read it, so a script injected into the page can't steal it. What scripts
 * can read is its CSRF companion cookie, which every state-changing request
 * echoes in the `X-CSRF-Token` header (a page on another site can't read it,
 * so it can't forge that header).
 *
 * Sign-in and sign-out anywhere (this tab or another) bump an "auth epoch":
 * the data cache is keyed by it, so nothing fetched for one account is ever
 * shown to the next.
 */

const CSRF_COOKIE = /(?:^|;\s*)(?:__Host-)?rn_csrf=([^;]+)/;
const AUTH_EVENT = "researchnexus:auth";
const UNAUTHORIZED_EVENT = "researchnexus:unauthorized";
const BROADCAST_KEY = "researchnexus.auth-changed";
// where the session token lived before cookies (cleared on sight)
const LEGACY_TOKEN_KEY = "researchnexus.token";

let epoch = 0;

export function csrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = CSRF_COOKIE.exec(document.cookie);
  return match ? decodeURIComponent(match[1]) : null;
}

/** Headers a state-changing request needs (none for reads). */
export function csrfHeader(method: string): Record<string, string> {
  if (method === "GET" || method === "HEAD") return {};
  const token = csrfToken();
  return token ? { "X-CSRF-Token": token } : {};
}

/** Signed in or out here: start a fresh data cache, here and in other tabs. */
export function notifyAuthChanged(): void {
  if (typeof window === "undefined") return;
  epoch += 1;
  window.dispatchEvent(new Event(AUTH_EVENT));
  try {
    window.localStorage.setItem(BROADCAST_KEY, String(Date.now()));
  } catch {
    // storage unavailable (private mode): other tabs notice on their next request
  }
}

export function getAuthEpoch(): number {
  return epoch;
}

export function subscribeToAuth(callback: () => void): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key === BROADCAST_KEY) {
      epoch += 1;
      callback();
    }
  };
  window.addEventListener(AUTH_EVENT, callback);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(AUTH_EVENT, callback);
    window.removeEventListener("storage", onStorage);
  };
}

/** A request came back 401: the session has ended (expired, or signed out
 * elsewhere). The auth provider re-checks who is signed in. */
export function notifyUnauthorized(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
}

export function subscribeToUnauthorized(callback: () => void): () => void {
  window.addEventListener(UNAUTHORIZED_EVENT, callback);
  return () => window.removeEventListener(UNAUTHORIZED_EVENT, callback);
}

export function forgetLegacyToken(): void {
  try {
    window.localStorage.removeItem(LEGACY_TOKEN_KEY);
  } catch {
    // nothing to clear
  }
}
