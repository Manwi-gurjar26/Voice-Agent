// Token persistence — mirrors widget/src/storage.ts's shape (try/catch
// around every read/write, so a storage-restricted context degrades to
// "start signed out" instead of crashing the app). localStorage, not
// sessionStorage: a dashboard session should survive closing the tab.

const STORAGE_KEY = "voiceagent-dashboard:auth";

export interface StoredAuth {
  accessToken: string;
  accessExpiresAt: number;
  refreshToken: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

function isStoredAuth(value: unknown): value is StoredAuth {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.accessToken === "string" &&
    typeof candidate.accessExpiresAt === "number" &&
    typeof candidate.refreshToken === "string"
  );
}

export function loadAuth(): StoredAuth | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isStoredAuth(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function storeAuth(tokens: TokenResponse): void {
  try {
    const auth: StoredAuth = {
      accessToken: tokens.access_token,
      accessExpiresAt: Date.now() + tokens.expires_in * 1000,
      refreshToken: tokens.refresh_token,
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(auth));
  } catch {
    // Private browsing / storage-restricted context — the user simply won't
    // stay signed in across a reload, rather than the app crashing.
  }
}

export function clearAuth(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Same reasoning as storeAuth.
  }
}

// A 5s skew avoids a race where the token expires between this check and
// the request that follows actually reaching the server.
const EXPIRY_SKEW_MS = 5_000;

export function isAccessTokenFresh(auth: StoredAuth): boolean {
  return auth.accessExpiresAt - EXPIRY_SKEW_MS > Date.now();
}
