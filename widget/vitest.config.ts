import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

// Separate from vite.config.ts deliberately — that one is tuned for the
// single-file IIFE production build (lib mode, no code splitting), and
// mixing test-runner config into it risks the two interacting in ways that
// are annoying to debug.
export default defineConfig({
  plugins: [preact()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
