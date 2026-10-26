"use client";
import Link from "next/link";
import type { components } from "@/lib/api.generated";
import { category, nodeViews, type Actor, type Engine, type XEvent } from "@/lib/xray-state";
import { descriptions } from "./canvas";
import { eventTime, semanticActor } from "./timeline";
type Case = components["schemas"]["CaseOutcome"];
type Runtime = components["schemas"]["RuntimeResponse"];
export type Inspection =
  { kind: "event"; sequence: number } | { kind: "node"; actor: Actor } | { kind: "case" };
const metadataKeys = [
  "provider",
  "case_index",
  "defence_action",
  "model_execution",
  "attack_outcome",
  "prompt_tokens",
  "completion_tokens",
  "completed_cases",
  "total_cases",
  "decision",
  "reason_code",
  "duration_ms",
  "verification_status",
  "status",
  "policy_digest",
  "policy_version",
  "message_type",
  "execution_mode",
  "guard_stage",
  "runtime_state",
  "workload_count",
  "cleanup_status",
  "probe_id",
  "probe_status",
  "cpu_percent",
  "memory_bytes",
  "artifact_id",
  "object_kind",
];
function Field({ name, value }: { name: string; value: unknown }) {
  return (
    <div>
      <dt>{name}</dt>
      <dd>{value == null ? "Not recorded" : String(value)}</dd>
    </div>
  );
}
export function CaseInspection({
  record,
  state,
  correlation,
}: {
  record: Case | undefined;
  state: Engine;
  correlation: string | null;
}) {
  const trace = correlation ? state.traces[correlation] : null;
  return (
    <div className="xray-case-inspection" data-testid="xray-case-inspection">
      <span className="xray-eyebrow">AUTHORIZED CASE PROJECTION</span>
      <h3>
        {record?.title ||
          (record ? `Case ${record.case_index + 1} · restricted details` : "Select an attack case")}
      </h3>
      {record && (
        <>
          <dl className="xray-detail-grid">
            <Field name="Case" value={record.case_index + 1} />
            <Field
              name="Category"
              value={record.attack_category?.replaceAll("_", " ") ?? "Restricted"}
            />
            <Field name="Objective" value={record.objective ?? "Restricted"} />
            <Field name="Input guard" value={trace?.inputAction} />
            <Field
              name="Model invocation"
              value={
                trace?.skipped
                  ? "SKIPPED · input blocked"
                  : trace?.inferenceCompleted
                    ? "EXECUTED · completion recorded"
                    : trace?.inferenceStarted
                      ? "STARTED · completion not recorded"
                      : "No invocation recorded at playhead"
              }
            />
            <Field name="Output guard" value={trace?.outputAction} />
            <Field name="Outcome at playhead" value={trace?.outcome} />
            <Field name="Recorded inference (ms)" value={trace?.inferenceMs} />
            <Field
              name="Prompt / generated tokens"
              value={
                trace?.promptTokens != null
                  ? `${trace.promptTokens} / ${trace.completionTokens ?? "unavailable"}`
                  : null
              }
            />
            <Field
              name="Case duration (final ms)"
              value={trace?.scored ? record.duration_ms : null}
            />
          </dl>
          <details>
            <summary>Permitted attack input</summary>
            <pre>{record.attack_input ?? "Restricted by backend projection"}</pre>
          </details>
          <details open={!!trace?.released}>
            <summary>Authorized observable output</summary>
            <pre data-testid="xray-authorized-output">
              {record.released_output === null
                ? "Restricted or no output released"
                : trace?.released
                  ? record.released_output
                  : "No authorized release observed at playhead"}
            </pre>
          </details>
          <details>
            <summary>Criterion and recorded boundary</summary>
            <p>{record.expected_boundary ?? "Restricted"}</p>
            <pre>
              {record.criterion
                ? trace?.scored
                  ? JSON.stringify(record.criterion, null, 2)
                  : "Criterion evaluation not reached at playhead"
                : "Restricted by backend projection"}
            </pre>
            {trace?.scored && <p>{record.scoring_explanation}</p>}
          </details>
          <p className="xray-caution">
            Input, criterion and released text come from the backend role projection. Internal Blue
            rules and raw pre-guard model output are unavailable here.
          </p>
        </>
      )}
      {!record && (
        <p className="xray-caution">
          Select a recorded case to inspect its permitted objective, guard actions and observable
          result.
        </p>
      )}
    </div>
  );
}
export function XrayInspector({
  inspection,
  evaluationId,
  state,
  events,
  correlation,
  record,
  runtime,
  onEvent,
  onCase,
}: {
  inspection: Inspection;
  evaluationId: string;
  state: Engine;
  events: XEvent[];
  correlation: string | null;
  record: Case | undefined;
  runtime: Runtime | null;
  onEvent: (sequence: number) => void;
  onCase: () => void;
}) {
  const event =
    inspection.kind === "event" ? events.find((e) => e.sequence === inspection.sequence) : null;
  const actor =
    inspection.kind === "node"
      ? inspection.actor
      : event
        ? (semanticActor(event) as Actor)
        : "REFERENCE_MONITOR";
  const workloadRole =
    actor === "RED_RUNNER"
      ? "red"
      : actor === "MODEL_WORKER"
        ? "model"
        : actor.startsWith("BLUE_")
          ? "blue"
          : null;
  const workload = runtime?.snapshot?.workloads.find((w) => w.role === workloadRole);
  const related = events
    .filter(
      (e) =>
        e.sequence <= state.sequence &&
        (inspection.kind === "event"
          ? e.correlation_id === event?.correlation_id
          : inspection.kind === "case"
            ? e.correlation_id === correlation
            : e.source === actor || e.destination === actor || semanticActor(e) === actor),
    )
    .slice(-8);
  return (
    <aside className="xray-inspector" aria-label="X-Ray forensic inspector">
      <div className="xray-inspector-heading">
        <span className="xray-eyebrow">FORENSIC INSPECTOR</span>
        <span className="xray-evidence-tag">PERMITTED EVIDENCE</span>
      </div>
      <div className="xray-inspector-tabs">
        <button aria-pressed={inspection.kind === "case"} onClick={onCase}>
          Case
        </button>
        <span>
          {inspection.kind === "event"
            ? "Selected event"
            : inspection.kind === "node"
              ? "Selected workload / stage"
              : "Selected attack trace"}
        </span>
      </div>
      {inspection.kind === "case" ? (
        <CaseInspection record={record} state={state} correlation={correlation} />
      ) : event ? (
        <>
          <span className={`xray-category-pill xray-category-${category(event).toLowerCase()}`}>
            {category(event)}
          </span>
          <h3>{event.event_type.replaceAll("_", " ")}</h3>
          <Link href={`/proof-vault?evaluation=${evaluationId}&sequence=${event.sequence}`}>
            Inspect signed evidence
          </Link>
          <dl className="xray-detail-grid">
            <Field name="Sequence" value={event.sequence} />
            <Field name="Recorded timestamp" value={eventTime(event.timestamp)} />
            <Field name="Correlation" value={event.correlation_id} />
            <Field name="Source" value={event.source} />
            <Field name="Destination" value={event.destination} />
            <Field
              name="Execution stage"
              value={descriptions[semanticActor(event) as Actor]?.title ?? "Not recorded"}
            />
            <Field
              name="Policy decision"
              value={
                event.permitted_metadata.decision ??
                (event.event_type === "POLICY_DENIED"
                  ? "DENY"
                  : event.event_type === "POLICY_ALLOWED"
                    ? "ALLOW"
                    : null)
              }
            />
            <Field name="Visibility" value={event.visibility} />
            <Field name="Origin" value={event.origin} />
          </dl>
          <h4>Recorded permitted metadata</h4>
          <dl className="xray-detail-grid">
            {Object.entries(event.permitted_metadata)
              .filter(([key, value]) => value != null && metadataKeys.includes(key))
              .map(([key, value]) => (
                <Field key={key} name={key.replaceAll("_", " ")} value={value} />
              ))}
          </dl>
          {event.permitted_metadata.probe_id && (
            <>
              <h4>Latest retained probe evidence</h4>
              <p className="xray-caution">
                The snapshot below may postdate this event. Match its probe identity and timestamp.
              </p>
              {runtime?.snapshot?.probes
                .filter((p) => p.probe_id === event.permitted_metadata.probe_id)
                .map((p, i) => (
                  <div className="xray-probe-evidence" key={i}>
                    <strong>
                      {p.status} · {p.probe_id}
                    </strong>
                    <p>
                      {p.source} → {p.target}
                    </p>
                    <time>{eventTime(p.timestamp)}</time>
                    <pre>{p.observed}</pre>
                  </div>
                ))}
            </>
          )}
        </>
      ) : (
        <>
          <span className="xray-eyebrow">{descriptions[actor]?.domain.toUpperCase()} DOMAIN</span>
          <h3>{descriptions[actor]?.title}</h3>
          <span className="xray-node-state-large">
            {nodeViews(state, correlation)[actor]?.status}
          </span>
          <p>{descriptions[actor]?.subtitle}</p>
          <dl className="xray-detail-grid">
            <Field
              name="State reconstructed through"
              value={state.sequence ? `Sequence ${state.sequence}` : "Before first record"}
            />
            <Field
              name="Physical evidence at playhead"
              value={workloadRole ? state.physical : "Logical service, not a tenant container"}
            />
            <Field
              name="Active observed traces"
              value={nodeViews(state, correlation)[actor]?.active}
            />
          </dl>
          {workload && (
            <>
              <h4>Latest retained runtime snapshot</h4>
              <p className="xray-caution">
                Historical inspection metadata; not an as-of-playhead measurement.
                {workloadRole === "blue" && " Blue input/output share this same container."}
              </p>
              <dl className="xray-detail-grid">
                <Field name="Container" value={workload.container_id} />
                <Field name="Snapshot workload state" value={workload.health} />
                <Field name="Network" value={workload.network_id} />
                <Field name="Image digest" value={workload.image_digest} />
                <Field name="Memory cap (bytes)" value={workload.memory_limit} />
                <Field
                  name="CPU / PID cap"
                  value={`${workload.cpu_limit} / ${workload.pids_limit}`}
                />
                <Field name="Latest cleanup" value={runtime?.snapshot?.cleanup} />
              </dl>
              <details>
                <summary>Inspected runtime controls</summary>
                <dl className="xray-detail-grid">
                  {Object.entries(workload.controls).map(([key, value]) => (
                    <Field
                      key={key}
                      name={key}
                      value={value ? "Observed true" : "Observed false"}
                    />
                  ))}
                </dl>
              </details>
            </>
          )}
          {!workload && workloadRole && (
            <p className="xray-caution">
              No physical workload snapshot recorded for this view. In-process mock adapters do not
              create containers.
            </p>
          )}
          {actor === "EVIDENCE_COLLECTOR" && (
            <p className="xray-caution">
              This node represents persisted, role-filtered records. Check Proof Vault for an actual
              signed receipt; replay alone does not verify evidence integrity.
            </p>
          )}
          {actor === "REFERENCE_MONITOR" && (
            <p className="xray-caution">
              Graph edges represent recorded application authorizations. Physical network
              enforcement is supported only by actual runtime probe evidence.
            </p>
          )}
        </>
      )}
      <div className="xray-related">
        <h4>Related recorded events</h4>
        {related.map((e) => (
          <button key={e.event_id} onClick={() => onEvent(e.sequence)}>
            <code>#{e.sequence}</code>
            <span>{e.event_type}</span>
          </button>
        ))}
        {!related.length && <p>Not recorded at this playhead.</p>}
      </div>
    </aside>
  );
}
