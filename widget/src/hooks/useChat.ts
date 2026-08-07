import { useEffect, useRef, useState } from "preact/hooks";
import { ApiError, type ApiClient } from "../api";
import * as storage from "../storage";
import type { AgentPublicConfig, ChatMessage, Citation } from "../types";

export type ChatStatus = "bootstrapping" | "ready" | "unavailable";

export interface ChatState {
  status: ChatStatus;
  config: AgentPublicConfig | null;
  messages: ChatMessage[];
  isSending: boolean;
  errorBanner: string | null;
  sendMessage: (content: string) => void;
  sendVoiceMessage: (audioBlob: Blob, filename: string) => Promise<{ audioUrl: string } | void>;
}

const AUTH_ERROR_CODES = new Set(["unauthenticated", "session_expired"]);

function friendlyErrorMessage(code: string): string {
  switch (code) {
    case "quota_exceeded":
    case "llm_error":
      return "The assistant is temporarily unavailable. Please try again shortly.";
    case "rate_limited":
      return "You're sending messages a little fast — please wait a moment and try again.";
    case "unauthenticated":
    case "session_expired":
      return "Your session expired. Please refresh the page.";
    default:
      return "Something went wrong. Please try again.";
  }
}

/** Decodes a base64 audio payload (see VoiceReplyResponse) into a playable
 * object URL. Callers are responsible for revoking it once played. */
function decodeAudioToUrl(base64: string, mime: string): string {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type: mime }));
}

export function useChat(api: ApiClient, publicKey: string): ChatState {
  const [status, setStatus] = useState<ChatStatus>("bootstrapping");
  const [config, setConfig] = useState<AgentPublicConfig | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Refs, not state: these drive request logic between renders but never
  // themselves need to trigger a re-render.
  const sessionTokenRef = useRef<string | null>(null);
  const conversationIdRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap(): Promise<void> {
      let fetchedConfig: AgentPublicConfig;
      try {
        fetchedConfig = await api.getConfig();
      } catch (err) {
        // Deliberately silent beyond a console line: a misconfigured origin
        // allowlist or a backend outage is the business owner's problem to
        // fix, not something worth showing every site visitor a broken
        // widget over. See README.
        console.error("[voice-agent-widget] could not load widget config:", err);
        if (!cancelled) setStatus("unavailable");
        return;
      }
      if (cancelled) return;
      setConfig(fetchedConfig);

      const token = await resolveSessionToken();
      if (!token) {
        if (!cancelled) setStatus("unavailable");
        return;
      }
      sessionTokenRef.current = token;

      await tryResumeConversation(token, cancelled);
      if (!cancelled) setStatus("ready");
    }

    async function resolveSessionToken(): Promise<string | null> {
      const stored = storage.loadStoredSession(publicKey);
      if (stored) {
        try {
          if (await api.validateSession(stored.token)) return stored.token;
        } catch {
          // fall through to creating a fresh one
        }
      }
      try {
        const session = await api.createSession();
        storage.storeSession(publicKey, session.session_token, session.expires_in);
        return session.session_token;
      } catch (err) {
        console.error("[voice-agent-widget] could not start a session:", err);
        return null;
      }
    }

    async function tryResumeConversation(token: string, alreadyCancelled: boolean): Promise<void> {
      const storedConversationId = storage.loadStoredConversationId(publicKey);
      if (!storedConversationId) return;
      try {
        const history = await api.listMessages(token, storedConversationId);
        if (history.length === 0 || alreadyCancelled) return;
        conversationIdRef.current = storedConversationId;
        setMessages(
          history.map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            citations: m.citations,
            status: "complete" as const,
          })),
        );
      } catch {
        // Stored id is stale (expired session, deleted conversation, etc.) —
        // a fresh conversation is created lazily on the next send, same as
        // if nothing had been stored at all.
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
    // publicKey identifies which widget instance this is; api is created
    // once per mount alongside it and never changes independently, so it's
    // deliberately left out of the dependency array.
  }, [publicKey]);

  /** Runs `action`, and on a mid-visit session-expiry error (the 60-minute
   * widget session is real for anyone keeping a tab open), transparently
   * refreshes the session and retries exactly once — most visitors should
   * never see "please refresh the page" just because they were reading for a
   * while before interacting. Shared between text and voice sends, since the
   * retry logic is identical for both. */
  async function withSessionRetry(
    action: () => Promise<void>,
    onFailure: (err: unknown) => void,
  ): Promise<void> {
    try {
      await action();
    } catch (err) {
      if (err instanceof ApiError && AUTH_ERROR_CODES.has(err.code)) {
        storage.clearSession(publicKey);
        conversationIdRef.current = null;
        try {
          const session = await api.createSession();
          storage.storeSession(publicKey, session.session_token, session.expires_in);
          sessionTokenRef.current = session.session_token;
          await action();
        } catch (retryErr) {
          onFailure(retryErr);
        }
      } else {
        onFailure(err);
      }
    }
  }

  async function sendMessage(content: string): Promise<void> {
    const trimmed = content.trim();
    if (!trimmed || isSending || status !== "ready" || !sessionTokenRef.current) return;

    setErrorBanner(null);
    const userMessageId = `local-user-${Date.now()}`;
    const assistantMessageId = `local-assistant-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: userMessageId, role: "user", content: trimmed, citations: null, status: "complete" },
      { id: assistantMessageId, role: "assistant", content: "", citations: null, status: "streaming" },
    ]);
    setIsSending(true);

    const updateAssistant = (patch: Partial<ChatMessage>) =>
      setMessages((prev) => prev.map((m) => (m.id === assistantMessageId ? { ...m, ...patch } : m)));

    try {
      await withSessionRetry(
        () => attemptSend(trimmed, updateAssistant),
        (err) => handleSendFailure(err, updateAssistant),
      );
    } finally {
      setIsSending(false);
    }
  }

  async function sendVoiceMessage(
    audioBlob: Blob,
    filename: string,
  ): Promise<{ audioUrl: string } | void> {
    if (isSending || status !== "ready" || !sessionTokenRef.current) return;

    setErrorBanner(null);
    // Transcription + local TTS runs on CPU and can take a while — placeholder
    // bubbles go up immediately (mirroring sendMessage's streaming assistant
    // bubble) so the panel doesn't look frozen while that happens. Both get
    // patched in place once the real transcript/reply come back.
    const userMessageId = `local-user-${Date.now()}`;
    const assistantMessageId = `local-assistant-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: userMessageId, role: "user", content: "🎤 Voice message", citations: null, status: "complete" },
      { id: assistantMessageId, role: "assistant", content: "", citations: null, status: "streaming" },
    ]);
    setIsSending(true);

    let result: { audioUrl: string } | undefined;

    async function attemptVoiceSend(): Promise<void> {
      const token = sessionTokenRef.current;
      if (!token) throw new ApiError(401, "unauthenticated", "No session token.");

      let conversationId = conversationIdRef.current;
      if (!conversationId) {
        const conversation = await api.createConversation(token);
        conversationId = conversation.id;
        conversationIdRef.current = conversationId;
        storage.storeConversationId(publicKey, conversationId);
      }

      const reply = await api.sendVoiceMessage(token, conversationId, audioBlob, filename);
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id === userMessageId) return { ...m, content: reply.transcript };
          if (m.id === assistantMessageId) {
            return {
              ...m,
              id: reply.message.id,
              content: reply.message.content,
              citations: reply.message.citations,
              status: "complete",
            };
          }
          return m;
        }),
      );
      result = reply.audio_base64
        ? { audioUrl: decodeAudioToUrl(reply.audio_base64, reply.audio_mime) }
        : undefined;
    }

    try {
      await withSessionRetry(attemptVoiceSend, (err) => {
        const code = err instanceof ApiError ? err.code : "unknown_error";
        setErrorBanner(friendlyErrorMessage(code));
        setMessages((prev) => prev.map((m) => (m.id === assistantMessageId ? { ...m, status: "failed" } : m)));
      });
    } finally {
      setIsSending(false);
    }
    return result;
  }

  async function attemptSend(
    trimmed: string,
    updateAssistant: (patch: Partial<ChatMessage>) => void,
  ): Promise<void> {
    const token = sessionTokenRef.current;
    if (!token) throw new ApiError(401, "unauthenticated", "No session token.");

    let conversationId = conversationIdRef.current;
    if (!conversationId) {
      const conversation = await api.createConversation(token);
      conversationId = conversation.id;
      conversationIdRef.current = conversationId;
      storage.storeConversationId(publicKey, conversationId);
    }

    let accumulated = "";
    for await (const event of api.sendMessage(token, conversationId, trimmed)) {
      if (event.event === "delta") {
        accumulated += event.data.text;
        updateAssistant({ content: accumulated });
      } else if (event.event === "done") {
        const citations: Citation[] = event.data.citations;
        updateAssistant({ status: "complete", citations });
      } else if (event.event === "error") {
        updateAssistant({ status: "failed" });
        setErrorBanner(friendlyErrorMessage(event.data.code));
      }
    }
  }

  function handleSendFailure(
    err: unknown,
    updateAssistant: (patch: Partial<ChatMessage>) => void,
  ): void {
    updateAssistant({ status: "failed" });
    const code = err instanceof ApiError ? err.code : "unknown_error";
    setErrorBanner(friendlyErrorMessage(code));
  }

  return { status, config, messages, isSending, errorBanner, sendMessage, sendVoiceMessage };
}
