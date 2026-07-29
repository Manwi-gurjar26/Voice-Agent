import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
}));

const signup = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ signup, status: "unauthenticated" }),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { toast } from "sonner";
import SignupPage from "./page";

describe("SignupPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("requires a workspace name and a valid email", async () => {
    const user = userEvent.setup();
    render(<SignupPage />);

    await user.click(screen.getByRole("button", { name: /create workspace/i }));

    expect(await screen.findByText(/workspace name is required/i)).toBeInTheDocument();
    expect(await screen.findByText(/enter a valid email/i)).toBeInTheDocument();
    expect(signup).not.toHaveBeenCalled();
  });

  it("signs up with a null full_name when left blank, and redirects", async () => {
    signup.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<SignupPage />);

    await user.type(screen.getByLabelText(/workspace name/i), "Acme Inc");
    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.type(screen.getByLabelText(/^password/i), "correct horse battery staple 1");
    await user.click(screen.getByRole("button", { name: /create workspace/i }));

    await waitFor(() =>
      expect(signup).toHaveBeenCalledWith({
        email: "a@b.com",
        password: "correct horse battery staple 1",
        company_name: "Acme Inc",
        full_name: null,
      }),
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/agents"));
  });

  it("passes a trimmed full_name when provided", async () => {
    signup.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<SignupPage />);

    await user.type(screen.getByLabelText(/workspace name/i), "Acme Inc");
    await user.type(screen.getByLabelText(/your name/i), "  Ada  ");
    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.type(screen.getByLabelText(/^password/i), "correct horse battery staple 1");
    await user.click(screen.getByRole("button", { name: /create workspace/i }));

    await waitFor(() =>
      expect(signup).toHaveBeenCalledWith(expect.objectContaining({ full_name: "Ada" })),
    );
  });

  it("surfaces the backend's validation message on a policy violation", async () => {
    const { ApiError } = await import("@/lib/api");
    signup.mockRejectedValue(
      new ApiError(422, "validation_error", "The request payload is invalid.", {
        fields: [{ loc: ["body", "password"], msg: "Value error, password must be at least 12 characters" }],
      }),
    );
    const user = userEvent.setup();
    render(<SignupPage />);

    await user.type(screen.getByLabelText(/workspace name/i), "Acme Inc");
    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.type(screen.getByLabelText(/^password/i), "short1");
    await user.click(screen.getByRole("button", { name: /create workspace/i }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("password must be at least 12 characters"),
    );
  });
});
