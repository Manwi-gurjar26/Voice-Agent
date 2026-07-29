import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./api";

const BASE_URL = "https://api.example.com/api/v1";
const PUBLIC_KEY = "agt_pub_test123";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("createApiClient", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("getConfig calls the right URL and returns the parsed body", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ name: "Bot", greeting: "Hi", voice_enabled: false, theme: {} }),
    );
    const client = createApiClient(BASE_URL, PUBLIC_KEY);

    const config = await client.getConfig();

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/public/agents/${PUBLIC_KEY}/config`,
      expect.objectContaining({ credentials: "omit" }),
    );
    expect(config.name).toBe("Bot");
  });

  it("strips a trailing slash from the base URL", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ name: "Bot", greeting: "", voice_enabled: false, theme: {} }));
    const client = createApiClient(`${BASE_URL}/`, PUBLIC_KEY);

    await client.getConfig();

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/public/agents/${PUBLIC_KEY}/config`,
      expect.anything(),
    );
  });

  it("createSession POSTs and returns the token", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ session_token: "tok_abc", token_type: "bearer", expires_in: 3600 }),
    );
    const client = createApiClient(BASE_URL, PUBLIC_KEY);

    const session = await client.createSession();

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/public/agents/${PUBLIC_KEY}/sessions`,
      expect.objectContaining({ method: "POST" }),
    );
    expect(session.session_token).toBe("tok_abc");
  });

  it("validateSession returns true for a 200 and false for any error status", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "s1", agent_id: "a1", expires_at: "x" }));
    const client = createApiClient(BASE_URL, PUBLIC_KEY);
    expect(await client.validateSession("tok")).toBe(true);

    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { code: "unauthenticated", message: "no" } }, 401));
    expect(await client.validateSession("tok")).toBe(false);
  });

  it("sends the Authorization header on authenticated calls", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "conv1", created_at: "now" }));
    const client = createApiClient(BASE_URL, PUBLIC_KEY);

    await client.createConversation("tok_xyz");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok_xyz");
  });

  it("listMessages returns the items array", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [{ id: "m1", role: "user", content: "hi", citations: null, created_at: "now" }] }),
    );
    const client = createApiClient(BASE_URL, PUBLIC_KEY);

    const messages = await client.listMessages("tok", "conv1");

    expect(messages).toHaveLength(1);
    expect(messages[0]?.content).toBe("hi");
  });

  it("throws an ApiError carrying the backend's code and message on failure", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ error: { code: "origin_not_allowed", message: "Origin not permitted." } }, 403),
    );
    const client = createApiClient(BASE_URL, PUBLIC_KEY);

    await expect(client.getConfig()).rejects.toMatchObject({
      status: 403,
      code: "origin_not_allowed",
      message: "Origin not permitted.",
    });
  });

  it("falls back to a generic ApiError when the error body isn't parseable JSON", async () => {
    fetchMock.mockResolvedValueOnce(new Response("<html>502</html>", { status: 502 }));
    const client = createApiClient(BASE_URL, PUBLIC_KEY);

    await expect(client.getConfig()).rejects.toBeInstanceOf(ApiError);
  });

  it("sendMessage POSTs the content as JSON and yields parsed SSE events", async () => {
    const sseBody = 'event: delta\ndata: {"text":"Hi"}\n\n';
    fetchMock.mockResolvedValueOnce(new Response(sseBody, { status: 200 }));
    const client = createApiClient(BASE_URL, PUBLIC_KEY);

    const events = [];
    for await (const event of client.sendMessage("tok", "conv1", "hello")) {
      events.push(event);
    }

    expect(events).toEqual([{ event: "delta", data: { text: "Hi" } }]);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ content: "hello" });
  });

  it("sendMessage throws before yielding anything if the request itself fails", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ error: { code: "quota_exceeded", message: "Quota used up." } }, 402),
    );
    const client = createApiClient(BASE_URL, PUBLIC_KEY);

    const iterator = client.sendMessage("tok", "conv1", "hi");
    await expect(iterator.next()).rejects.toMatchObject({ code: "quota_exceeded" });
  });
});
