import { useState } from "preact/hooks";
import type { JSX } from "preact";
import { SendIcon } from "../icons";
import { MicButton } from "./MicButton";

interface ComposerProps {
  disabled: boolean;
  onSend: (content: string) => void;
  voiceEnabled?: boolean;
  onVoiceMessage?: (audio: Blob, filename: string) => void;
  onVoiceError?: (message: string) => void;
}

export function Composer({
  disabled,
  onSend,
  voiceEnabled = false,
  onVoiceMessage,
  onVoiceError,
}: ComposerProps) {
  const [value, setValue] = useState("");

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  function handleKeyDown(event: JSX.TargetedKeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter inserts a newline — standard chat-input
    // convention, matches what visitors already expect from every other
    // chat product.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div class="va-composer">
      <textarea
        rows={1}
        value={value}
        placeholder="Type a message…"
        disabled={disabled}
        onInput={(e) => setValue((e.target as HTMLTextAreaElement).value)}
        onKeyDown={handleKeyDown}
        aria-label="Message"
      />
      {voiceEnabled && onVoiceMessage && onVoiceError && (
        <MicButton disabled={disabled} onRecordingComplete={onVoiceMessage} onError={onVoiceError} />
      )}
      <button
        type="button"
        class="va-send-button"
        disabled={disabled || value.trim() === ""}
        onClick={submit}
        aria-label="Send message"
      >
        <SendIcon />
      </button>
    </div>
  );
}
