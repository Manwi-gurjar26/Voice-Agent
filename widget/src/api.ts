import { parseSseStream } from "./sse";
import type {
  AgentPublicConfig,
  ApiErrorBody,
  ConversationRead,
  MessageRead,
  SseEvent,
  WidgetSessionResponse,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as ApiErrorBody;
    return new ApiError(response.status, body.error.code, body.error.message);
  } catch {
    return new ApiError(response.status, "unknown_error", `Request failed with status ${response.status}`);
  }
}

export interface ApiClient {
  getConfig(): Promise<AgentPublicConfig>;
  createSession(): Promise<WidgetSessionResponse>;
  validateSession(sessionToken: string): Promise<boolean>;
  createConversation(sessionToken: string): Promise<ConversationRead>;
  listMessages(sessionToken: string, conversationId: string): Promise<MessageRead[]>;
  sendMessage(sessionToken: string, conversationId: string, content: string): AsyncGenerator<SseEvent>;
}

/** One client per mounted widget instance, bound to one agent's public_key. */
export function createApiClient(baseUrl: string, publicKey: string): ApiClient {
  const base = baseUrl.replace(/\/+$/, "");

  function authHeaders(token: string): HeadersInit {
    return { Authorization: `Bearer ${token}` };
  }

  async function getConfig(): Promise<AgentPublicConfig> {
    const res = await fetch(`${base}/public/agents/${publicKey}/config`, {
      credentials: "omit", // bearer-token auth only — no ambient cookie authority
    });
    if (!res.ok) throw await errorFromResponse(res);
    return (await res.json()) as AgentPublicConfig;
  }

  async function createSession(): Promise<WidgetSessionResponse> {
    const res = await fetch(`${base}/public/agents/${publicKey}/sessions`, {
      method: "POST",
      credentials: "omit",
    });
    if (!res.ok) throw await errorFromResponse(res);
    return (await res.json()) as WidgetSessionResponse;
  }

  async function validateSession(sessionToken: string): Promise<boolean> {
    const res = await fetch(`${base}/public/sessions/me`, {
      headers: authHeaders(sessionToken),
      credentials: "omit",
    });
    return res.ok;
  }

  async function createConversation(sessionToken: string): Promise<ConversationRead> {
    const res = await fetch(`${base}/public/conversations`, {
      method: "POST",
      headers: authHeaders(sessionToken),
      credentials: "omit",
    });
    if (!res.ok) throw await errorFromResponse(res);
    return (await res.json()) as ConversationRead;
  }

  async function listMessages(sessionToken: string, conversationId: string): Promise<MessageRead[]> {
    const res = await fetch(`${base}/public/conversations/${conversationId}/messages`, {
      headers: authHeaders(sessionToken),
      credentials: "omit",
    });
    if (!res.ok) throw await errorFromResponse(res);
    const body = (await res.json()) as { items: MessageRead[] };
    return body.items;
  }

  async function* sendMessage(
    sessionToken: string,
    conversationId: string,
    content: string,
  ): AsyncGenerator<SseEvent> {
    const res = await fetch(`${base}/public/conversations/${conversationId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(sessionToken) },
      credentials: "omit",
      body: JSON.stringify({ content }),
    });
    if (!res.ok) throw await errorFromResponse(res);
    yield* parseSseStream(res);
  }

  return {
    getConfig,
    createSession,
    validateSession,
    createConversation,
    listMessages,
    sendMessage,
  };
}
