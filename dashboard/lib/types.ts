// Mirrors backend/app/schemas/auth.py and backend/app/schemas/agent.py.
// Kept as plain types, not generated, matching the same tradeoff
// widget/src/types.ts documents: the API surface this app depends on is
// small and stable enough that hand-maintained types are simpler than a
// codegen pipeline.

export type PlanTier = "free" | "starter" | "pro" | "enterprise";
export type UserRole = "owner" | "admin" | "member";
export type AgentStatus = "draft" | "active" | "disabled";
export type EffortLevel = "low" | "medium" | "high" | "xhigh" | "max";

// OpenAI's fixed TTS voice names — mirrors ALLOWED_VOICE_IDS in
// backend/app/schemas/agent.py.
export const ALLOWED_VOICE_IDS = [
  "alloy",
  "ash",
  "ballad",
  "coral",
  "echo",
  "sage",
  "shimmer",
  "verse",
  "marin",
  "cedar",
] as const;
export type VoiceId = (typeof ALLOWED_VOICE_IDS)[number];

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

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}
