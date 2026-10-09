import { afterEach, describe, expect, it, vi } from "vitest";
import { csrfHeader, csrfToken, getAuthEpoch, notifyAuthChanged, subscribeToAuth } from "./session";
import { emailProblem, passwordRules, safeNext } from "@/components/auth/AuthUi";
import { deviceName } from "@/app/settings/account";

function setCookie(value: string) {
  document.cookie = value;
}

describe("the CSRF token", () => {
  afterEach(() => {
    for (const name of ["rn_csrf", "__Host-rn_csrf", "other"]) document.cookie = `${name}=; max-age=0`;
  });

  it("is read from the readable CSRF cookie, and sent only with state-changing requests", () => {
    setCookie("other=1");
    setCookie("rn_csrf=abc123");
    expect(csrfToken()).toBe("abc123");
    expect(csrfHeader("POST")).toEqual({ "X-CSRF-Token": "abc123" });
    expect(csrfHeader("DELETE")).toEqual({ "X-CSRF-Token": "abc123" });
    expect(csrfHeader("GET")).toEqual({});
  });

  it("is absent when signed out", () => {
    expect(csrfToken()).toBeNull();
    expect(csrfHeader("POST")).toEqual({});
  });
});

describe("auth changes", () => {
  it("bump the epoch the data cache is keyed by, and tell subscribers", () => {
    const seen = vi.fn();
    const stop = subscribeToAuth(seen);
    const before = getAuthEpoch();
    notifyAuthChanged();
    expect(getAuthEpoch()).toBe(before + 1);
    expect(seen).toHaveBeenCalledTimes(1);
    stop();
  });
});

describe("after signing in, the app goes", () => {
  it("only to a path on this site", () => {
    expect(safeNext("/workspace/ws_1/chat")).toBe("/workspace/ws_1/chat");
    expect(safeNext(null)).toBe("/home");
    expect(safeNext("https://evil.example/phish")).toBe("/home");
    expect(safeNext("//evil.example")).toBe("/home");
    expect(safeNext("/\\evil.example")).toBe("/home");
    expect(safeNext("javascript:alert(1)")).toBe("/home");
  });
});

describe("the sign-up form's checks", () => {
  it("mirror the server's password rules", () => {
    const ok = (password: string, email = "ada@example.org") => passwordRules(password, email).every((r) => r.ok);
    expect(ok("Tidal-pools-9")).toBe(true);
    expect(ok("short-1")).toBe(false);
    expect(ok("onlyletterslong")).toBe(false);
    expect(ok("ada-loves-math-1", "ada@example.org")).toBe(true); // "ada" is too short to count
    expect(ok("lovelace-2026!", "lovelace@example.org")).toBe(false);
  });

  it("say what is wrong with an email", () => {
    expect(emailProblem("")).toMatch(/Enter your email/);
    expect(emailProblem("not-an-email")).toMatch(/valid email/);
    expect(emailProblem(" ada@example.org ")).toBeNull();
  });
});

describe("a signed-in device", () => {
  it("is named by its browser and system", () => {
    expect(deviceName("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36 Edg/140.0").label).toBe(
      "Edge on Windows",
    );
    expect(deviceName("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")).toEqual({
      label: "Safari on iOS",
      mobile: true,
    });
    expect(deviceName("Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0").label).toBe("Firefox on Linux");
    expect(deviceName(null).label).toBe("Unknown device");
    expect(deviceName("python-httpx/0.27").label).toBe("Another app");
  });
});
