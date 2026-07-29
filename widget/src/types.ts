// Mirrors app/schemas/public.py and app/schemas/chat.py on the backend.
// Kept as plain types, not generated, since the public API surface this
// widget depends on is small and stable — see README for the tradeoff.

export interface WidgetTheme {
  primaryColor?: string;
  position?: "bottom-right" | "bottom-left" | string;
  launcherIcon?: string;
  bubbleRadius?: number;
}

export interface AgentPublicConfig {
  name: string;
  greeting: string;
  voice_enabled: boolean;
  theme: WidgetTheme;
}

export interface WidgetSessionResponse {
  session_token: string;
  token_type: string;
  expires_in: number;
}

export interface ConversationRead {
  id: string;
  created_at: string;
}

export interface Citation {
  document_id: string;
  title: string;
}

export interface MessageRead {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  created_at: string;
}

// --- Voice (Step 7) ---
export interface VoiceReplyResponse {
  transcript: string;
  message: MessageRead;
  audio_base64: string;
  audio_mime: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

// --- SSE event payloads (app/services/chat.py's _sse()) ---
export interface SseDeltaData {
  text: string;
}

export interface SseDoneData {
  message_id: string;
  stop_reason: string | null;
  usage: { input_tokens: number; output_tokens: number };
  citations: Citation[];
}

export interface SseErrorData {
  code: string;
  message: string;
}

export type SseEvent =
  | { event: "delta"; data: SseDeltaData }
  | { event: "done"; data: SseDoneData }
  | { event: "error"; data: SseErrorData };

// --- UI-level chat message (includes locally-synthesized ones, e.g. the
// greeting, which never round-trips through the API as a Message row) ---
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  status: "complete" | "streaming" | "failed";
}
