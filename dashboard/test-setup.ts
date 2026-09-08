import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Node 20.9+ defines its own `globalThis.localStorage` accessor, which returns
// undefined unless the process was started with `--localstorage-file`. That
// accessor shadows the one jsdom installs, so `window.localStorage` is
// undefined inside tests while `window.sessionStorage` — which Node does not
// define — works fine. Every test that touches the stored session then dies on
// `localStorage.clear()` before asserting anything.
//
// Replacing it with a minimal in-memory Storage is the fix rather than passing
// `--localstorage-file`: that flag would give the tests Node's file-backed
// implementation, shared across the whole run and persisted to disk, which is
// the opposite of the per-test isolation these tests rely on.
if (!globalThis.localStorage) {
  const store = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return store.size;
    },
    key: (index: number) => [...store.keys()][index] ?? null,
    getItem: (key: string) => store.get(String(key)) ?? null,
    setItem: (key: string, value: string) => void store.set(String(key), String(value)),
    removeItem: (key: string) => void store.delete(String(key)),
    clear: () => store.clear(),
  };
  Object.defineProperty(globalThis, "localStorage", {
    value: storage,
    configurable: true,
    writable: true,
  });
}

// jsdom implements no CSS media query engine at all, so `window.matchMedia`
// is simply absent — not a browser behaviour worth coding defensively
// around (every browser since IE10 has it), just a gap in the test
// environment. Components that adapt to `prefers-reduced-motion` /
// `hover: hover` (see components/visuals/tilt.tsx) would otherwise throw on
// mount here while working fine in every real browser.
//
// Defaults to "does not match", which is the conservative branch: reduced
// motion off, pointer effects disabled.
if (!window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

afterEach(() => {
  cleanup();
});
