import type { SecurityEvent } from "./auth-types";
export type DomainId = "red" | "monitor" | "blue" | "model" | "evidence";
export type ScenarioId = "authorized" | "forbidden" | "sealed";
export type ScenarioStep = {
  title: string;
  description: string;
  route: string;
  event: SecurityEvent;
};
export type Scenario = {
  id: ScenarioId;
  letter: string;
  title: string;
  description: string;
  outcome: string;
  steps: ScenarioStep[];
};
const id = (value: number) => `00000000-0000-4000-8000-${String(value).padStart(12, "0")}`;
function event(
  index: number,
  event_type: SecurityEvent["event_type"],
  source: SecurityEvent["source"],
  destination: SecurityEvent["destination"],
  decision: "ALLOW" | "DENY",
  reason_code: string,
): SecurityEvent {
  return {
    schema_version: "1.0",
    sequence: null,
    event_id: id(index),
    evaluation_id: id(100),
    event_type,
    timestamp: `2026-10-19T00:00:${String(index).padStart(2, "0")}Z`,
    source,
    destination,
    visibility: "EVALUATION_METADATA",
    permitted_metadata: {
      provider: null,
      case_index: null,
      defence_action: null,
      model_execution: null,
      attack_outcome: null,
      prompt_tokens: null,
      completion_tokens: null,
      completed_cases: null,
      total_cases: null,
      decision,
      reason_code,
      runtime_state: null,
      workload_count: null,
      cleanup_status: null,
      probe_id: null,
      probe_status: null,
      cpu_percent: null,
      memory_bytes: null,
      artifact_id: null,
      duration_ms: null,
      execution_mode: null,
      guard_stage: null,
      message_type: null,
      object_kind: null,
      policy_digest: null,
      policy_version: null,
      status: null,
      verification_status: null,
    },
    correlation_id: id(200),
    origin: "SIMULATED",
  };
}
export const scenarios: Record<ScenarioId, Scenario> = {
  authorized: {
    id: "authorized",
    letter: "A",
    title: "Authorized Evaluation Flow",
    description: "Follow an approved message through the intended evaluation pathway.",
    outcome: "Approved pathway illustrated. No workload or inference was executed.",
    steps: [
      {
        title: "Scoped request",
        description: "Red submits a permitted request to the planned Reference Monitor.",
        route: "red-monitor",
        event: event(
          1,
          "POLICY_ALLOWED",
          "RED_RUNNER",
          "REFERENCE_MONITOR",
          "ALLOW",
          "SCOPED_REQUEST",
        ),
      },
      {
        title: "Defence invocation",
        description: "The monitor forwards an authorized envelope to the defensive boundary.",
        route: "monitor-blue",
        event: event(
          2,
          "DEFENCE_INVOKED",
          "REFERENCE_MONITOR",
          "BLUE_DEFENCE",
          "ALLOW",
          "APPROVED_DEFENCE_PATH",
        ),
      },
      {
        title: "Controlled model request",
        description:
          "Defensive logic invokes the Client LLM through the intended scoped interface.",
        route: "blue-model",
        event: event(
          3,
          "MODEL_REQUESTED",
          "BLUE_DEFENCE",
          "CLIENT_LLM",
          "ALLOW",
          "SCOPED_MODEL_REQUEST",
        ),
      },
      {
        title: "Model response",
        description: "A response returns to Blue without exposing model context to Red.",
        route: "model-blue",
        event: event(
          4,
          "MODEL_RESPONDED",
          "CLIENT_LLM",
          "BLUE_DEFENCE",
          "ALLOW",
          "SCOPED_RESPONSE",
        ),
      },
      {
        title: "Permitted result",
        description: "Blue passes a releasable result envelope back to the monitor.",
        route: "blue-monitor",
        event: event(
          5,
          "RESULT_RELEASED",
          "BLUE_DEFENCE",
          "REFERENCE_MONITOR",
          "ALLOW",
          "RELEASE_POLICY",
        ),
      },
      {
        title: "Red result release",
        description: "Only the permitted result is returned to the Red domain.",
        route: "monitor-red",
        event: event(
          6,
          "RESULT_RELEASED",
          "REFERENCE_MONITOR",
          "RED_RUNNER",
          "ALLOW",
          "RESULT_RELEASE_POLICY",
        ),
      },
      {
        title: "Sanitized evidence",
        description: "Approved event metadata is sent to the Evidence Collector.",
        route: "monitor-evidence",
        event: event(
          7,
          "POLICY_ALLOWED",
          "REFERENCE_MONITOR",
          "EVIDENCE_COLLECTOR",
          "ALLOW",
          "AUDIT_METADATA_ONLY",
        ),
      },
    ],
  },
  forbidden: {
    id: "forbidden",
    letter: "B",
    title: "Forbidden Direct Access",
    description: "Inspect a proposed direct Red-to-Blue request outside the broker path.",
    outcome: "Direct access rejection illustrated. This is not a Docker network-denial test.",
    steps: [
      {
        title: "Direct path rejected",
        description:
          "The scenario rejects direct Red access to Blue. No real network probe was sent.",
        route: "red-blue-denied",
        event: event(
          8,
          "POLICY_DENIED",
          "RED_RUNNER",
          "BLUE_DEFENCE",
          "DENY",
          "DIRECT_PATH_DISALLOWED",
        ),
      },
      {
        title: "Record the decision",
        description:
          "A sanitized denial decision is represented for the future evidence interface.",
        route: "monitor-evidence",
        event: event(
          9,
          "POLICY_DENIED",
          "REFERENCE_MONITOR",
          "EVIDENCE_COLLECTOR",
          "DENY",
          "SANITIZED_DENIAL_RECORD",
        ),
      },
    ],
  },
  sealed: {
    id: "sealed",
    letter: "C",
    title: "Sealed Defence",
    description: "Illustrate defensive execution with restricted operator visibility.",
    outcome: "Sealed visibility illustrated. No artifact was sealed or executed by this scenario.",
    steps: [
      {
        title: "Defensive model call",
        description: "The sealed defensive boundary is illustrated invoking the Client LLM.",
        route: "blue-model",
        event: event(
          10,
          "MODEL_REQUESTED",
          "BLUE_DEFENCE",
          "CLIENT_LLM",
          "ALLOW",
          "SEALED_DEFENCE_PATH",
        ),
      },
      {
        title: "Private runtime response",
        description: "The simulated model response remains inside the defensive pathway.",
        route: "model-blue",
        event: event(
          11,
          "MODEL_RESPONDED",
          "CLIENT_LLM",
          "BLUE_DEFENCE",
          "ALLOW",
          "RUNTIME_CONTEXT_PRIVATE",
        ),
      },
      {
        title: "Operator visibility restricted",
        description:
          "A Blue operator cannot inspect sealed runtime state. Permitted artifact metadata remains available.",
        route: "operator-blue-denied",
        event: event(
          12,
          "POLICY_DENIED",
          "BLUE_OPERATOR",
          "BLUE_DEFENCE",
          "DENY",
          "SEALED_RUNTIME_HIDDEN",
        ),
      },
    ],
  },
};
