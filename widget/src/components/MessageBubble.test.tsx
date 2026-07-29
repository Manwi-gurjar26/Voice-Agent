import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../types";
import { MessageBubble } from "./MessageBubble";

function message(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return { id: "m1", role: "assistant", content: "Hello!", citations: null, status: "complete", ...overrides };
}

describe("MessageBubble", () => {
  it("renders the message content", () => {
    render(<MessageBubble message={message({ content: "Hi there" })} />);
    expect(screen.getByText("Hi there")).toBeInTheDocument();
  });

  it("shows a typing indicator instead of text while streaming with empty content", () => {
    render(<MessageBubble message={message({ status: "streaming", content: "" })} />);
    expect(screen.getByLabelText("Assistant is typing")).toBeInTheDocument();
  });

  it("shows partial content while streaming once text has arrived", () => {
    render(<MessageBubble message={message({ status: "streaming", content: "Hel" })} />);
    expect(screen.getByText("Hel")).toBeInTheDocument();
    expect(screen.queryByLabelText("Assistant is typing")).not.toBeInTheDocument();
  });

  it("marks a failed message visually distinct", () => {
    const { container } = render(<MessageBubble message={message({ status: "failed", content: "oops" })} />);
    expect(container.querySelector(".va-failed")).toBeInTheDocument();
  });

  it("renders citation chips when present", () => {
    render(
      <MessageBubble
        message={message({
          citations: [
            { document_id: "d1", title: "Doc One" },
            { document_id: "d2", title: "Doc Two" },
          ],
        })}
      />,
    );
    expect(screen.getByText("Doc One")).toBeInTheDocument();
    expect(screen.getByText("Doc Two")).toBeInTheDocument();
  });

  it("renders no citations block when citations are null or empty", () => {
    const { container: c1 } = render(<MessageBubble message={message({ citations: null })} />);
    expect(c1.querySelector(".va-citations")).not.toBeInTheDocument();

    const { container: c2 } = render(<MessageBubble message={message({ citations: [] })} />);
    expect(c2.querySelector(".va-citations")).not.toBeInTheDocument();
  });
});
