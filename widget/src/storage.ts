// sessionStorage persistence, namespaced per agent public_key so more than
// one widget on the same host page (unusual, but not forbidden) can't
// collide. Scoped to sessionStorage, not localStorage, deliberately: a
// widget session already expires server-side after
// settings.widget_session_expire_minutes — surviving a full browser restart
// would outlive what the token itself is good for anyway, and sessionStorage
// naturally clears when the tab closes.
//
// Every read/write is wrapped in try/catch: sessionStorage can throw in
// private-browsing edge cases or storage-restricted iframes. Losing
// persistence should degrade to "start a fresh session," never crash the
// widget.

interface StoredSession {
  token: string;
  expiresAt: number; // epoch ms
}

function sessionKey(publicKey: string): string {
  return `voiceagent:${publicKey}:session`;
}

function conversationKey(publicKey: string): string {
  return `voiceagent:${publicKey}:conversation`;
}

export function loadStoredSession(publicKey: string): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(sessionKey(publicKey));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    if (typeof parsed.token !== "string" || typeof parsed.expiresAt !== "number") return null;
    if (parsed.expiresAt <= Date.now()) return null; // expired locally — don't even try it
    return { token: parsed.token, expiresAt: parsed.expiresAt };
  } catch {
    return null;
  }
}

export function storeSession(publicKey: string, token: string, expiresInSeconds: number): void {
  try {
    const stored: StoredSession = { token, expiresAt: Date.now() + expiresInSeconds * 1000 };
    sessionStorage.setItem(sessionKey(publicKey), JSON.stringify(stored));
  } catch {
    // no persistence this time — the widget still works, just re-bootstraps
    // a session on the next page load instead of reusing one.
  }
}

export function clearSession(publicKey: string): void {
  try {
    sessionStorage.removeItem(sessionKey(publicKey));
    sessionStorage.removeItem(conversationKey(publicKey));
  } catch {
    // nothing to do
  }
}

export function loadStoredConversationId(publicKey: string): string | null {
  try {
    return sessionStorage.getItem(conversationKey(publicKey));
  } catch {
    return null;
  }
}

export function storeConversationId(publicKey: string, conversationId: string): void {
  try {
    sessionStorage.setItem(conversationKey(publicKey), conversationId);
  } catch {
    // conversation still works for this page view — just won't be resumed
    // after a navigation.
  }
}
