import { fireEvent, render, screen } from "@testing-library/preact";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";

describe("Composer", () => {
  it("sends trimmed content and clears the textarea on button click", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Composer disabled={false} onSend={onSend} />);

    const textarea = screen.getByLabelText("Message");
    await user.type(textarea, "  hello there  ");
    await user.click(screen.getByLabelText("Send message"));

    expect(onSend).toHaveBeenCalledWith("hello there");
    expect(textarea).toHaveValue("");
  });

  it("sends on Enter and inserts a newline on Shift+Enter", async () => {
    const onSend = vi.fn();
    render(<Composer disabled={false} onSend={onSend} />);
    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement;

    fireEvent.input(textarea, { target: { value: "hi" } });
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("hi");
    expect(textarea.value).toBe("");

    fireEvent.input(textarea, { target: { value: "line1" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(onSend).toHaveBeenCalledTimes(1); // not called again
  });

  it("does not send empty or whitespace-only content", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Composer disabled={false} onSend={onSend} />);

    await user.type(screen.getByLabelText("Message"), "   ");
    expect(screen.getByLabelText("Send message")).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Send message"));

    expect(onSend).not.toHaveBeenCalled();
  });

  it("disables the textarea and send button while disabled", () => {
    render(<Composer disabled={true} onSend={vi.fn()} />);

    expect(screen.getByLabelText("Message")).toBeDisabled();
    expect(screen.getByLabelText("Send message")).toBeDisabled();
  });
});
