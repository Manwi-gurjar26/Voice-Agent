import { useEffect, useRef } from "preact/hooks";
import type { ChatMessage } from "../types";
import { MessageBubble } from "./MessageBubble";

interface MessageListProps {
  greeting: string;
  messages: ChatMessage[];
}

export function MessageList({ greeting, messages }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to the newest content — including on every streamed delta,
  // since message text mutates in place rather than adding new elements.
  useEffect(() => {
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  });

  return (
    <div class="va-messages" ref={containerRef}>
      {greeting && (
        <MessageBubble
          message={{ id: "greeting", role: "assistant", content: greeting, citations: null, status: "complete" }}
        />
      )}
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
    </div>
  );
}
