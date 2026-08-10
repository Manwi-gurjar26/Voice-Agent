import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
let searchParamsValue = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => searchParamsValue,
}));

vi.mock("@/lib/api", () => ({
  resetPassword: vi.fn(),
  formatApiError: (err: unknown) => (err instanceof Error ? err.message : "Something went wrong."),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { resetPassword } from "@/lib/api";
import { toast } from "sonner";
import ResetPasswordPage from "./page";

describe("ResetPasswordPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    searchParamsValue = new URLSearchParams("token=tok_abc");
  });

  it("shows an invalid-link message when the token query param is missing", () => {
    searchParamsValue = new URLSearchParams();
    render(<ResetPasswordPage />);

    expect(screen.getByText(/invalid link/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/new password/i)).not.toBeInTheDocument();
  });

  it("shows a validation error for an empty submission", async () => {
    const user = userEvent.setup();
    render(<ResetPasswordPage />);

    await user.click(screen.getByRole("button", { name: /reset password/i }));

    expect(await screen.findByText(/password is required/i)).toBeInTheDocument();
    expect(resetPassword).not.toHaveBeenCalled();
  });

  it("resets the password with the token from the URL, then redirects to login", async () => {
    vi.mocked(resetPassword).mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ResetPasswordPage />);

    await user.type(screen.getByLabelText(/new password/i), "new-correct-horse-99");
    await user.click(screen.getByRole("button", { name: /reset password/i }));

    await waitFor(() =>
      expect(resetPassword).toHaveBeenCalledWith("tok_abc", "new-correct-horse-99"),
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(toast.success).toHaveBeenCalled();
  });

  it("shows a toast error for an invalid or expired token, without redirecting", async () => {
    vi.mocked(resetPassword).mockRejectedValue(
      new Error("This password reset link is invalid or has expired."),
    );
    const user = userEvent.setup();
    render(<ResetPasswordPage />);

    await user.type(screen.getByLabelText(/new password/i), "new-correct-horse-99");
    await user.click(screen.getByRole("button", { name: /reset password/i }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("This password reset link is invalid or has expired."),
    );
    expect(replace).not.toHaveBeenCalled();
  });
});
