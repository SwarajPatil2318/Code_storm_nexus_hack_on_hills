"use client";
import { resetIdentityNavigation } from "@/lib/operator-api";
import { createContext, useContext, useEffect, useState } from "react";
import { operatorRequest } from "@/lib/operator-api";
import type { OperatorSession } from "@/lib/auth-types";
const Context = createContext<{
  session: OperatorSession;
  logout: () => Promise<void>;
  loggingOut: boolean;
} | null>(null);
export function AuthProvider({
  session,
  children,
}: {
  session: OperatorSession;
  children: React.ReactNode;
}) {
  const [loggingOut, setLoggingOut] = useState(false);
  useEffect(() => {
    const expire = () => resetIdentityNavigation("/login");
    const timer = setTimeout(expire, Math.max(0, Date.parse(session.expires_at) - Date.now()));
    window.addEventListener("nexus:unauthorized", expire);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("nexus:unauthorized", expire);
    };
  }, [session.expires_at]);
  async function logout() {
    setLoggingOut(true);
    try {
      await operatorRequest("/auth/logout", { method: "POST", csrf: session.csrf_token });
      resetIdentityNavigation("/login");
    } finally {
      setLoggingOut(false);
    }
  }
  return <Context.Provider value={{ session, logout, loggingOut }}>{children}</Context.Provider>;
}
export function useAuth() {
  const value = useContext(Context);
  if (!value) throw new Error("Authenticated operator context is required");
  return value;
}
