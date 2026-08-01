"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import * as api from "./api";
import { clearAuth, loadAuth } from "./auth-storage";
import type { LoginRequest, SignupRequest, TenantRead, UserRead } from "./types";

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  status: AuthStatus;
  user: UserRead | null;
  tenant: TenantRead | null;
  login: (payload: LoginRequest) => Promise<void>;
  signup: (payload: SignupRequest) => Promise<void>;
  logout: () => Promise<void>;
  /** Re-fetches user/tenant without touching auth status — used after
   * returning from Dodo Checkout, since the webhook that updates the
   * tenant's plan lands asynchronously and the cached context is stale. */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<UserRead | null>(null);
  const [tenant, setTenant] = useState<TenantRead | null>(null);

  const markSignedOut = useCallback(() => {
    setUser(null);
    setTenant(null);
    setStatus("unauthenticated");
  }, []);

  const loadCurrentUser = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me.user);
      setTenant(me.tenant);
      setStatus("authenticated");
    } catch {
      // A stored token that no longer resolves (revoked, expired refresh,
      // deactivated account) is the same as never having been signed in.
      clearAuth();
      markSignedOut();
    }
  }, [markSignedOut]);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      if (!loadAuth()) {
        if (!cancelled) markSignedOut();
        return;
      }
      if (!cancelled) await loadCurrentUser();
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [markSignedOut, loadCurrentUser]);

  const login = useCallback(
    async (payload: LoginRequest) => {
      await api.login(payload);
      await loadCurrentUser();
    },
    [loadCurrentUser],
  );

  const signup = useCallback(
    async (payload: SignupRequest) => {
      await api.signup(payload);
      await loadCurrentUser();
    },
    [loadCurrentUser],
  );

  const logout = useCallback(async () => {
    await api.logout();
    markSignedOut();
  }, [markSignedOut]);

  return (
    <AuthContext.Provider value={{ status, user, tenant, login, signup, logout, refresh: loadCurrentUser }}>
      {children}
    </AuthContext.Provider>
  );
}
