import type { ChatMessage } from "../types";

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isStreamingEmpty = message.status === "streaming" && message.content === "";

  return (
    <div class={`va-bubble-row va-role-${message.role}`}>
      <div>
        <div class={`va-bubble${message.status === "failed" ? " va-failed" : ""}`}>
          {isStreamingEmpty ? (
            <span class="va-typing" aria-label="Assistant is typing">
              <span />
              <span />
              <span />
            </span>
          ) : (
            message.content
          )}
        </div>
        {message.citations && message.citations.length > 0 && (
          <div class="va-citations">
            {message.citations.map((c) => (
              <span class="va-citation-chip" key={c.document_id}>
                {c.title}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
