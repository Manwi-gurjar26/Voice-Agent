import { clearAuth, isAccessTokenFresh, loadAuth, storeAuth } from "./auth-storage";
import type {
  AgentCreate,
  AgentListResponse,
  AgentRead,
  AgentUpdate,
  ApiErrorBody,
  CheckoutSessionResponse,
  DocumentCreateCrawl,
  DocumentListResponse,
  LoginRequest,
  MeResponse,
  PaidPlan,
  PortalSessionResponse,
  SignupRequest,
  TokenPair,
} from "./types";

const BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1").replace(
  /\/+$/,
  "",
);

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as ApiErrorBody;
    return new ApiError(response.status, body.error.code, body.error.message, body.error.details);
  } catch {
    return new ApiError(response.status, "unknown_error", `Request failed with status ${response.status}`);
  }
}

interface ValidationFieldError {
  loc?: unknown[];
  msg?: string;
}

/** Surfaces the real per-field message for a validation_error (the generic
 * envelope message is just "The request payload is invalid.") — falls back
 * to the error's own message for every other error code. */
export function formatApiError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "validation_error" && Array.isArray(err.details?.fields)) {
      const fields = err.details.fields as ValidationFieldError[];
      const first = fields.find((f) => typeof f.msg === "string");
      if (first?.msg) return first.msg.replace(/^Value error,\s*/, "");
    }
    return err.message;
  }
  return "Something went wrong. Please try again.";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, init);
  if (!res.ok) throw await errorFromResponse(res);
  // Not just 204 — 202 Accepted (forgot-password) also has no body. Reading
  // as text first and checking for emptiness covers any status that omits
  // one, rather than special-casing each status code that might.
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  };
}

/** Refreshes the stored session and persists the new pair, or clears the
 * session and returns null if the refresh token itself is no longer valid. */
async function refreshSession(): Promise<ReturnType<typeof loadAuth>> {
  const auth = loadAuth();
  if (!auth) return null;
  try {
    const pair = await request<TokenPair>("/auth/refresh", jsonInit("POST", { refresh_token: auth.refreshToken }));
    storeAuth(pair);
    return loadAuth();
  } catch {
    clearAuth();
    return null;
  }
}

/** Attaches the current access token and, on a 401, refreshes the session
 * and retries exactly once — centralized here (rather than per call site)
 * since nearly every dashboard endpoint needs this, unlike the widget where
 * only one call site ever needed a retry-on-expiry. */
async function authedRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  let auth = loadAuth();
  if (!auth) throw new ApiError(401, "unauthenticated", "Not signed in.");

  if (!isAccessTokenFresh(auth)) {
    auth = await refreshSession();
    if (!auth) throw new ApiError(401, "unauthenticated", "Session expired. Please sign in again.");
  }

  const withAuth = (token: string): RequestInit => ({
    ...init,
    headers: { ...(init.headers ?? {}), Authorization: `Bearer ${token}` },
  });

  try {
    return await request<T>(path, withAuth(auth.accessToken));
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      const refreshed = await refreshSession();
      if (!refreshed) throw err;
      return await request<T>(path, withAuth(refreshed.accessToken));
    }
    throw err;
  }
}

export async function signup(payload: SignupRequest): Promise<TokenPair> {
  const pair = await request<TokenPair>("/auth/signup", jsonInit("POST", payload));
  storeAuth(pair);
  return pair;
}

export async function login(payload: LoginRequest): Promise<TokenPair> {
  const pair = await request<TokenPair>("/auth/login", jsonInit("POST", payload));
  storeAuth(pair);
  return pair;
}

export async function forgotPassword(email: string): Promise<void> {
  await request("/auth/forgot-password", jsonInit("POST", { email }));
}

export async function resetPassword(token: string, password: string): Promise<void> {
  await request("/auth/reset-password", jsonInit("POST", { token, password }));
}

export async function logout(): Promise<void> {
  const auth = loadAuth();
  clearAuth();
  if (!auth) return;
  try {
    await request("/auth/logout", jsonInit("POST", { refresh_token: auth.refreshToken }));
  } catch {
    // Local session is already cleared — a failed server-side revoke
    // shouldn't trap the user in a logged-in-looking state.
  }
}

export async function logoutAll(): Promise<void> {
  try {
    await authedRequest("/auth/logout-all", { method: "POST" });
  } finally {
    clearAuth();
  }
}

export function me(): Promise<MeResponse> {
  return authedRequest<MeResponse>("/auth/me");
}

export function listAgents(): Promise<AgentListResponse> {
  return authedRequest<AgentListResponse>("/agents");
}

export function getAgent(id: string): Promise<AgentRead> {
  return authedRequest<AgentRead>(`/agents/${id}`);
}

export function createAgent(payload: AgentCreate): Promise<AgentRead> {
  return authedRequest<AgentRead>("/agents", jsonInit("POST", payload));
}

export function updateAgent(id: string, payload: AgentUpdate): Promise<AgentRead> {
  return authedRequest<AgentRead>(`/agents/${id}`, jsonInit("PATCH", payload));
}

export async function deleteAgent(id: string): Promise<void> {
  await authedRequest<void>(`/agents/${id}`, { method: "DELETE" });
}

export function listDocuments(agentId: string): Promise<DocumentListResponse> {
  return authedRequest<DocumentListResponse>(`/agents/${agentId}/documents`);
}

/** Starts a Firecrawl crawl and waits for the backend's synchronous
 * response — ingestion (including the crawl itself) runs within this one
 * request, so this can take a while for a many-page site; see the
 * backend's crawl_poll_timeout_seconds. */
export function crawlWebsite(agentId: string, payload: DocumentCreateCrawl): Promise<DocumentListResponse> {
  return authedRequest<DocumentListResponse>(`/agents/${agentId}/documents/crawl`, jsonInit("POST", payload));
}

export async function deleteDocument(agentId: string, documentId: string): Promise<void> {
  await authedRequest<void>(`/agents/${agentId}/documents/${documentId}`, { method: "DELETE" });
}

export function createCheckoutSession(plan: PaidPlan): Promise<CheckoutSessionResponse> {
  return authedRequest<CheckoutSessionResponse>("/billing/checkout-session", jsonInit("POST", { plan }));
}

export function createPortalSession(): Promise<PortalSessionResponse> {
  return authedRequest<PortalSessionResponse>("/billing/portal-session", { method: "POST" });
}
