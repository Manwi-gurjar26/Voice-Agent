import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearAuth, isAccessTokenFresh, loadAuth, storeAuth } from "./auth-storage";

const KEY = "voiceagent-dashboard:auth";

describe("auth-storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("returns null when nothing is stored", () => {
    expect(loadAuth()).toBeNull();
  });

  it("round-trips a stored token pair", () => {
    storeAuth({ access_token: "acc_1", refresh_token: "ref_1", expires_in: 1800 });
    const loaded = loadAuth();
    expect(loaded?.accessToken).toBe("acc_1");
    expect(loaded?.refreshToken).toBe("ref_1");
    expect(loaded?.accessExpiresAt).toBeGreaterThan(Date.now());
  });

  it("treats malformed stored JSON as absent rather than throwing", () => {
    window.localStorage.setItem(KEY, "{not json");
    expect(loadAuth()).toBeNull();
  });

  it("treats a stored value missing required fields as absent", () => {
    window.localStorage.setItem(KEY, JSON.stringify({ accessToken: "acc" }));
    expect(loadAuth()).toBeNull();
  });

  it("clearAuth removes the stored session", () => {
    storeAuth({ access_token: "acc_1", refresh_token: "ref_1", expires_in: 1800 });
    clearAuth();
    expect(loadAuth()).toBeNull();
  });

  describe("isAccessTokenFresh", () => {
    it("is true for a token well within its lifetime", () => {
      storeAuth({ access_token: "acc", refresh_token: "ref", expires_in: 1800 });
      expect(isAccessTokenFresh(loadAuth()!)).toBe(true);
    });

    it("is false once within the expiry skew window", () => {
      storeAuth({ access_token: "acc", refresh_token: "ref", expires_in: 1 });
      expect(isAccessTokenFresh(loadAuth()!)).toBe(false);
    });

    it("is false for an already-expired token", () => {
      storeAuth({ access_token: "acc", refresh_token: "ref", expires_in: -10 });
      expect(isAccessTokenFresh(loadAuth()!)).toBe(false);
    });
  });

  describe("when localStorage throws", () => {
    let original: Storage;

    beforeEach(() => {
      original = window.localStorage;
      Object.defineProperty(window, "localStorage", {
        configurable: true,
        value: {
          getItem() {
            throw new DOMException("blocked");
          },
          setItem() {
            throw new DOMException("blocked");
          },
          removeItem() {
            throw new DOMException("blocked");
          },
        },
      });
    });

    afterEach(() => {
      Object.defineProperty(window, "localStorage", { configurable: true, value: original });
    });

    it("degrades to no-ops instead of throwing", () => {
      expect(() => storeAuth({ access_token: "a", refresh_token: "b", expires_in: 100 })).not.toThrow();
      expect(loadAuth()).toBeNull();
      expect(() => clearAuth()).not.toThrow();
    });
  });
});
