import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { storeAuth, loadAuth } from "./auth-storage";
import type { MeResponse, TokenPair } from "./types";

vi.mock("./api", () => ({
  me: vi.fn(),
  login: vi.fn(),
  signup: vi.fn(),
  logout: vi.fn(),
}));

import * as api from "./api";
import { AuthProvider, useAuth } from "./auth-context";

const ME: MeResponse = {
  user: {
    id: "u1",
    email: "a@b.com",
    full_name: "Ada",
    role: "owner",
    is_active: true,
    created_at: "now",
    last_login_at: null,
  },
  tenant: {
    id: "t1",
    name: "Acme",
    slug: "acme",
    plan: "free",
    monthly_message_quota: 1000,
    messages_used_in_period: 0,
    period_started_at: "now",
  },
};

const TOKENS: TokenPair = { access_token: "acc", refresh_token: "ref", token_type: "bearer", expires_in: 1800 };

function wrapper({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

describe("AuthProvider", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("starts unauthenticated when no session is stored", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe("unauthenticated"));
    expect(result.current.user).toBeNull();
  });

  it("bootstraps to authenticated when a valid session is stored", async () => {
    storeAuth({ access_token: "acc", refresh_token: "ref", expires_in: 1800 });
    vi.mocked(api.me).mockResolvedValue(ME);

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe("authenticated"));
    expect(result.current.user?.email).toBe("a@b.com");
    expect(result.current.tenant?.name).toBe("Acme");
  });

  it("clears a stored session that no longer resolves via /auth/me", async () => {
    storeAuth({ access_token: "acc", refresh_token: "ref", expires_in: 1800 });
    vi.mocked(api.me).mockRejectedValue(new Error("session gone"));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe("unauthenticated"));
    expect(loadAuth()).toBeNull();
  });

  it("login() calls the API then loads the current user", async () => {
    vi.mocked(api.login).mockResolvedValue(TOKENS);
    vi.mocked(api.me).mockResolvedValue(ME);

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("unauthenticated"));

    await act(async () => {
      await result.current.login({ email: "a@b.com", password: "x" });
    });

    expect(api.login).toHaveBeenCalledWith({ email: "a@b.com", password: "x" });
    expect(result.current.status).toBe("authenticated");
    expect(result.current.user?.email).toBe("a@b.com");
  });

  it("signup() calls the API then loads the current user", async () => {
    vi.mocked(api.signup).mockResolvedValue(TOKENS);
    vi.mocked(api.me).mockResolvedValue(ME);

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("unauthenticated"));

    await act(async () => {
      await result.current.signup({ email: "a@b.com", password: "x", company_name: "Acme" });
    });

    expect(result.current.status).toBe("authenticated");
  });

  it("logout() clears state even though the API call is mocked away", async () => {
    storeAuth({ access_token: "acc", refresh_token: "ref", expires_in: 1800 });
    vi.mocked(api.me).mockResolvedValue(ME);
    vi.mocked(api.logout).mockResolvedValue(undefined);

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("authenticated"));

    await act(async () => {
      await result.current.logout();
    });

    expect(api.logout).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("unauthenticated");
    expect(result.current.user).toBeNull();
  });
});
