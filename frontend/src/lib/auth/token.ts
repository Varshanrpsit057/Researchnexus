const STORAGE_KEY = "researchnexus.token";

/**
 * The backend issues a bare bearer JWT (POST /api/v1/auth/session) with no
 * cookie, refresh token, or CSRF scheme of its own -- a stateless SPA-style
 * token, stored the way such tokens conventionally are. There is no
 * server-rendered authenticated page in this app (every authenticated
 * screen is a Client Component), so there is no SSR/cookie boundary this
 * needs to cross.
 */
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(STORAGE_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, token);
  window.dispatchEvent(new Event("researchnexus:auth"));
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
  window.dispatchEvent(new Event("researchnexus:auth"));
}
