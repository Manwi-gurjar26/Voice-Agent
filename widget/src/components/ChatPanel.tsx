import type { ChatMessage } from "../types";
import { CloseIcon } from "../icons";
import { MessageList } from "./MessageList";
import { Composer } from "./Composer";
import { ErrorBanner } from "./ErrorBanner";

interface ChatPanelProps {
  position: "left" | "right";
  agentName: string;
  greeting: string;
  messages: ChatMessage[];
  isSending: boolean;
  errorBanner: string | null;
  onSend: (content: string) => void;
  onClose: () => void;
  voiceEnabled?: boolean;
  onVoiceMessage?: (audio: Blob, filename: string) => void;
  onVoiceError?: (message: string) => void;
}

export function ChatPanel({
  position,
  agentName,
  greeting,
  messages,
  isSending,
  errorBanner,
  onSend,
  onClose,
  voiceEnabled,
  onVoiceMessage,
  onVoiceError,
}: ChatPanelProps) {
  return (
    <div class={`va-panel va-pos-${position}`} role="dialog" aria-label={`Chat with ${agentName}`}>
      <div class="va-header">
        <span class="va-header-title">{agentName}</span>
        <button type="button" class="va-close-button" onClick={onClose} aria-label="Close chat">
          <CloseIcon />
        </button>
      </div>
      <MessageList greeting={greeting} messages={messages} />
      {errorBanner && <ErrorBanner message={errorBanner} />}
      <Composer
        disabled={isSending}
        onSend={onSend}
        voiceEnabled={voiceEnabled}
        onVoiceMessage={onVoiceMessage}
        onVoiceError={onVoiceError}
      />
    </div>
  );
}
