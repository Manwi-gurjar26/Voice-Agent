// Mirrors backend/app/schemas/auth.py and backend/app/schemas/agent.py.
// Kept as plain types, not generated, matching the same tradeoff
// widget/src/types.ts documents: the API surface this app depends on is
// small and stable enough that hand-maintained types are simpler than a
// codegen pipeline.

export type PlanTier = "free" | "starter" | "pro" | "enterprise";
export type UserRole = "owner" | "admin" | "member";
export type AgentStatus = "draft" | "active" | "disabled";
export type EffortLevel = "low" | "medium" | "high" | "xhigh" | "max";

export interface AgentTheme {
  primaryColor?: string;
  position?: "bottom-right" | "bottom-left" | string;
  launcherIcon?: string;
  bubbleRadius?: number;
}

export interface SignupRequest {
  email: string;
  password: string;
  full_name?: string | null;
  company_name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface TenantRead {
  id: string;
  name: string;
  slug: string;
  plan: PlanTier;
  monthly_message_quota: number;
  messages_used_in_period: number;
  period_started_at: string;
}

export type PaidPlan = "starter" | "pro" | "enterprise";

export interface CheckoutSessionResponse {
  url: string;
}

export interface PortalSessionResponse {
  url: string;
}

export interface UserRead {
  id: string;
  email: string;
  full_name: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface MeResponse {
  user: UserRead;
  tenant: TenantRead;
}

export interface AgentCreate {
  name: string;
  system_prompt?: string | null;
  greeting?: string | null;
  model?: string | null;
  effort: EffortLevel;
  max_output_tokens: number;
  voice_enabled: boolean;
  voice_id?: string | null;
  theme?: AgentTheme | null;
  allowed_origins: string[];
}

export interface AgentUpdate {
  name?: string;
  status?: AgentStatus;
  system_prompt?: string | null;
  greeting?: string | null;
  model?: string | null;
  effort?: EffortLevel;
  max_output_tokens?: number;
  voice_enabled?: boolean;
  voice_id?: string | null;
  theme?: AgentTheme | null;
  allowed_origins?: string[];
  rate_limit_per_minute?: number;
}

export interface AgentRead {
  id: string;
  name: string;
  public_key: string;
  status: AgentStatus;
  system_prompt: string;
  greeting: string;
  model: string;
  effort: EffortLevel;
  max_output_tokens: number;
  voice_enabled: boolean;
  voice_id: string | null;
  theme: AgentTheme;
  allowed_origins: string[];
  rate_limit_per_minute: number;
  created_at: string;
  updated_at: string;
  embed_snippet: string;
}

export interface AgentListResponse {
  items: AgentRead[];
  total: number;
}

export type DocumentSourceType = "text" | "file" | "url" | "crawl";
export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export interface DocumentRead {
  id: string;
  source_type: DocumentSourceType;
  title: string;
  source_url: string | null;
  original_filename: string | null;
  status: DocumentStatus;
  error_message: string | null;
  char_count: number | null;
  created_at: string;
}

export interface DocumentListResponse {
  items: DocumentRead[];
}

export interface DocumentCreateCrawl {
  url: string;
  limit?: number;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

// --- Analytics (mirrors backend/app/schemas/analytics.py) ---

export interface DailyPoint {
  day: string;
  conversations: number;
  messages: number;
  sessions: number;
  input_tokens: number;
  output_tokens: number;
}

export interface PeriodTotals {
  conversations: number;
  messages: number;
  user_messages: number;
  assistant_messages: number;
  sessions: number;
  input_tokens: number;
  output_tokens: number;
  cited_replies: number;
  voice_agents_used: number;
}

export interface AgentUsage {
  id: string;
  name: string;
  status: AgentStatus;
  voice_enabled: boolean;
  conversations: number;
  messages: number;
  input_tokens: number;
  output_tokens: number;
  last_activity_at: string | null;
}

export interface OriginUsage {
  origin: string;
  sessions: number;
}

export interface KnowledgeBaseStats {
  documents: number;
  ready: number;
  pending: number;
  processing: number;
  failed: number;
  characters: number;
}

export interface QuotaStats {
  plan: PlanTier;
  used: number;
  quota: number;
  remaining: number;
  percent_used: number;
  period_started_at: string;
}

export interface RecentConversation {
  id: string;
  agent_id: string;
  agent_name: string;
  messages: number;
  started_at: string;
  last_message_at: string | null;
}

export interface AnalyticsOverview {
  generated_at: string;
  range_days: number;
  range_start: string;
  totals: PeriodTotals;
  previous_totals: PeriodTotals;
  daily: DailyPoint[];
  agents: AgentUsage[];
  origins: OriginUsage[];
  knowledge_base: KnowledgeBaseStats;
  quota: QuotaStats;
  recent_conversations: RecentConversation[];
  agents_total: number;
  agents_active: number;
}

// --- Preview (mirrors backend/app/api/v1/preview.py) ---
// The message/citation shapes are the same rows the widget renders; kept
// here rather than imported from widget/ because the two apps build and
// deploy independently.

export interface Citation {
  document_id: string;
  title: string;
}

export interface AgentPublicConfig {
  name: string;
  greeting: string;
  voice_enabled: boolean;
  theme: AgentTheme;
}

export interface ConversationRead {
  id: string;
  created_at: string;
}

export interface MessageRead {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  created_at: string;
}

export interface VoiceReplyResponse {
  transcript: string;
  message: MessageRead;
  audio_base64: string;
  audio_mime: string;
}

export interface SseDoneData {
  message_id: string;
  stop_reason: string | null;
  usage: { input_tokens: number; output_tokens: number };
  citations: Citation[];
}

export type PreviewStreamEvent =
  | { event: "delta"; data: { text: string } }
  | { event: "done"; data: SseDoneData }
  | { event: "error"; data: { code: string; message: string } };
