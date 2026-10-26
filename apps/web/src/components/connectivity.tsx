"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { ApiError, getHealth, getReadiness, type Health, type Readiness } from "@/lib/api";
type Connection = {
  status: "checking" | "online" | "offline" | "error";
  health: Health | null;
  readiness: Readiness | null;
  readinessError: string | null;
  message: string;
  checkedAt: Date | null;
  checking: boolean;
  refresh: () => void;
};
const Context = createContext<Connection | null>(null);
export function ConnectivityProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<Omit<Connection, "refresh">>({
    status: "checking",
    health: null,
    readiness: null,
    readinessError: null,
    message: "Connecting to the NEXUS API…",
    checkedAt: null,
    checking: true,
  });
  const active = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const timeout = setTimeout(() => controller.abort("timeout"), 6000);
    setState((previous) => ({ ...previous, checking: true }));
    try {
      const [healthResult, readyResult] = await Promise.allSettled([
        getHealth(controller.signal),
        getReadiness(controller.signal),
      ]);
      if (controller.signal.aborted && controller.signal.reason !== "timeout") return;
      if (healthResult.status === "rejected") throw healthResult.reason;
      setState({
        status: "online",
        health: healthResult.value,
        readiness: readyResult.status === "fulfilled" ? readyResult.value : null,
        readinessError:
          readyResult.status === "rejected" ? "Readiness could not be verified." : null,
        message: "Live response from the NEXUS API.",
        checkedAt: new Date(),
        checking: false,
      });
    } catch (error) {
      if (controller.signal.aborted && controller.signal.reason !== "timeout") return;
      setState({
        status: error instanceof ApiError ? "error" : "offline",
        health: null,
        readiness: null,
        readinessError: null,
        message:
          error instanceof ApiError
            ? error.message
            : "The API could not be reached. Check that it is running and CORS allows this origin.",
        checkedAt: new Date(),
        checking: false,
      });
    } finally {
      clearTimeout(timeout);
    }
  }, []);
  useEffect(() => {
    const initial = setTimeout(() => void refresh(), 0);
    const interval = setInterval(() => void refresh(), 15000);
    return () => {
      clearTimeout(initial);
      clearInterval(interval);
      active.current?.abort();
    };
  }, [refresh]);
  return <Context.Provider value={{ ...state, refresh }}>{children}</Context.Provider>;
}
export function useConnectivity() {
  const value = useContext(Context);
  if (!value) throw new Error("ConnectivityProvider is required");
  return value;
}
