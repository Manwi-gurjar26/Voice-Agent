import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

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
