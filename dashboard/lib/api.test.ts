import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  createAgent,
  createCheckoutSession,
  createPortalSession,
  deleteAgent,
  forgotPassword,
  getAgent,
  listAgents,
  login,
  logout,
  me,
  resetPassword,
  signup,
  updateAgent,
} from "./api";
import { loadAuth, storeAuth } from "./auth-storage";

const BASE_URL = "https://api.example.com/api/v1";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function seedAuth(overrides: Partial<{ expires_in: number }> = {}) {
  storeAuth({ access_token: "acc_1", refresh_token: "ref_1", expires_in: overrides.expires_in ?? 1800 });
}

describe("api", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    window.localStorage.clear();
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("signup POSTs the payload and stores the returned token pair", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ access_token: "acc", refresh_token: "ref", token_type: "bearer", expires_in: 1800 }),
    );

    await signup({ email: "a@b.com", password: "correct horse battery staple 1", company_name: "Acme" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE_URL}/auth/signup`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toMatchObject({ email: "a@b.com", company_name: "Acme" });
    expect(loadAuth()?.accessToken).toBe("acc");
  });

  it("login POSTs credentials and stores the returned token pair", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ access_token: "acc", refresh_token: "ref", token_type: "bearer", expires_in: 1800 }),
    );

    await login({ email: "a@b.com", password: "hunter2hunter2" });

    expect(loadAuth()?.accessToken).toBe("acc");
  });

  it("forgotPassword POSTs the email and stores no session", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 202 }));

    await forgotPassword("a@b.com");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE_URL}/auth/forgot-password`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ email: "a@b.com" });
    expect(loadAuth()).toBeNull();
  });

  it("forgotPassword propagates an ApiError on failure", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ error: { code: "rate_limited", message: "Too many requests." } }, 429),
    );

    await expect(forgotPassword("a@b.com")).rejects.toMatchObject({ code: "rate_limited" });
  });

  it("resetPassword POSTs the token and new password", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await resetPassword("tok_abc", "new-correct-horse-99");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE_URL}/auth/reset-password`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      token: "tok_abc",
      password: "new-correct-horse-99",
    });
  });

  it("resetPassword propagates an ApiError on an invalid token", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { error: { code: "invalid_reset_token", message: "This password reset link is invalid or has expired." } },
        401,
      ),
    );

    await expect(resetPassword("bad-token", "new-correct-horse-99")).rejects.toMatchObject({
      code: "invalid_reset_token",
    });
  });

  it("throws an ApiError carrying the backend's code and message on failure", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ error: { code: "unauthenticated", message: "Invalid credentials." } }, 401),
    );

    await expect(login({ email: "a@b.com", password: "wrong" })).rejects.toMatchObject({
      status: 401,
      code: "unauthenticated",
      message: "Invalid credentials.",
    });
  });

  it("falls back to a generic ApiError when the error body isn't parseable JSON", async () => {
    fetchMock.mockResolvedValueOnce(new Response("<html>502</html>", { status: 502 }));

    await expect(login({ email: "a@b.com", password: "x" })).rejects.toBeInstanceOf(ApiError);
  });

  it("me() attaches the Authorization header from the stored session", async () => {
    seedAuth();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        user: { id: "u1", email: "a@b.com", full_name: null, role: "owner", is_active: true, created_at: "now", last_login_at: null },
        tenant: {
          id: "t1",
          name: "Acme",
          slug: "acme",
          plan: "free",
          monthly_message_quota: 1000,
          messages_used_in_period: 0,
          period_started_at: "now",
        },
      }),
    );

    const result = await me();

    expect(result.user.email).toBe("a@b.com");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer acc_1");
  });

  it("me() throws unauthenticated without calling fetch when there is no stored session", async () => {
    await expect(me()).rejects.toMatchObject({ status: 401, code: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("proactively refreshes before the request when the stored access token is stale", async () => {
    seedAuth({ expires_in: 1 }); // within the 5s skew window -> treated as stale
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ access_token: "acc_2", refresh_token: "ref_2", token_type: "bearer", expires_in: 1800 }),
      )
      .mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));

    await listAgents();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [refreshUrl] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(refreshUrl).toBe(`${BASE_URL}/auth/refresh`);
    const [, secondInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect((secondInit.headers as Record<string, string>).Authorization).toBe("Bearer acc_2");
    expect(loadAuth()?.accessToken).toBe("acc_2");
  });

  it("reactively refreshes and retries once on a 401 from the actual request", async () => {
    seedAuth();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ error: { code: "token_expired", message: "expired" } }, 401))
      .mockResolvedValueOnce(
        jsonResponse({ access_token: "acc_2", refresh_token: "ref_2", token_type: "bearer", expires_in: 1800 }),
      )
      .mockResolvedValueOnce(jsonResponse({ id: "agent_1", name: "Bot" }));

    const result = await getAgent("agent_1");

    expect(result).toMatchObject({ id: "agent_1" });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const [, retryInit] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect((retryInit.headers as Record<string, string>).Authorization).toBe("Bearer acc_2");
  });

  it("propagates the original 401 when the refresh attempt itself fails", async () => {
    seedAuth();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ error: { code: "token_expired", message: "expired" } }, 401))
      .mockResolvedValueOnce(jsonResponse({ error: { code: "unauthenticated", message: "refresh dead" } }, 401));

    await expect(getAgent("agent_1")).rejects.toMatchObject({ code: "token_expired" });
    expect(loadAuth()).toBeNull();
  });

  it("createAgent/updateAgent/deleteAgent send the right method and body", async () => {
    seedAuth();
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "a1", name: "New Bot" }, 201));
    await createAgent({ name: "New Bot", effort: "medium", max_output_tokens: 2048, voice_enabled: false, allowed_origins: [] });
    let [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE_URL}/agents`);
    expect(init.method).toBe("POST");

    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "a1", name: "Renamed" }));
    await updateAgent("a1", { name: "Renamed" });
    [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe(`${BASE_URL}/agents/a1`);
    expect(init.method).toBe("PATCH");

    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await deleteAgent("a1");
    [url, init] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect(url).toBe(`${BASE_URL}/agents/a1`);
    expect(init.method).toBe("DELETE");
  });

  it("logout clears the session locally even if the server call fails", async () => {
    seedAuth();
    fetchMock.mockRejectedValueOnce(new TypeError("network down"));

    await logout();

    expect(loadAuth()).toBeNull();
  });

  it("logout is a no-op against the network when there is no stored session", async () => {
    await logout();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("createCheckoutSession POSTs the plan and returns the Checkout URL", async () => {
    seedAuth();
    fetchMock.mockResolvedValueOnce(jsonResponse({ url: "https://checkout.dodopayments.com/test" }));

    const result = await createCheckoutSession("pro");

    expect(result).toEqual({ url: "https://checkout.dodopayments.com/test" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE_URL}/billing/checkout-session`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ plan: "pro" });
  });

  it("createPortalSession POSTs with no body and returns the Portal URL", async () => {
    seedAuth();
    fetchMock.mockResolvedValueOnce(jsonResponse({ url: "https://customer-portal.dodopayments.com/test" }));

    const result = await createPortalSession();

    expect(result).toEqual({ url: "https://customer-portal.dodopayments.com/test" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE_URL}/billing/portal-session`);
    expect(init.method).toBe("POST");
  });
});
