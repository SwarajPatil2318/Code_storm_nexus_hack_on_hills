"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { operatorRequest } from "@/lib/operator-api";
export function useResource<T>(path: string | null) {
  const [result, setResult] = useState<{
    path: string;
    revision: number;
    data: T | null;
    error: string;
  } | null>(null);
  const [revision, setRevision] = useState(0);
  const pending = useRef<AbortController | null>(null);
  // Coalesce polling while a bounded request is in flight. Aborting on every
  // interval can starve slower real API responses indefinitely.
  const reload = useCallback(() => {
    if (!pending.current) setRevision((value) => value + 1);
  }, []);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    pending.current = controller;
    operatorRequest<T>(path, {
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]),
    })
      .then((data) => {
        if (!controller.signal.aborted) setResult({ path, revision, data, error: "" });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setResult({
            path,
            revision,
            data: null,
            error: error instanceof Error ? error.message : "Request failed",
          });
      })
      .finally(() => {
        if (pending.current === controller) pending.current = null;
      });
    return () => {
      controller.abort();
      if (pending.current === controller) pending.current = null;
    };
  }, [path, revision]);
  // Retain only the last result for this exact path during refresh. Changing
  // evaluation or identity navigation never reuses another path's data.
  const current = result?.path === path ? result : null;
  return {
    data: current?.data ?? null,
    error: current?.error ?? "",
    loading: Boolean(path && !current),
    refreshing: Boolean(path && current && current.revision !== revision),
    reload,
  };
}
