import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";
import type { Me } from "./types";

interface AuthState { me: Me | null; loading: boolean; login: (u: string, p: string) => Promise<void>; logout: () => void; }
const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState<boolean>(!!getToken());
  const qc = useQueryClient();

  const logout = useCallback(() => { setToken(null); setMe(null); qc.clear(); }, [qc]);
  useEffect(() => { setUnauthorizedHandler(logout); }, [logout]);
  useEffect(() => {
    if (!getToken()) return;
    api.me().then(setMe).catch(() => setToken(null)).finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (u: string, p: string) => {
    const { access_token } = await api.login(u, p);
    setToken(access_token);
    setMe(await api.me());
  }, []);

  const value = useMemo(() => ({ me, loading, login, logout }), [me, loading, login, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
