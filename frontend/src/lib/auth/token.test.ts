import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearToken, getToken, setToken } from "./token";

describe("token storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("returns null when no token is stored", () => {
    expect(getToken()).toBeNull();
  });

  it("round-trips a token through setToken/getToken", () => {
    setToken("jwt.abc.123");
    expect(getToken()).toBe("jwt.abc.123");
  });

  it("clearToken removes the stored token", () => {
    setToken("jwt.abc.123");
    clearToken();
    expect(getToken()).toBeNull();
  });

  it("setToken and clearToken both announce the change via researchnexus:auth", () => {
    const handler = vi.fn();
    window.addEventListener("researchnexus:auth", handler);
    setToken("jwt.abc.123");
    clearToken();
    expect(handler).toHaveBeenCalledTimes(2);
    window.removeEventListener("researchnexus:auth", handler);
  });
});
