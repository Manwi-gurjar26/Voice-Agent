import { render } from "preact";
import { App } from "./App";
import cssText from "./styles.css?inline";

// Must run synchronously, at the very top, before any `await` — per spec,
// document.currentScript is only reliably associated with this <script>
// element during its initial synchronous execution. It remains valid for an
// `async` script (a common point of confusion), but only up to the first
// yield point; reading it after an await here would silently return null.
const thisScript = document.currentScript as HTMLScriptElement | null;

// document.currentScript is always null for ES module scripts — a browser
// platform behavior, not a bug to work around. Only relevant during `npm run
// dev` (Vite serves everything as native ESM there); the production IIFE
// build is a classic script, where thisScript above works normally. The dev
// harness (index.html) sets this global before importing main.tsx so local
// development can still exercise the real mount path. import.meta.env.DEV is
// statically replaced with `false` in production builds, so esbuild
// dead-code-eliminates this whole branch — it does not ship.
declare global {
  interface Window {
    __VOICE_AGENT_DEV__?: { publicKey: string; apiBaseUrl: string };
  }
}

function readConfig(): { publicKey: string; apiBaseUrl: string } | null {
  const devOverride = import.meta.env.DEV ? window.__VOICE_AGENT_DEV__ : undefined;

  const publicKey = devOverride?.publicKey || thisScript?.dataset.agentKey;
  if (!publicKey) {
    console.error(
      "[voice-agent-widget] missing data-agent-key attribute on the widget <script> tag — not mounting.",
    );
    return null;
  }
  // Falls back to the build-time default; data-api-base lets one built
  // bundle be pointed at a different backend without a rebuild (useful for
  // local development against a non-default API port).
  const apiBaseUrl =
    devOverride?.apiBaseUrl || thisScript?.dataset.apiBase || import.meta.env.VITE_API_BASE_URL;
  if (!apiBaseUrl) {
    console.error(
      "[voice-agent-widget] no API base URL configured (VITE_API_BASE_URL at build time, " +
        "or data-api-base on the <script> tag) — not mounting.",
    );
    return null;
  }
  return { publicKey, apiBaseUrl };
}

function mount(publicKey: string, apiBaseUrl: string): void {
  // Guard against double-mount: a customer accidentally including the
  // snippet twice, or a SPA re-running injected scripts on navigation,
  // should not produce two floating launchers for the same agent.
  const marker = `data-voice-agent-mounted-${publicKey}`;
  if (document.documentElement.hasAttribute(marker)) return;
  document.documentElement.setAttribute(marker, "true");

  const host = document.createElement("div");
  host.style.all = "initial"; // isolate the host element itself, belt-and-suspenders with the shadow root
  const shadow = host.attachShadow({ mode: "open" });

  const style = document.createElement("style");
  style.textContent = cssText;
  shadow.appendChild(style);

  const mountPoint = document.createElement("div");
  shadow.appendChild(mountPoint);

  document.body.appendChild(host);
  render(<App baseUrl={apiBaseUrl} publicKey={publicKey} />, mountPoint);
}

function start(): void {
  const config = readConfig();
  if (!config) return;

  if (document.body) {
    mount(config.publicKey, config.apiBaseUrl);
  } else {
    // An `async` script can in principle still run before <body> exists,
    // e.g. if placed very early in <head>. Wait for the DOM rather than
    // failing on a null document.body.
    document.addEventListener("DOMContentLoaded", () => mount(config.publicKey, config.apiBaseUrl), {
      once: true,
    });
  }
}

start();
