import { expect, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";

/**
 * Signing in for end-to-end tests: the real flow -- a password, then the
 * six-digit code emailed to the account. A development backend
 * (RESEARCHNEXUS_ENVIRONMENT=development, which `python start.py` sets)
 * "sends" email by printing it and keeping it in its development mailbox,
 * which answers only this machine; that is where these helpers read the
 * code. No such mailbox exists on a staging or production server.
 */

export const API = "http://localhost:8000";
// the account the shared fixture signs in as (test values for the local dev server only)
export const TEST_EMAIL = "playwright@researchnexus.dev";
export const TEST_NAME = "Playwright Reader";
export const TEST_PASSWORD = "Tidal-pools-9!";

/** The newest code emailed to `email` since `after` (waiting up to
 * `timeout` ms for it), or null. */
export async function codeFor(request: APIRequestContext, email: string, after: string, timeout = 10_000): Promise<string | null> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const resp = await request.get(`${API}/api/v1/dev/mailbox`, { params: { email } });
    if (resp.ok()) {
      const { messages } = (await resp.json()) as { messages: { text: string; sent_at: string }[] };
      const code = messages.filter((m) => Date.parse(m.sent_at) > Date.parse(after)).map((m) => /\b(\d{6})\b/.exec(m.text)?.[1]).find(Boolean);
      if (code) return code;
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  return null;
}

export async function latestCode(request: APIRequestContext, email: string, after: string): Promise<string> {
  const code = await codeFor(request, email, after);
  expect(code, `a code emailed to ${email}`).not.toBeNull();
  return code!;
}

export function justBefore(): string {
  return new Date(Date.now() - 1000).toISOString();
}

/** Sign `request`'s browser context in: password, then the emailed code.
 * The first time, the account is made -- or, when it is one made before
 * passwords (or with another password), claimed through "Forgot password",
 * as a person would. The session cookie lands in the context. */
export async function signInViaApi(request: APIRequestContext, email = TEST_EMAIL, password = TEST_PASSWORD, name = TEST_NAME): Promise<void> {
  let since = justBefore();
  const login = await request.post(`${API}/api/v1/auth/login`, { data: { email, password } });
  if (login.ok()) {
    const { challenge_id } = await login.json();
    const verified = await request.post(`${API}/api/v1/auth/verify`, { data: { challenge_id, code: await latestCode(request, email, since) } });
    expect(verified.ok(), `verifying ${email}: ${await verified.text()}`).toBe(true);
    return;
  }
  expect(login.status(), `signing in ${email}: ${await login.text()}`).toBe(401);

  since = justBefore();
  const forgot = await request.post(`${API}/api/v1/auth/password/forgot`, { data: { email } });
  expect(forgot.ok(), `resetting ${email}: ${await forgot.text()}`).toBe(true);
  const resetCode = await codeFor(request, email, since, 3_000);
  if (resetCode) {
    const reset = await request.post(`${API}/api/v1/auth/password/reset`, {
      data: { challenge_id: (await forgot.json()).challenge_id, code: resetCode, password },
    });
    expect(reset.ok(), `setting ${email}'s password: ${await reset.text()}`).toBe(true);
    return;
  }

  since = justBefore();
  const signup = await request.post(`${API}/api/v1/auth/signup`, { data: { name, email, password } });
  expect(signup.ok(), `signing up ${email}: ${await signup.text()}`).toBe(true);
  const verified = await request.post(`${API}/api/v1/auth/verify`, {
    data: { challenge_id: (await signup.json()).challenge_id, code: await latestCode(request, email, since) },
  });
  expect(verified.ok(), `verifying ${email}: ${await verified.text()}`).toBe(true);
}

/** The CSRF header a state-changing API call from the test needs, read from
 * the context's cookies (as the page does). */
export async function csrfHeaders(context: BrowserContext): Promise<Record<string, string>> {
  const cookie = (await context.cookies(API)).find((c) => c.name.endsWith("rn_csrf"));
  return cookie ? { "X-CSRF-Token": cookie.value } : {};
}

/** POST to the API as the page's signed-in user. */
export async function apiPost(page: Page, path: string, data: unknown) {
  return page.request.post(`${API}${path}`, { data, headers: await csrfHeaders(page.context()) });
}
