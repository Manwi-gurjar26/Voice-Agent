import { defineConfig } from "vite";
import preact from "@preact/preset-vite";
import { resolve } from "node:path";

// Builds a single self-contained IIFE file — the whole point of this widget
// is that a customer drops one <script src=...> tag onto an arbitrary page
// with no module loader, no bundler, no assumptions about what else is
// running there. Code-splitting or ESM output would break that contract.
export default defineConfig({
  plugins: [preact()],
  build: {
    outDir: "dist",
    // No leftover module-preload / other chunks — a single file, always.
    cssCodeSplit: false,
    lib: {
      entry: resolve(__dirname, "src/main.tsx"),
      formats: ["iife"],
      name: "__voiceAgentWidgetLoaded", // never intentionally read by anything
      fileName: () => "widget.js",
    },
    rollupOptions: {
      output: {
        // Keep this predictable — app/schemas/agent.py's embed_snippet
        // points at exactly this filename via settings.widget_cdn_url.
        entryFileNames: "widget.js",
      },
    },
    // Widget code + inlined CSS as a string only — no separate widget.css to
    // forget to include (see src/styles.ts for how it's injected).
    minify: "esbuild",
  },
});
