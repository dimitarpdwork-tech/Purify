"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, clearSession, getStoredUser, getToken, setSession, type SessionUser } from "@/lib/api";

interface AuthCtx { user: SessionUser | null; logout: () => void; can: (role: "analyst" | "admin") => boolean }
const Ctx = createContext<AuthCtx>({ user: null, logout: () => {}, can: () => false });

const RANK = { viewer: 0, analyst: 1, admin: 2 } as const;

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [ready, setReady] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    setUser(getStoredUser());
    setReady(true);
    // Refresh identity (role may have changed). 401 is handled by api() -> /login.
    api<SessionUser>("/api/auth/me").then((u) => { setUser(u); setSession(token, u); }).catch(() => {});
  }, [router, pathname]);

  const logout = () => {
    clearSession();
    router.replace("/login");
  };
  const can = (role: "analyst" | "admin") => !!user && RANK[user.role] >= RANK[role];

  if (!ready) return <div className="p-6 text-sm text-muted">Checking session…</div>;
  return <Ctx.Provider value={{ user, logout, can }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
