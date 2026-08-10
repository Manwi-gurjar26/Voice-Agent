import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  forgotPassword: vi.fn(),
  formatApiError: (err: unknown) => (err instanceof Error ? err.message : "Something went wrong."),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { forgotPassword } from "@/lib/api";
import { toast } from "sonner";
import ForgotPasswordPage from "./page";

describe("ForgotPasswordPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a validation error for an empty submission", async () => {
    const user = userEvent.setup();
    render(<ForgotPasswordPage />);

    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(await screen.findByText(/enter a valid email/i)).toBeInTheDocument();
    expect(forgotPassword).not.toHaveBeenCalled();
  });

  it("shows the same confirmation regardless of whether the address exists", async () => {
    vi.mocked(forgotPassword).mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ForgotPasswordPage />);

    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(forgotPassword).toHaveBeenCalledWith("a@b.com");
    expect(await screen.findByText(/check your email/i)).toBeInTheDocument();
  });

  it("shows a toast error when the request itself fails (e.g. rate limited)", async () => {
    vi.mocked(forgotPassword).mockRejectedValue(new Error("Too many requests."));
    const user = userEvent.setup();
    render(<ForgotPasswordPage />);

    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Too many requests."));
    expect(screen.queryByText(/check your email/i)).not.toBeInTheDocument();
  });
});
