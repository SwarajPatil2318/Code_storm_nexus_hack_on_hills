/** Evidence-only state reduction. Playback changes a cursor, never execution evidence. */
import type { SecurityEvent } from "./auth-types";
export type XEvent = SecurityEvent & { sequence: number };
export const actors = [
  "RED_RUNNER",
  "REFERENCE_MONITOR",
  "BLUE_INPUT_GUARD",
  "MODEL_WORKER",
  "BLUE_OUTPUT_GUARD",
  "EVIDENCE_COLLECTOR",
] as const;
export type Actor = (typeof actors)[number];
export type NodeState =
  | "Not provisioned"
  | "Provisioning"
  | "Ready"
  | "Active"
  | "Waiting"
  | "Completed"
  | "Blocked"
  | "Failed"
  | "Destroyed";
export type Category =
  "Case" | "Policy" | "Guard" | "Inference" | "Infrastructure" | "Lifecycle" | "Other";
export type Route = {
  id: string;
  source: Actor;
  target: Actor;
  message: string;
  decision: "ALLOW" | "DENY";
  sequence: number;
  correlation: string;
};
export type Trace = {
  correlation: string;
  caseIndex: number | null;
  nodes: Partial<Record<Actor, NodeState>>;
  routes: Record<string, Route>;
  skipped: boolean;
  inferenceStarted: boolean;
  inferenceCompleted: boolean;
  released: boolean;
  scored: boolean;
  outcome: string | null;
  inputAction: string | null;
  outputAction: string | null;
  inferenceMs: number | null;
  promptTokens: number | null;
  completionTokens: number | null;
};
export type Engine = {
  sequence: number;
  evaluationState: string;
  physical:
    | "Not recorded"
    | "Provisioning"
    | "Ready"
    | "Removed"
    | "Cleanup failed"
    | "Not applicable · in-process";
  executionMode: string | null;
  stopped: boolean;
  base: Record<Actor, NodeState>;
  traces: Record<string, Trace>;
  routes: Record<string, Route>;
  latest: XEvent | null;
  observed: number;
  unknown: number;
};
export function initialEngine(): Engine {
  return {
    sequence: 0,
    evaluationState: "Not recorded",
    physical: "Not recorded",
    executionMode: null,
    stopped: false,
    base: Object.fromEntries(
      actors.map((a) => [a, a === "REFERENCE_MONITOR" ? "Waiting" : "Not provisioned"]),
    ) as Record<Actor, NodeState>,
    traces: {},
    routes: {},
    latest: null,
    observed: 0,
    unknown: 0,
  };
}
export function category(event: Pick<SecurityEvent, "event_type">): Category {
  const t = event.event_type;
  if (t.startsWith("ATTACK_CASE") || t === "EVALUATION_PROGRESS" || t === "RESULT_RELEASED")
    return "Case";
  if (t.startsWith("POLICY_")) return "Policy";
  if (t.includes("GUARD_EVALUATED") || t === "DEFENCE_INVOKED") return "Guard";
  if (t.startsWith("MODEL_")) return "Inference";
  if (
    t.startsWith("RUNTIME_") ||
    t.startsWith("SECURITY_PROBE") ||
    t.startsWith("CPU_") ||
    t === "EXECUTION_PROFILE_SELECTED"
  )
    return "Infrastructure";
  if (
    t.startsWith("EVALUATION_") ||
    t.startsWith("WORKLOAD_") ||
    t === "ARTIFACT_COMMITTED" ||
    t === "BLUE_APPROVED"
  )
    return "Lifecycle";
  return "Other";
}
export function orderedEvents(events: readonly SecurityEvent[], evaluationId: string): XEvent[] {
  const ids = new Set<string>();
  const sequences = new Set<number>();
  return events
    .filter(
      (e): e is XEvent =>
        e.origin === "RUNTIME" &&
        e.evaluation_id === evaluationId &&
        Number.isSafeInteger(e.sequence) &&
        (e.sequence ?? 0) > 0 &&
        Number.isFinite(Date.parse(e.timestamp)),
    )
    .sort((a, b) => a.sequence - b.sequence || a.event_id.localeCompare(b.event_id))
    .filter((e) => {
      if (ids.has(e.event_id) || sequences.has(e.sequence)) return false;
      ids.add(e.event_id);
      sequences.add(e.sequence);
      return true;
    });
}
function actor(value: string): value is Actor {
  return (actors as readonly string[]).includes(value);
}
function traceFor(e: XEvent, old?: Trace): Trace {
  return old
    ? { ...old, nodes: { ...old.nodes }, routes: { ...old.routes } }
    : {
        correlation: e.correlation_id,
        caseIndex: e.permitted_metadata.case_index ?? null,
        nodes: {},
        routes: {},
        skipped: false,
        inferenceStarted: false,
        inferenceCompleted: false,
        released: false,
        scored: false,
        outcome: null,
        inputAction: null,
        outputAction: null,
        inferenceMs: null,
        promptTokens: null,
        completionTokens: null,
      };
}
const transitionEvents = new Set<string>([
  "RECOVERY_STARTED",
  "EVALUATION_RECONCILED",
  "RUNTIME_FOUND",
  "RUNTIME_MISSING",
  "RECOVERY_FAILED",
  "CLEANUP_ATTEMPTED",
  "CLEANUP_VERIFIED",
  "CREDENTIALS_REVOKED",
  "EVALUATION_INTERRUPTED",
  "ATTACK_CASE_STARTED",
  "POLICY_ALLOWED",
  "POLICY_DENIED",
  "DEFENCE_INVOKED",
  "INPUT_GUARD_EVALUATED",
  "OUTPUT_GUARD_EVALUATED",
  "MODEL_LOADING",
  "MODEL_READY",
  "MODEL_INFERENCE_STARTED",
  "MODEL_INFERENCE_COMPLETED",
  "MODEL_REQUESTED",
  "MODEL_RESPONDED",
  "MODEL_WORKER_STOPPED",
  "ATTACK_CASE_SCORED",
  "ATTACK_CASE_FAILED",
  "RESULT_RELEASED",
  "RUNTIME_UPDATED",
  "RUNTIME_TEARDOWN",
  "SECURITY_PROBE_RESULT",
  "SECURITY_PROBE_PASSED",
  "SECURITY_PROBE_FAILED",
  "EVALUATION_CREATED",
  "ARTIFACT_COMMITTED",
  "BLUE_APPROVED",
  "EVALUATION_SEALED",
  "WORKLOAD_STARTING",
  "WORKLOAD_READY",
  "WORKLOAD_DESTROYED",
  "EVALUATION_PROGRESS",
  "EVALUATION_FINALIZING",
  "EVALUATION_COMPLETED",
  "EVALUATION_FAILED",
  "EVALUATION_CANCELLED",
]);
export function reduceEvidence(previous: Engine, event: XEvent): Engine {
  const s: Engine = {
    ...previous,
    sequence: event.sequence,
    latest: event,
    observed: previous.observed + 1,
    base: { ...previous.base },
    traces: { ...previous.traces },
    routes: { ...previous.routes },
  };
  s.base.EVIDENCE_COLLECTOR = "Completed"; // This event is a persisted authorized projection, not a signed receipt.
  if (!transitionEvents.has(event.event_type)) {
    s.unknown++;
    return s;
  }
  const t = event.event_type,
    m = event.permitted_metadata;
  if (m.status) s.evaluationState = m.status;
  if (m.execution_mode) s.executionMode = m.execution_mode;
  if (s.executionMode === "local_mock") s.physical = "Not applicable · in-process";
  const states: Record<string, string> = {
    EVALUATION_CREATED: "CREATED",
    ARTIFACT_COMMITTED: "COMMITTED",
    EVALUATION_SEALED: "SEALED",
    WORKLOAD_STARTING: "PROVISIONING",
    WORKLOAD_READY: "RUNNING",
    EVALUATION_FINALIZING: "FINALIZING",
    EVALUATION_COMPLETED: "COMPLETED",
    EVALUATION_FAILED: "FAILED",
    EVALUATION_INTERRUPTED: "FAILED",
    EVALUATION_CANCELLED: "CANCELLED",
    WORKLOAD_DESTROYED: "DESTROYED",
  };
  if (states[t]) s.evaluationState = states[t];
  if (m.runtime_state === "PROVISIONING") {
    s.physical = "Provisioning";
    s.stopped = false;
    for (const a of [
      "RED_RUNNER",
      "BLUE_INPUT_GUARD",
      "BLUE_OUTPUT_GUARD",
      "MODEL_WORKER",
    ] as Actor[])
      s.base[a] = "Provisioning";
  }
  if (m.runtime_state === "READY" || m.runtime_state === "PROBING") {
    s.physical = "Ready";
    for (const a of [
      "RED_RUNNER",
      "BLUE_INPUT_GUARD",
      "BLUE_OUTPUT_GUARD",
      "MODEL_WORKER",
    ] as Actor[])
      s.base[a] = "Ready";
  }
  if (m.cleanup_status === "FAILED") s.physical = "Cleanup failed";
  if (m.cleanup_status === "VERIFIED") {
    s.physical = "Removed";
    s.stopped = true;
  }
  if (t === "MODEL_WORKER_STOPPED") {
    s.stopped = true;
    if (s.executionMode === "isolated_docker") s.physical = "Removed";
  }
  if (t === "MODEL_LOADING") {
    s.base.MODEL_WORKER = "Provisioning";
    s.stopped = false;
  }
  if (t === "MODEL_READY") s.base.MODEL_WORKER = "Ready";
  if (["EVALUATION_COMPLETED", "EVALUATION_FAILED", "EVALUATION_CANCELLED"].includes(t)) {
    s.base.REFERENCE_MONITOR =
      t === "EVALUATION_COMPLETED" ? "Completed" : t === "EVALUATION_FAILED" ? "Failed" : "Waiting";
    for (const [key, old] of Object.entries(s.traces))
      s.traces[key] = {
        ...old,
        nodes: Object.fromEntries(
          Object.entries(old.nodes).map(([a, state]) => [
            a,
            state === "Active" ? (t === "EVALUATION_FAILED" ? "Failed" : "Completed") : state,
          ]),
        ),
      };
  }
  const scoped = [
    "ATTACK_CASE_STARTED",
    "POLICY_ALLOWED",
    "POLICY_DENIED",
    "INPUT_GUARD_EVALUATED",
    "OUTPUT_GUARD_EVALUATED",
    "MODEL_INFERENCE_STARTED",
    "MODEL_INFERENCE_COMPLETED",
    "MODEL_REQUESTED",
    "MODEL_RESPONDED",
    "DEFENCE_INVOKED",
    "ATTACK_CASE_SCORED",
    "ATTACK_CASE_FAILED",
    "RESULT_RELEASED",
  ].includes(t);
  if (scoped) {
    const trace = traceFor(event, s.traces[event.correlation_id]);
    trace.caseIndex = m.case_index ?? trace.caseIndex;
    if (t === "ATTACK_CASE_STARTED") trace.nodes.RED_RUNNER = "Active";
    if (t === "POLICY_ALLOWED" || t === "POLICY_DENIED") {
      trace.nodes.REFERENCE_MONITOR = t === "POLICY_DENIED" ? "Blocked" : "Active";
      if (actor(event.source) && actor(event.destination)) {
        const id = `${event.source}:${event.destination}:${m.message_type ?? "UNKNOWN"}`;
        const route: Route = {
          id,
          source: event.source,
          target: event.destination,
          message: m.message_type ?? "UNKNOWN",
          decision: t === "POLICY_ALLOWED" ? "ALLOW" : "DENY",
          sequence: event.sequence,
          correlation: event.correlation_id,
        };
        trace.routes[id] = route;
        s.routes[id] = route;
      }
      // Authorization is not proof of destination execution.
    }
    if (t === "INPUT_GUARD_EVALUATED") {
      trace.inputAction = m.defence_action ?? null;
      trace.nodes.BLUE_INPUT_GUARD = m.defence_action === "BLOCK" ? "Blocked" : "Completed";
      if (m.defence_action === "BLOCK") {
        trace.skipped = true;
        trace.nodes.MODEL_WORKER = "Blocked";
      }
    }
    if (t === "OUTPUT_GUARD_EVALUATED") {
      trace.outputAction = m.defence_action ?? null;
      trace.nodes.BLUE_OUTPUT_GUARD = m.defence_action === "BLOCK" ? "Blocked" : "Completed";
    }
    if (t === "DEFENCE_INVOKED")
      trace.nodes[m.guard_stage === "output" ? "BLUE_OUTPUT_GUARD" : "BLUE_INPUT_GUARD"] = "Active";
    if (t === "MODEL_INFERENCE_STARTED" || t === "MODEL_REQUESTED") {
      trace.nodes.MODEL_WORKER = "Active";
      trace.inferenceStarted = true;
    }
    if (t === "MODEL_INFERENCE_COMPLETED" || t === "MODEL_RESPONDED") {
      trace.nodes.MODEL_WORKER = "Completed";
      trace.inferenceCompleted = true;
      trace.inferenceMs = m.duration_ms ?? null;
      trace.promptTokens = m.prompt_tokens ?? null;
      trace.completionTokens = m.completion_tokens ?? null;
    }
    if (t === "RESULT_RELEASED") {
      trace.released = true;
      trace.nodes.RED_RUNNER = "Completed";
    }
    if (t === "ATTACK_CASE_SCORED" || t === "ATTACK_CASE_FAILED") {
      trace.scored = true;
      trace.outcome = m.attack_outcome ?? null;
      for (const a of actors)
        if (trace.nodes[a] === "Active")
          trace.nodes[a] = t === "ATTACK_CASE_FAILED" ? "Failed" : "Completed";
      if (t === "ATTACK_CASE_FAILED" && !trace.skipped && trace.inferenceStarted)
        trace.nodes.MODEL_WORKER = "Failed";
    }
    s.traces[event.correlation_id] = trace;
  }
  return s;
}
export type ReplayIndex = { events: XEvent[]; checkpoints: Map<number, Engine> };
export function prepareReplay(events: XEvent[]): ReplayIndex {
  const checkpoints = new Map<number, Engine>([[-1, initialEngine()]]);
  let state = initialEngine();
  for (let i = 0; i < events.length; i++) {
    state = reduceEvidence(state, events[i]);
    if ((i + 1) % 128 === 0) checkpoints.set(i, state);
  }
  return { events, checkpoints };
}
export function stateAt(index: ReplayIndex, position: number): Engine {
  const end = Math.max(-1, Math.min(index.events.length - 1, Math.trunc(position)));
  const checkpoint = Math.floor((end + 1) / 128) * 128 - 1;
  let state = index.checkpoints.get(checkpoint) ?? initialEngine();
  for (let i = checkpoint + 1; i <= end; i++) state = reduceEvidence(state, index.events[i]);
  return state;
}
export function nodeViews(state: Engine, correlation: string | null) {
  const traces = correlation
    ? [state.traces[correlation]].filter(Boolean)
    : Object.values(state.traces);
  const priority: NodeState[] = [
    "Active",
    "Failed",
    "Blocked",
    "Completed",
    "Ready",
    "Waiting",
    "Provisioning",
    "Not provisioned",
  ];
  return Object.fromEntries(
    actors.map((a) => {
      const observed = traces.flatMap((t) => (t.nodes[a] ? [t.nodes[a]!] : []));
      let status = priority.find((s) => observed.includes(s)) ?? state.base[a];
      if (
        state.physical === "Provisioning" &&
        !["REFERENCE_MONITOR", "EVIDENCE_COLLECTOR"].includes(a)
      )
        status = "Provisioning";
      if (
        (state.physical === "Removed" || state.stopped) &&
        !["REFERENCE_MONITOR", "EVIDENCE_COLLECTOR"].includes(a)
      )
        status = "Destroyed";
      return [a, { status, active: traces.filter((t) => t.nodes[a] === "Active").length }];
    }),
  ) as Record<Actor, { status: NodeState; active: number }>;
}
export function routesFor(state: Engine, correlation: string | null): Route[] {
  return Object.values(correlation ? (state.traces[correlation]?.routes ?? {}) : state.routes);
}
export function replayDelay(previous: XEvent | undefined, next: XEvent, speed: number) {
  const actual = previous
    ? Math.max(0, Date.parse(next.timestamp) - Date.parse(previous.timestamp))
    : 0;
  return {
    delay: Math.max(60, Math.min(actual, 1500) / speed),
    compressed: actual > 1500,
    recordedGap: actual,
  };
}
export function stepPosition(position: number, delta: number, count: number) {
  return Math.max(-1, Math.min(count - 1, position + delta));
}
