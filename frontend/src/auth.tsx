import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, setUnauthorizedHandler, tokenStore } from "./api";

interface AuthState {
  email: string | null;
  loading: boolean;
  login: (token: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(null);
  const [loading, setLoading] = useState(tokenStore.get() !== null);

  const logout = useCallback(() => {
    tokenStore.clear();
    setEmail(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!tokenStore.get()) return;
    api
      .me()
      .then((me) => setEmail(me.email))
      .catch(() => {}) // a 401 already triggered logout
      .finally(() => setLoading(false));
  }, [logout]);

  const login = useCallback(async (token: string) => {
    tokenStore.set(token);
    setEmail((await api.me()).email);
  }, []);

  const value = useMemo(() => ({ email, loading, login, logout }), [email, loading, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
