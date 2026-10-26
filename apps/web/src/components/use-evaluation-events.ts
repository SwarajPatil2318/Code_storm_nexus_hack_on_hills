"use client";
import { useEffect, useState } from "react";
import type { components } from "@/lib/api.generated";
import type { SecurityEvent } from "@/lib/auth-types";
type Frame = components["schemas"]["LiveFrame"];

export function useEvaluationEvents(evaluationId: string, refresh: () => void) {
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [connection, setConnection] = useState("Connecting");
  useEffect(() => {
    let closed = false,
      socket: WebSocket | undefined,
      timer: ReturnType<typeof setTimeout>;
    let cursor = 0,
      attempts = 0;
    const connect = () => {
      if (closed) return;
      const url = new URL(process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000");
      if (
        ["localhost", "127.0.0.1"].includes(url.hostname) &&
        ["localhost", "127.0.0.1"].includes(location.hostname)
      )
        url.hostname = location.hostname;
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      url.pathname = `/evaluations/${evaluationId}/live`;
      url.search = `after=${cursor}`;
      socket = new WebSocket(url);
      socket.onopen = () => {
        attempts = 0;
        setConnection("Connected · persisted replay + live");
      };
      socket.onmessage = (message) => {
        try {
          const frame: Frame = JSON.parse(message.data);
          if (!Number.isSafeInteger(frame.sequence) || frame.sequence < cursor) throw Error();
          if (
            frame.kind === "event" &&
            frame.event?.origin === "RUNTIME" &&
            frame.event.evaluation_id === evaluationId
          ) {
            const event = frame.event;
            setEvents((previous) =>
              previous.some((e) => e.event_id === event.event_id)
                ? previous
                : [...previous, event].slice(-500),
            );
            if (
              [
                "EVALUATION_COMPLETED",
                "EVALUATION_FAILED",
                "EVALUATION_CANCELLED",
                "EVALUATION_SEALED",
                "BLUE_APPROVED",
                "ARTIFACT_COMMITTED",
                "ATTACK_CASE_SCORED",
                "ATTACK_CASE_FAILED",
                "EVALUATION_PROGRESS",
                "MODEL_READY",
                "MODEL_WORKER_STOPPED",
              ].includes(event.event_type)
            ) {
              refresh();
            }
          }
          cursor = frame.sequence;
        } catch {
          setConnection("Invalid event frame");
          socket?.close();
        }
      };
      socket.onclose = (event) => {
        if (closed) return;
        if (event.code === 1008) {
          setConnection("Subscription rejected · verify identity and membership");
          return;
        }
        setConnection("Disconnected · reconnecting");
        timer = setTimeout(connect, Math.min(1000 * 2 ** attempts++, 10000));
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [evaluationId, refresh]);
  return { events, connection };
}
