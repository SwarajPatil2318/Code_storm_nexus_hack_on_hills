"use client";
import { useEffect, useState } from "react";
import type { components } from "@/lib/api.generated";
import { WorkspaceApiError, operatorRequest } from "@/lib/operator-api";
import { orderedEvents, type XEvent } from "@/lib/xray-state";
type Page = components["schemas"]["HistoryPage"];
type Frame = components["schemas"]["LiveFrame"];
export const HISTORY_LIMIT = 10000;
export function useXrayFeed(evaluationId: string, live: boolean) {
  const empty = {
    id: evaluationId,
    events: [] as XEvent[],
    status: "Loading authorized history",
    error: "",
    watermark: 0,
    truncated: false,
    realtime: 0,
  };
  const [store, setStore] = useState(empty);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let closed = false,
      socket: WebSocket | undefined;
    let reconnect: ReturnType<typeof setTimeout> | undefined,
      flush: ReturnType<typeof setTimeout> | undefined;
    let cursor = 0,
      historyCursor = 0,
      attempts = 0,
      events: XEvent[] = [],
      watermark = 0,
      truncated = false,
      realtime = 0;
    let lastFrame = Date.now(),
      reconciling: Promise<void> | null = null,
      gapPending = false;
    const controller = new AbortController();
    const publish = (status: string, error = "") => {
      if (!closed)
        setStore({ id: evaluationId, events, status, error, watermark, truncated, realtime });
    };
    const merge = (incoming: XEvent[]) => {
      events = orderedEvents([...events, ...incoming], evaluationId);
      if (events.length > HISTORY_LIMIT) {
        events = events.slice(0, HISTORY_LIMIT);
        truncated = true;
      }
    };
    // REST coverage has its own cursor. A newer WebSocket cursor must never skip
    // a missed visible event; hidden raw sequences are not presumed missing data.
    const snapshot = async () => {
      let until: number | undefined;
      for (let pages = 0; pages < 10000; pages++) {
        const page = await operatorRequest<Page>(
          `/evaluations/${evaluationId}/history?after=${historyCursor}&limit=256${until === undefined ? "" : `&until=${until}`}`,
          { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]) },
        );
        if (
          page.evaluation_id !== evaluationId ||
          page.next_after < historyCursor ||
          page.high_watermark < page.next_after ||
          (page.has_more && page.next_after === historyCursor)
        )
          throw Error("Invalid history cursor");
        until = page.high_watermark;
        historyCursor = page.next_after;
        cursor = Math.max(cursor, historyCursor);
        watermark = Math.max(watermark, until);
        merge(page.events as XEvent[]);
        if ((events.length >= HISTORY_LIMIT || historyCursor >= HISTORY_LIMIT) && page.has_more) {
          truncated = true;
          return;
        }
        if (!page.has_more) return;
      }
    };
    const reconcile = () => {
      if (!reconciling)
        reconciling = snapshot().finally(() => {
          reconciling = null;
        });
      return reconciling;
    };
    const denied = (error: unknown) =>
      error instanceof WorkspaceApiError && [401, 403, 404].includes(error.status);
    const schedule = () => {
      if (closed || truncated) return;
      reconnect = setTimeout(
        async () => {
          try {
            await reconcile();
            publish("History recovered · reconnecting");
            connect();
          } catch (error) {
            if (!closed) {
              publish(
                "Recovery failed",
                error instanceof Error ? error.message : "History unavailable",
              );
              if (!denied(error)) schedule();
            }
          }
        },
        Math.min(1000 * 2 ** attempts++, 10000),
      );
    };
    const connect = () => {
      if (closed || truncated) return;
      const url = new URL(process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000");
      if (
        ["localhost", "127.0.0.1"].includes(url.hostname) &&
        ["localhost", "127.0.0.1"].includes(location.hostname)
      )
        url.hostname = location.hostname;
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      url.pathname = `/evaluations/${evaluationId}/live`;
      url.search = `after=${historyCursor}`;
      socket = new WebSocket(url);
      socket.onopen = () => {
        attempts = 0;
        lastFrame = Date.now();
        publish("Connected · authenticated live stream");
      };
      socket.onmessage = (message) => {
        try {
          const frame: Frame = JSON.parse(message.data);
          if (
            !Number.isSafeInteger(frame.sequence) ||
            frame.sequence < 0 ||
            !["event", "cursor"].includes(frame.kind)
          )
            throw Error();
          lastFrame = Date.now();
          if (frame.kind === "event") {
            if (
              !frame.event ||
              frame.event.evaluation_id !== evaluationId ||
              frame.event.origin !== "RUNTIME" ||
              frame.event.sequence !== frame.sequence
            )
              throw Error();
            gapPending ||= frame.sequence > cursor + 1;
            merge([frame.event as XEvent]);
            if (frame.event.event_type === "POLICY_ALLOWED")
              realtime = Math.max(realtime, frame.sequence);
          }
          cursor = Math.max(cursor, frame.sequence);
          watermark = Math.max(watermark, cursor);
          if (!flush)
            flush = setTimeout(() => {
              flush = undefined;
              if (gapPending) {
                gapPending = false;
                publish(
                  "Sequence jump · reconciling authorized history (hidden records may explain gaps)",
                );
                void reconcile().then(
                  () => publish("Connected · authenticated live stream"),
                  () => {
                    publish("History reconciliation delayed");
                    socket?.close();
                  },
                );
              } else publish("Connected · authenticated live stream");
            }, 100);
          if (truncated) {
            socket?.close();
            publish("History limit reached · visualization incomplete");
          }
        } catch {
          publish(
            "Invalid stream frame",
            "Live frame validation failed; reload authorized history",
          );
          socket?.close(1008);
        }
      };
      socket.onclose = (event) => {
        clearTimeout(flush);
        flush = undefined;
        if (closed || truncated) return;
        if (event.code === 1008) {
          publish(
            "Subscription rejected",
            "Session or membership changed; reload or sign in again",
          );
          return;
        }
        publish("Disconnected · recovering authorized history");
        schedule();
      };
    };
    const watch = setInterval(() => {
      if (!live || socket?.readyState !== WebSocket.OPEN || closed || truncated) return;
      if (Date.now() - lastFrame > 10000) {
        publish("Live feed delayed · recovering persisted history");
        socket?.close();
        return;
      }
      // Reconcile raw coverage even if an entire final frame was dropped and no
      // later sequence arrives. This is independent of visible sequence gaps.
      void reconcile().then(
        () => {
          if (truncated) {
            publish("History limit reached · visualization incomplete");
            socket?.close();
          }
        },
        () => {
          publish("History reconciliation delayed");
          socket?.close();
        },
      );
    }, 5000);
    void reconcile().then(
      () => {
        publish(
          truncated
            ? "History limit reached · visualization incomplete"
            : live
              ? "History loaded · connecting"
              : "Recorded history · no execution calls",
        );
        if (live) connect();
      },
      (error) => {
        if (!closed) {
          publish(
            "History unavailable",
            error instanceof Error ? error.message : "History unavailable",
          );
          if (live && !denied(error)) schedule();
        }
      },
    );
    return () => {
      closed = true;
      controller.abort();
      clearInterval(watch);
      clearTimeout(reconnect);
      clearTimeout(flush);
      socket?.close();
    };
  }, [evaluationId, live, revision]);
  return {
    ...(store.id === evaluationId ? store : empty),
    reload: () => setRevision((r) => r + 1),
  };
}
