import { waitFor } from "@testing-library/preact";
import { renderHook } from "@testing-library/preact";
import { act } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient } from "../api";
import * as storage from "../storage";
import type {
  AgentPublicConfig,
  ConversationRead,
  MessageRead,
  SseEvent,
  VoiceReplyResponse,
  WidgetSessionResponse,
} from "../types";
import { useChat } from "./useChat";

const PUBLIC_KEY = "agt_pub_test123";

const CONFIG: AgentPublicConfig = {
  name: "Bot",
  greeting: "Hi there",
  voice_enabled: false,
  theme: {},
};

async function* asyncEvents(events: SseEvent[]): AsyncGenerator<SseEvent> {
  for (const event of events) yield event;
}

// eslint-disable-next-line require-yield -- intentionally throws before ever yielding, to simulate a stream that fails immediately
async function* throwingEvents(err: unknown): AsyncGenerator<SseEvent> {
  throw err;
}

function makeApi(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    getConfig: vi.fn().mockResolvedValue(CONFIG),
    createSession: vi
      .fn()
      .mockResolvedValue({ session_token: "tok_new", token_type: "bearer", expires_in: 3600 } satisfies WidgetSessionResponse),
    validateSession: vi.fn().mockResolvedValue(true),
    createConversation: vi.fn().mockResolvedValue({ id: "conv_1", created_at: "now" } satisfies ConversationRead),
    listMessages: vi.fn().mockResolvedValue([] as MessageRead[]),
    sendMessage: vi.fn().mockImplementation(() => asyncEvents([])),
    sendVoiceMessage: vi.fn().mockResolvedValue({
      transcript: "hello",
      message: { id: "m_voice", role: "assistant", content: "hi there", citations: null, created_at: "now" },
      audio_base64: "ZmFrZQ==",
      audio_mime: "audio/mpeg",
    } satisfies VoiceReplyResponse),
    ...overrides,
  };
}

describe("useChat", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("bootstraps to ready, creating a fresh session when none is stored", async () => {
    const api = makeApi();
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));

    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(result.current.config).toEqual(CONFIG);
    expect(api.createSession).toHaveBeenCalledTimes(1);
    expect(storage.loadStoredSession(PUBLIC_KEY)?.token).toBe("tok_new");
  });

  it("reuses and validates a stored session instead of creating a new one", async () => {
    storage.storeSession(PUBLIC_KEY, "tok_existing", 3600);
    const api = makeApi();
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));

    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(api.validateSession).toHaveBeenCalledWith("tok_existing");
    expect(api.createSession).not.toHaveBeenCalled();
  });

  it("creates a new session when the stored one fails validation", async () => {
    storage.storeSession(PUBLIC_KEY, "tok_stale", 3600);
    const api = makeApi({ validateSession: vi.fn().mockResolvedValue(false) });
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));

    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(api.createSession).toHaveBeenCalledTimes(1);
  });

  it("becomes unavailable, without throwing, when getConfig fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const api = makeApi({ getConfig: vi.fn().mockRejectedValue(new Error("network down")) });
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));

    await waitFor(() => expect(result.current.status).toBe("unavailable"));
  });

  it("becomes unavailable when session creation fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const api = makeApi({ createSession: vi.fn().mockRejectedValue(new Error("boom")) });
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));

    await waitFor(() => expect(result.current.status).toBe("unavailable"));
  });

  it("resumes a stored conversation's history when present", async () => {
    storage.storeConversationId(PUBLIC_KEY, "conv_old");
    const history: MessageRead[] = [
      { id: "m1", role: "user", content: "hello", citations: null, created_at: "now" },
      { id: "m2", role: "assistant", content: "hi!", citations: null, created_at: "now" },
    ];
    const api = makeApi({ listMessages: vi.fn().mockResolvedValue(history) });
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));

    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({ content: "hello", status: "complete" });
  });

  it("silently discards a stale stored conversation id when history fetch fails", async () => {
    storage.storeConversationId(PUBLIC_KEY, "conv_gone");
    const api = makeApi({ listMessages: vi.fn().mockRejectedValue(new ApiError(404, "not_found", "gone")) });
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));

    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(result.current.messages).toHaveLength(0);
  });

  it("sendMessage streams delta events into the assistant message and marks it complete on done", async () => {
    const api = makeApi({
      sendMessage: vi.fn().mockImplementation(() =>
        asyncEvents([
          { event: "delta", data: { text: "Hel" } },
          { event: "delta", data: { text: "lo!" } },
          {
            event: "done",
            data: { message_id: "m1", stop_reason: "end_turn", usage: { input_tokens: 1, output_tokens: 2 }, citations: [] },
          },
        ]),
      ),
    });
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    await act(async () => {
      result.current.sendMessage("hello");
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.isSending).toBe(false));

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({ role: "user", content: "hello", status: "complete" });
    expect(result.current.messages[1]).toMatchObject({ role: "assistant", content: "Hello!", status: "complete" });
    expect(api.createConversation).toHaveBeenCalledTimes(1);
  });

  it("ignores empty/whitespace-only input", async () => {
    const api = makeApi();
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    await act(async () => {
      result.current.sendMessage("   ");
    });

    expect(result.current.messages).toHaveLength(0);
    expect(api.createConversation).not.toHaveBeenCalled();
  });

  it("reuses the conversation id across multiple sends", async () => {
    const api = makeApi();
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    await act(async () => {
      result.current.sendMessage("first");
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.isSending).toBe(false));

    await act(async () => {
      result.current.sendMessage("second");
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.isSending).toBe(false));

    expect(api.createConversation).toHaveBeenCalledTimes(1);
  });

  it("on an auth error, refreshes the session and retries exactly once, succeeding", async () => {
    let call = 0;
    const api = makeApi({
      sendMessage: vi.fn().mockImplementation(() => {
        call += 1;
        if (call === 1) {
          return throwingEvents(new ApiError(401, "session_expired", "expired"));
        }
        return asyncEvents([
          {
            event: "done",
            data: { message_id: "m1", stop_reason: "end_turn", usage: { input_tokens: 1, output_tokens: 1 }, citations: [] },
          },
        ]);
      }),
    });
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    await act(async () => {
      result.current.sendMessage("hi");
      await Promise.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.isSending).toBe(false));

    expect(api.createSession).toHaveBeenCalledTimes(2); // bootstrap + retry
    expect(api.sendMessage).toHaveBeenCalledTimes(2);
    expect(result.current.messages[1]).toMatchObject({ status: "complete" });
    expect(result.current.errorBanner).toBeNull();
  });

  it("shows a friendly error and marks the message failed when the retry also fails", async () => {
    const api = makeApi({
      sendMessage: vi.fn().mockImplementation(() => throwingEvents(new ApiError(401, "session_expired", "expired"))),
    });
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    await act(async () => {
      result.current.sendMessage("hi");
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.isSending).toBe(false));

    expect(result.current.messages[1]).toMatchObject({ status: "failed" });
    expect(result.current.errorBanner).toBe("Your session expired. Please refresh the page.");
  });

  it("maps a non-auth ApiError to a friendly banner without retrying", async () => {
    const api = makeApi({
      sendMessage: vi.fn().mockImplementation(() => throwingEvents(new ApiError(402, "quota_exceeded", "no quota"))),
    });
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    await act(async () => {
      result.current.sendMessage("hi");
      await Promise.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.isSending).toBe(false));

    expect(api.createSession).toHaveBeenCalledTimes(1); // bootstrap only, no retry
    expect(result.current.messages[1]).toMatchObject({ status: "failed" });
    expect(result.current.errorBanner).toBe("The assistant is temporarily unavailable. Please try again shortly.");
  });

  it("surfaces an in-stream error event without throwing", async () => {
    const api = makeApi({
      sendMessage: vi.fn().mockImplementation(() =>
        asyncEvents([{ event: "error", data: { code: "rate_limited", message: "slow down" } }]),
      ),
    });
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    await act(async () => {
      result.current.sendMessage("hi");
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.isSending).toBe(false));

    expect(result.current.messages[1]).toMatchObject({ status: "failed" });
    expect(result.current.errorBanner).toBe("You're sending messages a little fast — please wait a moment and try again.");
  });

  it("is a no-op while a send is already in flight", async () => {
    let resolveSend!: () => void;
    const api = makeApi({
      sendMessage: vi.fn().mockImplementation(
        () =>
          // eslint-disable-next-line require-yield -- simulates a stream that's still open, before any event has arrived
          (async function* (): AsyncGenerator<SseEvent> {
            await new Promise<void>((resolve) => {
              resolveSend = resolve;
            });
          })(),
      ),
    });
    const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    act(() => {
      result.current.sendMessage("first");
    });
    await waitFor(() => expect(result.current.isSending).toBe(true));

    act(() => {
      result.current.sendMessage("second");
    });

    expect(api.createConversation).toHaveBeenCalledTimes(1);
    expect(result.current.messages).toHaveLength(2);

    await act(async () => {
      resolveSend();
      await Promise.resolve();
    });
  });

  describe("sendVoiceMessage", () => {
    const AUDIO = new Blob(["fake-audio"], { type: "audio/webm" });

    it("appends the transcript and reply as complete bubbles and resolves an audioUrl", async () => {
      const api = makeApi();
      const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
      await waitFor(() => expect(result.current.status).toBe("ready"));

      let audioUrl: string | undefined;
      await act(async () => {
        const outcome = await result.current.sendVoiceMessage(AUDIO, "recording.webm");
        audioUrl = outcome ? outcome.audioUrl : undefined;
      });

      expect(result.current.messages).toHaveLength(2);
      expect(result.current.messages[0]).toMatchObject({ role: "user", content: "hello", status: "complete" });
      expect(result.current.messages[1]).toMatchObject({
        role: "assistant",
        content: "hi there",
        status: "complete",
      });
      expect(audioUrl).toMatch(/^blob:/);
      expect(result.current.isSending).toBe(false);
      expect(api.createConversation).toHaveBeenCalledTimes(1);
    });

    it("resolves void (no audioUrl) when the reply has no audio", async () => {
      const api = makeApi({
        sendVoiceMessage: vi.fn().mockResolvedValue({
          transcript: "hello",
          message: { id: "m1", role: "assistant", content: "hi", citations: null, created_at: "now" },
          audio_base64: "",
          audio_mime: "audio/mpeg",
        } satisfies VoiceReplyResponse),
      });
      const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
      await waitFor(() => expect(result.current.status).toBe("ready"));

      let outcome: { audioUrl: string } | void = undefined;
      await act(async () => {
        outcome = await result.current.sendVoiceMessage(AUDIO, "recording.webm");
      });

      expect(outcome).toBeUndefined();
      expect(result.current.messages).toHaveLength(2);
    });

    it("reuses the conversation id across a text send and a voice send", async () => {
      const api = makeApi();
      const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
      await waitFor(() => expect(result.current.status).toBe("ready"));

      await act(async () => {
        result.current.sendMessage("hi");
        await Promise.resolve();
      });
      await waitFor(() => expect(result.current.isSending).toBe(false));

      await act(async () => {
        await result.current.sendVoiceMessage(AUDIO, "recording.webm");
      });

      expect(api.createConversation).toHaveBeenCalledTimes(1);
    });

    it("on an auth error, refreshes the session and retries exactly once, succeeding", async () => {
      let call = 0;
      const api = makeApi({
        sendVoiceMessage: vi.fn().mockImplementation(() => {
          call += 1;
          if (call === 1) return Promise.reject(new ApiError(401, "session_expired", "expired"));
          return Promise.resolve({
            transcript: "hello",
            message: { id: "m1", role: "assistant", content: "hi", citations: null, created_at: "now" },
            audio_base64: "",
            audio_mime: "audio/mpeg",
          } satisfies VoiceReplyResponse);
        }),
      });
      const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
      await waitFor(() => expect(result.current.status).toBe("ready"));

      await act(async () => {
        await result.current.sendVoiceMessage(AUDIO, "recording.webm");
      });

      expect(api.createSession).toHaveBeenCalledTimes(2); // bootstrap + retry
      expect(api.sendVoiceMessage).toHaveBeenCalledTimes(2);
      expect(result.current.messages).toHaveLength(2);
      expect(result.current.errorBanner).toBeNull();
    });

    it("shows a friendly error and appends nothing when the retry also fails", async () => {
      const api = makeApi({
        sendVoiceMessage: vi
          .fn()
          .mockImplementation(() => Promise.reject(new ApiError(401, "session_expired", "expired"))),
      });
      const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
      await waitFor(() => expect(result.current.status).toBe("ready"));

      await act(async () => {
        await result.current.sendVoiceMessage(AUDIO, "recording.webm");
      });

      expect(result.current.messages).toHaveLength(0);
      expect(result.current.errorBanner).toBe("Your session expired. Please refresh the page.");
    });

    it("maps a non-auth ApiError to a friendly banner without retrying", async () => {
      const api = makeApi({
        sendVoiceMessage: vi
          .fn()
          .mockImplementation(() => Promise.reject(new ApiError(422, "empty_transcript", "silent"))),
      });
      const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
      await waitFor(() => expect(result.current.status).toBe("ready"));

      await act(async () => {
        await result.current.sendVoiceMessage(AUDIO, "recording.webm");
      });

      expect(api.createSession).toHaveBeenCalledTimes(1); // bootstrap only, no retry
      expect(result.current.messages).toHaveLength(0);
      expect(result.current.errorBanner).toBe("Something went wrong. Please try again.");
    });

    it("is a no-op while a send is already in flight", async () => {
      let resolveVoice!: (value: VoiceReplyResponse) => void;
      const api = makeApi({
        sendVoiceMessage: vi.fn().mockImplementation(
          () =>
            new Promise<VoiceReplyResponse>((resolve) => {
              resolveVoice = resolve;
            }),
        ),
      });
      const { result } = renderHook(() => useChat(api, PUBLIC_KEY));
      await waitFor(() => expect(result.current.status).toBe("ready"));

      act(() => {
        void result.current.sendVoiceMessage(AUDIO, "recording.webm");
      });
      await waitFor(() => expect(result.current.isSending).toBe(true));

      act(() => {
        void result.current.sendVoiceMessage(AUDIO, "recording.webm");
      });

      expect(api.sendVoiceMessage).toHaveBeenCalledTimes(1);

      await act(async () => {
        resolveVoice({
          transcript: "hello",
          message: { id: "m1", role: "assistant", content: "hi", citations: null, created_at: "now" },
          audio_base64: "",
          audio_mime: "audio/mpeg",
        });
        await Promise.resolve();
      });
    });
  });
});
