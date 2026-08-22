"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter, usePathname } from "next/navigation";

type AuthState = { email: string | null; ready: boolean };

const AuthContext = createContext<AuthState>({ email: null, ready: false });

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ email: null, ready: false });
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    let cancelled = false;
    fetch("/backend/api/auth/me")
      .then((res) => (res.ok ? res.json() : Promise.reject()))
      .then((data) => {
        if (cancelled) return;
        setState({ email: data.email, ready: true });
      })
      .catch(() => {
        if (cancelled) return;
        setState({ email: null, ready: true });
        if (pathname !== "/login") {
          router.replace(`/login?next=${encodeURIComponent(pathname)}`);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  // Gate protected pages until we know auth state (or once we know it's missing —
  // the redirect above is already in flight).
  if (pathname !== "/login" && (!state.ready || !state.email)) {
    return null;
  }

  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>;
}
