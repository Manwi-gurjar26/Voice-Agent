import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TenantRead } from "@/lib/types";

const replace = vi.fn();
let searchParamsValue = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => searchParamsValue,
}));

const refresh = vi.fn();
let currentTenant: TenantRead;
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ tenant: currentTenant, refresh }),
}));

vi.mock("@/lib/api", () => ({
  createCheckoutSession: vi.fn(),
  createPortalSession: vi.fn(),
  formatApiError: (err: unknown) => (err instanceof Error ? err.message : "Something went wrong."),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() },
}));

import { createCheckoutSession, createPortalSession } from "@/lib/api";
import { toast } from "sonner";
import BillingPage from "./page";

function makeTenant(overrides: Partial<TenantRead> = {}): TenantRead {
  return {
    id: "t1",
    name: "Acme",
    slug: "acme",
    plan: "free",
    monthly_message_quota: 1000,
    messages_used_in_period: 200,
    period_started_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const originalLocation = window.location;

describe("BillingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    searchParamsValue = new URLSearchParams();
    currentTenant = makeTenant();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, href: "" },
    });
  });

  it("shows usage and upgrade options for a free-plan tenant", () => {
    render(<BillingPage />);

    expect(screen.getByText(/free plan/i)).toBeInTheDocument();
    expect(screen.getByText(/200/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upgrade to starter/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upgrade to pro/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upgrade to enterprise/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /manage billing/i })).not.toBeInTheDocument();
  });

  it("only offers tiers above the current plan, and shows Manage billing once paid", () => {
    currentTenant = makeTenant({ plan: "pro" });
    render(<BillingPage />);

    expect(screen.queryByRole("button", { name: /upgrade to starter/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /upgrade to pro/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upgrade to enterprise/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /manage billing/i })).toBeInTheDocument();
  });

  it("redirects to the returned Checkout URL on upgrade", async () => {
    vi.mocked(createCheckoutSession).mockResolvedValue({ url: "https://checkout.dodopayments.com/xyz" });
    const user = userEvent.setup();
    render(<BillingPage />);

    await user.click(screen.getByRole("button", { name: /upgrade to pro/i }));

    expect(createCheckoutSession).toHaveBeenCalledWith("pro");
    await waitFor(() => expect(window.location.href).toBe("https://checkout.dodopayments.com/xyz"));
  });

  it("redirects to the returned Portal URL on manage billing", async () => {
    currentTenant = makeTenant({ plan: "starter" });
    vi.mocked(createPortalSession).mockResolvedValue({ url: "https://customer-portal.dodopayments.com/xyz" });
    const user = userEvent.setup();
    render(<BillingPage />);

    await user.click(screen.getByRole("button", { name: /manage billing/i }));

    await waitFor(() => expect(window.location.href).toBe("https://customer-portal.dodopayments.com/xyz"));
  });

  it("shows a toast and re-enables the button when checkout fails to start", async () => {
    vi.mocked(createCheckoutSession).mockRejectedValue(new Error("no price configured"));
    const user = userEvent.setup();
    render(<BillingPage />);

    await user.click(screen.getByRole("button", { name: /upgrade to starter/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("no price configured"));
    expect(screen.getByRole("button", { name: /upgrade to starter/i })).not.toBeDisabled();
  });

  it("shows a success toast, refreshes, and clears the query param after a successful checkout return", async () => {
    searchParamsValue = new URLSearchParams("checkout=success");
    render(<BillingPage />);

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith("/billing");
  });

  it("shows an info toast without refreshing after a cancelled checkout", async () => {
    searchParamsValue = new URLSearchParams("checkout=cancelled");
    render(<BillingPage />);

    await waitFor(() => expect(toast.info).toHaveBeenCalled());
    expect(refresh).not.toHaveBeenCalled();
    expect(replace).toHaveBeenCalledWith("/billing");
  });
});
