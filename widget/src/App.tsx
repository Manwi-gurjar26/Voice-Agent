import { useState } from "preact/hooks";
import type { JSX } from "preact";
import { createApiClient } from "./api";
import { useChat } from "./hooks/useChat";
import { Launcher } from "./components/Launcher";
import { ChatPanel } from "./components/ChatPanel";

interface AppProps {
  baseUrl: string;
  publicKey: string;
}

function resolvePosition(rawPosition: string | undefined): "left" | "right" {
  return rawPosition === "bottom-left" ? "left" : "right";
}

export function App({ baseUrl, publicKey }: AppProps) {
  // Created once per mount, not per render — a fresh client every render
  // would be harmless functionally (it's stateless) but wasteful.
  const [api] = useState(() => createApiClient(baseUrl, publicKey));
  const [open, setOpen] = useState(false);
  const chat = useChat(api, publicKey);

  // Bootstrapping is brief (a couple of round trips) and unavailable is a
  // configuration/outage problem for the business owner to notice via
  // devtools — see useChat's console.error. Neither state renders anything
  // visible to the site visitor.
  if (chat.status !== "ready" || !chat.config) return null;

  const { name, theme } = chat.config;
  const position = resolvePosition(theme.position);
  const rootStyle = {
    "--va-primary": theme.primaryColor || "#2f6fed",
    "--va-bubble-radius": `${theme.bubbleRadius ?? 16}px`,
  } as JSX.CSSProperties;

  return (
    <div class="va-root" style={rootStyle}>
      {open && (
        <ChatPanel
          position={position}
          agentName={name}
          greeting={chat.config.greeting}
          messages={chat.messages}
          isSending={chat.isSending}
          errorBanner={chat.errorBanner}
          onSend={chat.sendMessage}
          onClose={() => setOpen(false)}
        />
      )}
      <Launcher open={open} position={position} agentName={name} onToggle={() => setOpen((v) => !v)} />
    </div>
  );
}
