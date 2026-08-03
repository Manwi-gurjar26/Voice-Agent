import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentRead } from "@/lib/types";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useParams: () => ({ id: "a1" }),
}));

vi.mock("@/lib/api", () => ({
  getAgent: vi.fn(),
  updateAgent: vi.fn(),
  deleteAgent: vi.fn(),
  formatApiError: (err: unknown) => (err instanceof Error ? err.message : "Something went wrong."),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { deleteAgent, getAgent, updateAgent } from "@/lib/api";
import { toast } from "sonner";
import EditAgentPage from "./page";

function makeAgent(overrides: Partial<AgentRead> = {}): AgentRead {
  return {
    id: "a1",
    name: "Support Bot",
    public_key: "agt_pub_1",
    status: "active",
    system_prompt: "You are helpful.",
    greeting: "Hi!",
    model: "gemini-flash-latest",
    effort: "medium",
    max_output_tokens: 2048,
    voice_enabled: false,
    voice_id: null,
    theme: { primaryColor: "#2F6FED", position: "bottom-right" },
    allowed_origins: ["https://example.com"],
    rate_limit_per_minute: 30,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    embed_snippet: '<script src="https://cdn.example.com/widget.js" data-agent-key="agt_pub_1" async></script>',
    ...overrides,
  };
}

describe("EditAgentPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads the agent and prefills the form", async () => {
    vi.mocked(getAgent).mockResolvedValue(makeAgent());
    render(<EditAgentPage />);

    expect(await screen.findByDisplayValue("Support Bot")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Hi!")).toBeInTheDocument();
    expect(screen.getByText(/data-agent-key="agt_pub_1"/)).toBeInTheDocument();
    expect(getAgent).toHaveBeenCalledWith("a1");
  });

  it("shows the load error when the agent can't be fetched", async () => {
    vi.mocked(getAgent).mockRejectedValue(new Error("not found"));
    render(<EditAgentPage />);

    expect(await screen.findByText("not found")).toBeInTheDocument();
  });

  it("saves changes via updateAgent, including status and rate limit", async () => {
    vi.mocked(getAgent).mockResolvedValue(makeAgent());
    vi.mocked(updateAgent).mockResolvedValue(makeAgent({ name: "Renamed Bot" }));
    const user = userEvent.setup();
    render(<EditAgentPage />);

    await screen.findByDisplayValue("Support Bot");
    const nameInput = screen.getByLabelText(/^name$/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed Bot");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() =>
      expect(updateAgent).toHaveBeenCalledWith(
        "a1",
        expect.objectContaining({
          name: "Renamed Bot",
          status: "active",
          rate_limit_per_minute: 30,
        }),
      ),
    );
    expect(toast.success).toHaveBeenCalled();
  });

  it("deletes the agent after confirming and navigates back to the list", async () => {
    vi.mocked(getAgent).mockResolvedValue(makeAgent());
    vi.mocked(deleteAgent).mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<EditAgentPage />);

    await screen.findByDisplayValue("Support Bot");
    await user.click(screen.getByRole("button", { name: "Delete agent" }));
    await user.click(await screen.findByRole("button", { name: /^Delete$/ }));

    await waitFor(() => expect(deleteAgent).toHaveBeenCalledWith("a1"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/agents"));
  });
});
