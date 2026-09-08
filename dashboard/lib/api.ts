import { clearAuth, isAccessTokenFresh, loadAuth, storeAuth } from "./auth-storage";
import type {
  AgentCreate,
  AgentListResponse,
  AgentPublicConfig,
  AgentRead,
  AgentUpdate,
  AnalyticsOverview,
  ApiErrorBody,
  CheckoutSessionResponse,
  ConversationRead,
  DocumentCreateCrawl,
  DocumentListResponse,
  LoginRequest,
  MessageRead,
  MeResponse,
  PaidPlan,
  PortalSessionResponse,
  PreviewStreamEvent,
  SignupRequest,
  TokenPair,
  VoiceReplyResponse,
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

/** The current access token, refreshed first if it is close to expiry.
 * Extracted from authedRequest so the two calls that manage their own
 * fetch (an SSE stream and a multipart upload) do not each reimplement the
 * refresh dance. */
async function freshAccessToken(): Promise<string> {
  let auth = loadAuth();
  if (!auth) throw new ApiError(401, "unauthenticated", "Not signed in.");
  if (!isAccessTokenFresh(auth)) {
    auth = await refreshSession();
    if (!auth) throw new ApiError(401, "unauthenticated", "Session expired. Please sign in again.");
  }
  return auth.accessToken;
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

export function getAnalyticsOverview(days = 30): Promise<AnalyticsOverview> {
  return authedRequest<AnalyticsOverview>(`/analytics/overview?days=${days}`);
}

/* ---------------------------------------------------------------------------
   Agent preview.

   Talks to /agents/{id}/preview/* — the dashboard-authenticated twin of the
   widget's public endpoints. Using the public ones from here cannot work:
   they require the caller's Origin to be on the agent's allowlist (the
   dashboard is not, and should not be) and refuse any agent still in draft,
   which is the state an agent is in when you most want to try it.
--------------------------------------------------------------------------- */

export function getPreviewConfig(agentId: string): Promise<AgentPublicConfig> {
  return authedRequest<AgentPublicConfig>(`/agents/${agentId}/preview/config`);
}

export function startPreviewConversation(agentId: string): Promise<ConversationRead> {
  return authedRequest<ConversationRead>(`/agents/${agentId}/preview/conversations`, {
    method: "POST",
  });
}

export function listPreviewMessages(
  agentId: string,
  conversationId: string,
): Promise<{ items: MessageRead[] }> {
  return authedRequest<{ items: MessageRead[] }>(
    `/agents/${agentId}/preview/conversations/${conversationId}/messages`,
  );
}

/**
 * Parses the `event: X` / `data: Y` blocks off a streaming response — the
 * exact format the backend's `_sse()` writes, one blank line between blocks.
 *
 * Native EventSource cannot be used: it is GET-only, carries no body, and
 * cannot set an Authorization header. Partial blocks are buffered across
 * chunk boundaries, since the blank-line separator can land anywhere relative
 * to how the browser happens to deliver bytes.
 */
const BLOCK_SEPARATOR = "\n\n";

async function* parseSse(response: Response): AsyncGenerator<PreviewStreamEvent> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf(BLOCK_SEPARATOR);
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let event = "";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7);
          else if (line.startsWith("data: ")) data = line.slice(6);
        }
        if (event && data) {
          try {
            yield { event, data: JSON.parse(data) } as PreviewStreamEvent;
          } catch {
            // A block that does not parse is dropped rather than aborting
            // the stream — the turn's remaining deltas are still useful.
          }
        }
        boundary = buffer.indexOf(BLOCK_SEPARATOR);
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** Streams a preview reply. Bypasses `authedRequest` because that helper
 * reads the whole body as text; here the point is to consume it
 * incrementally. Token freshness is handled the same way, just inline. */
export async function* sendPreviewMessage(
  agentId: string,
  conversationId: string,
  content: string,
): AsyncGenerator<PreviewStreamEvent> {
  const token = await freshAccessToken();
  const res = await fetch(
    `${BASE_URL}/agents/${agentId}/preview/conversations/${conversationId}/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ content }),
    },
  );
  if (!res.ok) throw await errorFromResponse(res);
  yield* parseSse(res);
}

export async function sendPreviewVoiceMessage(
  agentId: string,
  conversationId: string,
  audio: Blob,
  filename: string,
): Promise<VoiceReplyResponse> {
  const token = await freshAccessToken();
  const form = new FormData();
  form.append("file", audio, filename);
  const res = await fetch(
    `${BASE_URL}/agents/${agentId}/preview/conversations/${conversationId}/voice-messages`,
    {
      method: "POST",
      // No explicit Content-Type: the browser sets the multipart boundary
      // itself when the body is a FormData instance.
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    },
  );
  if (!res.ok) throw await errorFromResponse(res);
  return (await res.json()) as VoiceReplyResponse;
}
