import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  clearSession,
  loadStoredConversationId,
  loadStoredSession,
  storeConversationId,
  storeSession,
} from "./storage";

const KEY = "agt_pub_test123";

describe("storage", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("returns null when nothing is stored", () => {
    expect(loadStoredSession(KEY)).toBeNull();
    expect(loadStoredConversationId(KEY)).toBeNull();
  });

  it("round-trips a stored session", () => {
    storeSession(KEY, "tok_abc", 3600);
    const loaded = loadStoredSession(KEY);
    expect(loaded?.token).toBe("tok_abc");
    expect(loaded?.expiresAt).toBeGreaterThan(Date.now());
  });

  it("rejects a locally-expired session without touching the network", () => {
    sessionStorage.setItem(
      `voiceagent:${KEY}:session`,
      JSON.stringify({ token: "tok_old", expiresAt: Date.now() - 1000 }),
    );
    expect(loadStoredSession(KEY)).toBeNull();
  });

  it("treats malformed stored JSON as absent rather than throwing", () => {
    sessionStorage.setItem(`voiceagent:${KEY}:session`, "{not json");
    expect(loadStoredSession(KEY)).toBeNull();
  });

  it("treats a stored value missing required fields as absent", () => {
    sessionStorage.setItem(`voiceagent:${KEY}:session`, JSON.stringify({ token: "tok" }));
    expect(loadStoredSession(KEY)).toBeNull();
  });

  it("namespaces storage per public key", () => {
    storeSession(KEY, "tok_a", 3600);
    storeSession("agt_pub_other", "tok_b", 3600);
    expect(loadStoredSession(KEY)?.token).toBe("tok_a");
    expect(loadStoredSession("agt_pub_other")?.token).toBe("tok_b");
  });

  it("round-trips a stored conversation id", () => {
    storeConversationId(KEY, "conv_1");
    expect(loadStoredConversationId(KEY)).toBe("conv_1");
  });

  it("clearSession removes both the session and the conversation id", () => {
    storeSession(KEY, "tok_abc", 3600);
    storeConversationId(KEY, "conv_1");

    clearSession(KEY);

    expect(loadStoredSession(KEY)).toBeNull();
    expect(loadStoredConversationId(KEY)).toBeNull();
  });

  it("clearSession does not affect a different public key's storage", () => {
    storeSession(KEY, "tok_abc", 3600);
    storeConversationId("agt_pub_other", "conv_other");

    clearSession(KEY);

    expect(loadStoredConversationId("agt_pub_other")).toBe("conv_other");
  });

  describe("when sessionStorage throws", () => {
    let original: Storage;

    beforeEach(() => {
      original = window.sessionStorage;
      Object.defineProperty(window, "sessionStorage", {
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
      Object.defineProperty(window, "sessionStorage", { configurable: true, value: original });
    });

    it("degrades to no-ops instead of throwing", () => {
      expect(() => storeSession(KEY, "tok", 3600)).not.toThrow();
      expect(loadStoredSession(KEY)).toBeNull();
      expect(loadStoredConversationId(KEY)).toBeNull();
      expect(() => storeConversationId(KEY, "conv")).not.toThrow();
      expect(() => clearSession(KEY)).not.toThrow();
    });
  });
});
