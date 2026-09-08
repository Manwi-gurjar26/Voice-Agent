import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    environment: "jsdom",
    // Without an explicit URL jsdom runs on `about:blank`, which is an opaque
    // origin — and Web Storage is unavailable on an opaque origin, so
    // `window.localStorage` is simply undefined. Every test that touches the
    // stored session (auth-storage, api, auth-context, both auth pages) then
    // fails on `localStorage.clear()` before it asserts anything. Vitest
    // supplied a default here in v2; v4 does not.
    environmentOptions: {
      jsdom: { url: "http://localhost:3000" },
    },
    setupFiles: ["./test-setup.ts"],
    globals: false,
    css: false,
    env: {
      NEXT_PUBLIC_API_BASE_URL: "https://api.example.com/api/v1",
    },
  },
});
