import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentRead } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  listAgents: vi.fn(),
  deleteAgent: vi.fn(),
  formatApiError: (err: unknown) => (err instanceof Error ? err.message : "Something went wrong."),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { deleteAgent, listAgents } from "@/lib/api";
import { toast } from "sonner";
import AgentsPage from "./page";

function makeAgent(overrides: Partial<AgentRead> = {}): AgentRead {
  return {
    id: "a1",
    name: "Support Bot",
    public_key: "agt_pub_1",
    status: "active",
    system_prompt: "You are helpful.",
    greeting: "Hi!",
    model: "gemini-2.5-flash",
    effort: "medium",
    max_output_tokens: 2048,
    voice_enabled: false,
    voice_id: null,
    theme: {},
    allowed_origins: ["https://example.com"],
    rate_limit_per_minute: 30,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    embed_snippet: '<script src="..."></script>',
    ...overrides,
  };
}

describe("AgentsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the empty state when there are no agents", async () => {
    vi.mocked(listAgents).mockResolvedValue({ items: [], total: 0 });
    render(<AgentsPage />);

    expect(await screen.findByText(/no agents yet/i)).toBeInTheDocument();
  });

  it("renders a table row per agent", async () => {
    vi.mocked(listAgents).mockResolvedValue({
      items: [makeAgent(), makeAgent({ id: "a2", name: "Sales Bot", status: "draft" })],
      total: 2,
    });
    render(<AgentsPage />);

    expect(await screen.findByText("Support Bot")).toBeInTheDocument();
    expect(screen.getByText("Sales Bot")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByText("draft")).toBeInTheDocument();
  });

  it("shows the load error when listAgents fails", async () => {
    vi.mocked(listAgents).mockRejectedValue(new Error("network down"));
    render(<AgentsPage />);

    expect(await screen.findByText("network down")).toBeInTheDocument();
  });

  it("deletes an agent after confirming, and removes it from the table", async () => {
    vi.mocked(listAgents).mockResolvedValue({ items: [makeAgent()], total: 1 });
    vi.mocked(deleteAgent).mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<AgentsPage />);

    await screen.findByText("Support Bot");
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByText(/delete "support bot"/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Delete$/ }));

    await waitFor(() => expect(deleteAgent).toHaveBeenCalledWith("a1"));
    await waitFor(() => expect(screen.queryByText("Support Bot")).not.toBeInTheDocument());
    expect(toast.success).toHaveBeenCalled();
  });

  it("shows a toast and keeps the row when delete fails", async () => {
    vi.mocked(listAgents).mockResolvedValue({ items: [makeAgent()], total: 1 });
    vi.mocked(deleteAgent).mockRejectedValue(new Error("cannot delete"));
    const user = userEvent.setup();
    render(<AgentsPage />);

    await screen.findByText("Support Bot");
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(await screen.findByRole("button", { name: /^Delete$/ }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("cannot delete"));
    expect(screen.getByText("Support Bot")).toBeInTheDocument();
  });
});
