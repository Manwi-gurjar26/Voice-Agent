import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/preact";
import { afterEach } from "vitest";

// jsdom doesn't implement the Blob URL APIs at all (every real browser
// does) — stubbed here once for every test, rather than per test file,
// since it's an environment gap, not something under test.
if (typeof URL.createObjectURL !== "function") {
  URL.createObjectURL = () => `blob:mock-${Math.random().toString(36).slice(2)}`;
}
if (typeof URL.revokeObjectURL !== "function") {
  URL.revokeObjectURL = () => {};
}

afterEach(() => {
  cleanup();
});
