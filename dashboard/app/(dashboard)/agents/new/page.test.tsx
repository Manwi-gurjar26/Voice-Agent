import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  createAgent: vi.fn(),
  formatApiError: (err: unknown) => (err instanceof Error ? err.message : "Something went wrong."),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { createAgent } from "@/lib/api";
import { toast } from "sonner";
import NewAgentPage from "./page";

describe("NewAgentPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("requires a name before submitting", async () => {
    const user = userEvent.setup();
    render(<NewAgentPage />);

    await user.click(screen.getByRole("button", { name: /create agent/i }));

    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
    expect(createAgent).not.toHaveBeenCalled();
  });

  it("creates an agent with defaults and redirects to its edit page", async () => {
    vi.mocked(createAgent).mockResolvedValue({ id: "new-agent-1", name: "Support Bot" } as never);
    const user = userEvent.setup();
    render(<NewAgentPage />);

    await user.type(screen.getByLabelText(/^name$/i), "Support Bot");
    await user.click(screen.getByRole("button", { name: /create agent/i }));

    await waitFor(() =>
      expect(createAgent).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Support Bot",
          effort: "medium",
          max_output_tokens: 2048,
          voice_enabled: false,
          allowed_origins: [],
        }),
      ),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/agents/new-agent-1"));
  });

  it("parses one-per-line allowed origins into an array", async () => {
    vi.mocked(createAgent).mockResolvedValue({ id: "a1", name: "Bot" } as never);
    const user = userEvent.setup();
    render(<NewAgentPage />);

    await user.type(screen.getByLabelText(/^name$/i), "Bot");
    await user.type(
      screen.getByLabelText(/allowed origins/i),
      "https://a.example.com\nhttps://b.example.com",
    );
    await user.click(screen.getByRole("button", { name: /create agent/i }));

    await waitFor(() =>
      expect(createAgent).toHaveBeenCalledWith(
        expect.objectContaining({
          allowed_origins: ["https://a.example.com", "https://b.example.com"],
        }),
      ),
    );
  });

  it("shows a toast on failure and does not navigate away", async () => {
    vi.mocked(createAgent).mockRejectedValue(new Error("name already used"));
    const user = userEvent.setup();
    render(<NewAgentPage />);

    await user.type(screen.getByLabelText(/^name$/i), "Bot");
    await user.click(screen.getByRole("button", { name: /create agent/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("name already used"));
    expect(push).not.toHaveBeenCalled();
  });
});
