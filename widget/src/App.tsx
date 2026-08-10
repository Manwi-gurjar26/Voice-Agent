import { useRef, useState } from "preact/hooks";
import type { JSX } from "preact";
import { createApiClient } from "./api";
import { useChat } from "./hooks/useChat";
import { Launcher } from "./components/Launcher";
import { VoiceLauncher } from "./components/VoiceLauncher";
import { ChatPanel } from "./components/ChatPanel";
import { isVoiceCaptureSupported } from "./voiceCapture";

interface AppProps {
  baseUrl: string;
  publicKey: string;
}

function resolvePosition(rawPosition: string | undefined): "left" | "right" {
  return rawPosition === "bottom-left" ? "left" : "right";
}

/** Resolves when the reply has finished being spoken — that's the cue for
 * VoiceLauncher's hands-free loop to reopen the mic, so it must also resolve
 * (rather than hang) when playback fails or is blocked by an autoplay
 * policy, otherwise the conversation would stall with the mic shut. */
function playToEnd(element: HTMLAudioElement): Promise<void> {
  return new Promise((resolve) => {
    const finish = () => {
      element.removeEventListener("ended", finish);
      element.removeEventListener("error", finish);
      resolve();
    };
    element.addEventListener("ended", finish);
    element.addEventListener("error", finish);
    element.play().catch(finish);
  });
}

export function App({ baseUrl, publicKey }: AppProps) {
  // Created once per mount, not per render — a fresh client every render
  // would be harmless functionally (it's stateless) but wasteful.
  const [api] = useState(() => createApiClient(baseUrl, publicKey));
  const [open, setOpen] = useState(false);
  const chat = useChat(api, publicKey);

  // Mic-permission/unsupported-browser errors surface through the same
  // ErrorBanner the chat pipeline itself uses (merged below), rather than a
  // second error UI — but they're not chat-pipeline state, so they live here.
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const previousAudioUrlRef = useRef<string | null>(null);

  // Bootstrapping is brief (a couple of round trips) and unavailable is a
  // configuration/outage problem for the business owner to notice via
  // devtools — see useChat's console.error. Neither state renders anything
  // visible to the site visitor.
  if (chat.status !== "ready" || !chat.config) return null;

  const { name, theme, voice_enabled } = chat.config;
  const position = resolvePosition(theme.position);
  const rootStyle = {
    "--va-primary": theme.primaryColor || "#2f6fed",
    "--va-bubble-radius": `${theme.bubbleRadius ?? 16}px`,
  } as JSX.CSSProperties;

  function handleSend(content: string) {
    setVoiceError(null);
    chat.sendMessage(content);
  }

  // The floating voice button deliberately never opens the panel on a
  // successful turn (that's the whole point of it being separate) — but a
  // mic-permission/unsupported-browser error has nowhere else to be shown,
  // since ErrorBanner only renders inside the (closed) panel.
  function handleVoiceLauncherError(message: string) {
    setVoiceError(message);
    setOpen(true);
  }

  // Awaited by VoiceLauncher: it only reopens the mic once this resolves, so
  // the agent is never recording itself while it speaks.
  async function handleVoiceMessage(audio: Blob, filename: string) {
    setVoiceError(null);
    const result = await chat.sendVoiceMessage(audio, filename);
    if (!result?.audioUrl) return;

    if (previousAudioUrlRef.current) URL.revokeObjectURL(previousAudioUrlRef.current);
    previousAudioUrlRef.current = result.audioUrl;
    if (!audioRef.current) return;
    audioRef.current.src = result.audioUrl;
    await playToEnd(audioRef.current);
  }

  /** Ending a conversation should also cut the agent off mid-sentence —
   * waiting out a reply you've already dismissed feels broken. */
  function stopSpeaking() {
    audioRef.current?.pause();
  }

  return (
    <div class="va-root" style={rootStyle}>
      {open && (
        <ChatPanel
          position={position}
          agentName={name}
          greeting={chat.config.greeting}
          messages={chat.messages}
          isSending={chat.isSending}
          errorBanner={chat.errorBanner ?? voiceError}
          onSend={handleSend}
          onClose={() => setOpen(false)}
          voiceEnabled={voice_enabled}
          onVoiceMessage={handleVoiceMessage}
          onVoiceError={setVoiceError}
        />
      )}
      {!open && voice_enabled && isVoiceCaptureSupported() && (
        <VoiceLauncher
          position={position}
          agentName={name}
          thinking={chat.isSending}
          onRecordingComplete={handleVoiceMessage}
          onConversationEnd={stopSpeaking}
          onError={handleVoiceLauncherError}
        />
      )}
      <Launcher open={open} position={position} agentName={name} onToggle={() => setOpen((v) => !v)} />
      <audio ref={audioRef} hidden />
    </div>
  );
}
