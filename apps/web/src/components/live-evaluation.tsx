"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { useReducedMotion } from "motion/react";
import type { components } from "@/lib/api.generated";
import type { SecurityEvent } from "@/lib/auth-types";
import { operatorRequest } from "@/lib/operator-api";
import { useAuth } from "./auth-provider";
import { RuntimeInspection } from "./runtime-observatory";
import { CampaignMonitor } from "./attack-campaign";
import { useResource } from "./use-resource";
import { useEvaluationEvents } from "./use-evaluation-events";
import { Badge, Button, Panel } from "./ui";
import "@xyflow/react/dist/style.css";

type Version = components["schemas"]["VersionResponse"];
type Evaluation = components["schemas"]["EvaluationResponse"];
type Manifest = components["schemas"]["ManifestResponse"];
type Release = components["schemas"]["ReleasedResult"];
const flows = [
  ["RED_RUNNER", "REFERENCE_MONITOR", "ATTACK_SUBMISSION"],
  ["REFERENCE_MONITOR", "BLUE_INPUT_GUARD", "DEFENCE_INPUT_REQUEST"],
  ["BLUE_INPUT_GUARD", "REFERENCE_MONITOR", "DEFENCE_INPUT_RESULT"],
  ["REFERENCE_MONITOR", "MODEL_WORKER", "MODEL_INFERENCE_REQUEST"],
  ["MODEL_WORKER", "REFERENCE_MONITOR", "MODEL_INFERENCE_RESULT"],
  ["REFERENCE_MONITOR", "BLUE_OUTPUT_GUARD", "DEFENCE_OUTPUT_REQUEST"],
  ["BLUE_OUTPUT_GUARD", "REFERENCE_MONITOR", "DEFENCE_OUTPUT_RESULT"],
  ["REFERENCE_MONITOR", "RED_RUNNER", "FINAL_RESULT"],
];
const labels: Record<string, string> = {
  RED_RUNNER: "Red Runner",
  REFERENCE_MONITOR: "Reference Monitor",
  BLUE_INPUT_GUARD: "Blue input guard",
  MODEL_WORKER: "Mock model",
  BLUE_OUTPUT_GUARD: "Blue output guard",
};
function LiveGraph({
  events,
  modelLabel = "Mock model",
}: {
  events: SecurityEvent[];
  modelLabel?: string;
}) {
  const reduced = useReducedMotion();
  const [active, setActive] = useState<string | null>(null);
  const latest = events.findLast((event) => event.event_type === "POLICY_ALLOWED");
  const modelActivity = events.findLast((event) =>
    [
      "MODEL_LOADING",
      "MODEL_READY",
      "MODEL_INFERENCE_STARTED",
      "MODEL_INFERENCE_COMPLETED",
      "MODEL_WORKER_STOPPED",
    ].includes(event.event_type),
  );
  useEffect(() => {
    if (!latest || latest.origin !== "RUNTIME" || latest.event_type !== "POLICY_ALLOWED") return;
    const id = `${latest.source}:${latest.destination}:${latest.permitted_metadata.message_type}`;
    const show = setTimeout(() => setActive(id), 0);
    const stop = setTimeout(() => setActive(null), 900);
    return () => {
      clearTimeout(show);
      clearTimeout(stop);
    };
  }, [latest]);
  const nodes: Node[] = useMemo(
    () =>
      Object.entries(labels).map(([id, label], i) => ({
        id,
        position: [
          { x: 0, y: 160 },
          { x: 260, y: 160 },
          { x: 530, y: 0 },
          { x: 530, y: 160 },
          { x: 530, y: 320 },
        ][i],
        data: {
          label:
            id === "MODEL_WORKER" ? (
              <div>
                {modelLabel}
                {modelActivity && (
                  <small className="live-model-state">
                    {modelActivity.event_type.replaceAll("_", " ")}
                  </small>
                )}
              </div>
            ) : (
              label
            ),
        },
        style: { background: "#ffffff", color: "#1d2c45", border: "1px solid #c8d2e1", width: 180 },
      })),
    [modelLabel, modelActivity],
  );
  const edges: Edge[] = flows.map(([source, target, type]) => {
    const id = `${source}:${target}:${type}`;
    const count = events.filter(
      (e) =>
        e.event_type === "POLICY_ALLOWED" &&
        e.source === source &&
        e.destination === target &&
        e.permitted_metadata.message_type === type,
    ).length;
    return {
      id,
      source,
      target,
      label: count ? `${type} · ${count}` : type,
      animated: !reduced && active === id,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { stroke: count ? "#176a52" : "#8b9bb4", strokeWidth: active === id ? 3 : 1 },
      labelStyle: { fill: "#596980", fontSize: 9 },
      labelBgStyle: { fill: "#ffffff" },
    };
  });
  return (
    <div
      className="live-graph"
      data-testid="live-graph"
      data-observed-decisions={events.filter((e) => e.event_type === "POLICY_ALLOWED").length}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        aria-label="Message route template with recorded authorization counts"
      >
        <Background color="#dce3ee" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

function EvaluationDetail({
  evaluation,
  refresh,
}: {
  evaluation: Evaluation;
  refresh: () => void;
}) {
  const { session } = useAuth();
  const { data: manifest, reload } = useResource<Manifest>(
    `/evaluations/${evaluation.id}/manifest`,
  );
  const changed = useCallback(() => {
    reload();
    refresh();
  }, [reload, refresh]);
  const { events, connection } = useEvaluationEvents(evaluation.id, changed);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Release | null>(null);
  const [auditor, setAuditor] = useState("");
  const mutate = async (action: string) => {
    setBusy(true);
    setError("");
    try {
      await operatorRequest(`/evaluations/${evaluation.id}/${action}`, {
        method: "POST",
        csrf: session.csrf_token,
      });
      reload();
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };
  const state = manifest?.status || evaluation.status;
  const isCampaign = evaluation.evaluation_kind === "campaign";
  const localModel =
    isCampaign &&
    (manifest?.manifest.model as { provider?: string } | undefined)?.provider === "local";
  const red = session.user.role === "RED_OPERATOR";
  return (
    <>
      <Panel
        title={evaluation.name}
        subtitle={
          localModel
            ? "LOCAL MODEL · isolated CPU inference · inspect case outcomes below"
            : evaluation.execution_mode === "isolated_docker"
              ? "ISOLATED DOCKER EVALUATION · deterministic mock inference"
              : "Trusted local adapters · MOCK_NOT_SAFETY_EVIDENCE"
        }
        action={<Badge tone={state === "FAILED" ? "red" : "green"}>{state}</Badge>}
      >
        <div className="live-detail">
          {error && (
            <p role="alert" className="form-error">
              {error}
            </p>
          )}
          <p>
            <strong>Manifest commitment:</strong>{" "}
            <code title={manifest?.manifest_digest || "Uncommitted"}>
              {manifest?.manifest_digest
                ? `${manifest.manifest_digest.slice(0, 16)}…`
                : "Not committed"}
            </code>
          </p>
          <p>
            Blue approval: {manifest?.blue_approved ? "Approved" : "Pending"}. Sealing freezes the
            exact versions, model, policy and budget.
          </p>
          <div className="live-version-list">
            {manifest &&
              (
                manifest.manifest.versions as { kind: string; version_id: string; sha256: string }[]
              ).map((v) => (
                <div key={v.kind}>
                  <strong>{v.kind}</strong>
                  <code title={v.version_id}>{v.version_id.slice(0, 8)}</code>
                  <code title={v.sha256}>{v.sha256.slice(0, 16)}…</code>
                </div>
              ))}
          </div>
          <div className="live-actions">
            {red && state === "CREATED" && (
              <Button disabled={busy} onClick={() => void mutate("commit")}>
                Commit versions
              </Button>
            )}
            {session.user.role === "BLUE_OPERATOR" &&
              state === "COMMITTED" &&
              !manifest?.blue_approved && (
                <Button disabled={busy} onClick={() => void mutate("approve")}>
                  Approve committed manifest
                </Button>
              )}
            {red && state === "COMMITTED" && (
              <Button
                disabled={busy || !manifest?.blue_approved}
                onClick={() => void mutate("seal")}
              >
                Seal evaluation
              </Button>
            )}
            {red && state === "SEALED" && (
              <Button disabled={busy} variant="primary" onClick={() => void mutate("start")}>
                {evaluation.execution_mode === "isolated_docker"
                  ? "Start isolated Docker evaluation"
                  : "Start local mock evaluation"}
              </Button>
            )}
            {["RED_OPERATOR", "BLUE_OPERATOR"].includes(session.user.role) &&
              ["CREATED", "COMMITTED", "SEALED", "PROVISIONING", "RUNNING", "FINALIZING"].includes(
                state,
              ) && (
                <Button disabled={busy} onClick={() => void mutate("cancel")}>
                  Cancel evaluation
                </Button>
              )}
            {red && state === "COMPLETED" && !isCampaign && (
              <Button
                onClick={() =>
                  void operatorRequest<Release>(`/evaluations/${evaluation.id}/released-result`)
                    .then(setResult)
                    .catch((e) => setError(e.message))
                }
              >
                View released result
              </Button>
            )}
            {red && ["COMPLETED", "FAILED", "CANCELLED"].includes(state) && (
              <Button disabled={busy} onClick={() => void mutate("destroy")}>
                Destroy local state
              </Button>
            )}
            <Button
              onClick={() => {
                reload();
                refresh();
              }}
            >
              Refresh evaluation
            </Button>
          </div>
          {result && <pre className="live-result">{JSON.stringify(result, null, 2)}</pre>}
          {red && (
            <form
              className="live-inline"
              onSubmit={async (e) => {
                e.preventDefault();
                try {
                  await operatorRequest(`/evaluations/${evaluation.id}/auditor`, {
                    method: "POST",
                    csrf: session.csrf_token,
                    body: { email: auditor },
                  });
                  setAuditor("");
                } catch (e) {
                  setError(e instanceof Error ? e.message : "Membership failed");
                }
              }}
            >
              <label>
                Approved auditor email
                <input
                  type="email"
                  required
                  value={auditor}
                  onChange={(e) => setAuditor(e.target.value)}
                />
              </label>
              <Button type="submit">Grant metadata membership</Button>
            </form>
          )}
        </div>
        <LiveGraph
          events={events}
          modelLabel={localModel ? "LOCAL MODEL · Qwen2.5" : "Mock model"}
        />
      </Panel>
      {isCampaign && <CampaignMonitor evaluationId={evaluation.id} refreshParent={refresh} />}
      {evaluation.execution_mode === "isolated_docker" && (
        <RuntimeInspection evaluation={{ ...evaluation, status: state }} events={events} />
      )}
      <Panel
        title="Live application trace"
        subtitle={`${connection} · ${events.length} observed events · last 500 displayed`}
        action={<Badge tone="green">REAL PERSISTED EVENTS</Badge>}
      >
        <ol className="live-trace" aria-label="Live application events">
          {events.map((event) => (
            <li key={event.event_id}>
              <code>#{event.sequence}</code>
              <strong>{event.event_type}</strong>
              <span>
                {event.source} → {event.destination}
              </span>
              <small>
                {event.permitted_metadata.message_type}{" "}
                {event.permitted_metadata.reason_code ||
                  event.permitted_metadata.status ||
                  event.permitted_metadata.guard_stage}
              </small>
            </li>
          ))}
        </ol>
        {!events.length && <p className="live-detail">Waiting for authorized persisted events.</p>}
      </Panel>
    </>
  );
}

export function LiveEvaluation() {
  const { session } = useAuth();
  const operator = ["RED_OPERATOR", "BLUE_OPERATOR"].includes(session.user.role);
  const versions = useResource<Version[]>(operator ? "/versions" : null);
  const evaluations = useResource<Evaluation[]>("/evaluations");
  const capabilities =
    useResource<components["schemas"]["RuntimeCapabilities"]>("/runtime/capabilities");
  const [executionMode, setExecutionMode] = useState<"local_mock" | "isolated_docker">(
    "local_mock",
  );
  const [selected, setSelected] = useState("");
  const [redVersion, setRedVersion] = useState("");
  const [blueVersion, setBlueVersion] = useState("");
  const [name, setName] = useState("Local mediation evaluation");
  const [content, setContent] = useState(
    session.user.role === "RED_OPERATOR"
      ? '{"cases":[{"prompt":"A harmless test request","route":"mediated"}]}'
      : '{"blocked_terms":["CANARY_PRIVATE"],"block_input":false}',
  );
  const [model, setModel] = useState<"safe" | "canary" | "error" | "timeout">("safe");
  const [cases, setCases] = useState(5);
  const [messages, setMessages] = useState(160);
  const [timeout, setTimeoutBudget] = useState(10);
  const [grantVersion, setGrantVersion] = useState("");
  const [redEmail, setRedEmail] = useState("red@nexus.local");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const current = evaluations.data?.find((e) => e.id === selected);
  const perform = async (task: () => Promise<void>) => {
    setError("");
    setBusy(true);
    try {
      await task();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="live-workspace">
      <div className="live-assurance">
        <Badge tone="green">APPLICATION-LAYER REFERENCE MONITOR</Badge>
        <Badge tone="amber">
          {current?.execution_mode === "isolated_docker" || executionMode === "isolated_docker"
            ? "ISOLATED DOCKER EVALUATION · VERIFY PROBES BELOW"
            : "IN-PROCESS MOCK · NO CONTAINER ISOLATION"}
        </Badge>
        <p>
          Live decisions from the selected runtime. Legacy evaluations use deterministic MOCK
          responses. Attack Lab campaigns explicitly identify LOCAL MODEL or MOCK; inspect their
          case criteria and model revision before interpreting outcomes.
        </p>
      </div>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {(versions.error || evaluations.error) && (
        <p role="alert">{versions.error || evaluations.error}</p>
      )}
      {operator && (
        <Panel
          title={
            session.user.role === "RED_OPERATOR"
              ? "Version a Red corpus"
              : "Version a Blue guard configuration"
          }
          subtitle="Creates immutable canonical bytes; the source artifact remains private."
        >
          <form
            className="live-form"
            onSubmit={(e) => {
              e.preventDefault();
              void perform(async () => {
                const parsed: unknown = JSON.parse(content);
                const artifact = await operatorRequest<{ id: string }>("/artifacts", {
                  method: "POST",
                  csrf: session.csrf_token,
                  body: {
                    name: "Versioned local configuration",
                    kind: session.user.role === "RED_OPERATOR" ? "attack" : "defence",
                    content,
                  },
                });
                const version = await operatorRequest<Version>(
                  `/artifacts/${artifact.id}/versions`,
                  { method: "POST", csrf: session.csrf_token, body: { content: parsed } },
                );
                versions.reload();
                if (version.kind === "attack") setRedVersion(version.version_id);
                else setGrantVersion(version.version_id);
              });
            }}
          >
            <label>
              Version content (strict JSON)
              <textarea
                rows={5}
                required
                value={content}
                onChange={(e) => setContent(e.target.value)}
              />
            </label>
            <Button type="submit" disabled={busy}>
              Create immutable version
            </Button>
          </form>
          {versions.loading && <p className="live-detail">Loading authorized references…</p>}
          <div className="live-version-list">
            {versions.data?.slice(0, 6).map((v) => (
              <div key={v.version_id}>
                <strong>{v.kind}</strong>
                <code title={v.version_id}>{v.version_id}</code>
                <small>
                  {v.byte_size} bytes · {v.sha256.slice(0, 12)}…
                </small>
              </div>
            ))}
          </div>
        </Panel>
      )}
      {session.user.role === "BLUE_OPERATOR" && (
        <Panel
          title="Authorize a Red operator"
          subtitle="Shares only an opaque version reference and digest. Approval of the exact evaluation is a separate step."
        >
          <form
            className="live-form"
            onSubmit={(e) => {
              e.preventDefault();
              void perform(async () => {
                await operatorRequest(`/versions/${grantVersion}/grants`, {
                  method: "POST",
                  csrf: session.csrf_token,
                  body: { red_email: redEmail },
                });
                versions.reload();
              });
            }}
          >
            <label>
              Blue version
              <select
                required
                value={grantVersion}
                onChange={(e) => setGrantVersion(e.target.value)}
              >
                <option value="">Select version</option>
                {versions.data?.map((v) => (
                  <option key={v.version_id} value={v.version_id}>
                    {v.version_id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Red operator email
              <input
                type="email"
                required
                value={redEmail}
                onChange={(e) => setRedEmail(e.target.value)}
              />
            </label>
            <Button type="submit" disabled={busy}>
              Grant reference access
            </Button>
          </form>
        </Panel>
      )}
      {session.user.role === "RED_OPERATOR" && (
        <Panel
          title="Create a local evaluation"
          subtitle="Fixed policy: local-flow-v1 · default DENY. Blue must approve after commitment."
        >
          <form
            className="live-form"
            onSubmit={(e) => {
              e.preventDefault();
              void perform(async () => {
                const evaluation = await operatorRequest<Evaluation>("/evaluations", {
                  method: "POST",
                  csrf: session.csrf_token,
                  body: {
                    name,
                    red_version_id: redVersion,
                    blue_version_id: blueVersion,
                    execution_mode: executionMode,
                    model_mode: model,
                    budget: {
                      max_cases: cases,
                      max_messages: messages,
                      max_bytes: 8192,
                      timeout_seconds: timeout,
                    },
                  },
                });
                evaluations.reload();
                setSelected(evaluation.id);
              });
            }}
          >
            <label>
              Execution mode
              <select
                value={executionMode}
                onChange={(e) => setExecutionMode(e.target.value as typeof executionMode)}
              >
                <option value="local_mock">LOCAL APPLICATION MOCK</option>
                <option value="isolated_docker" disabled={!capabilities.data?.available}>
                  ISOLATED DOCKER EVALUATION
                </option>
              </select>
            </label>
            {!capabilities.data?.available && (
              <p className="runtime-note">
                {capabilities.data?.reason || "Checking isolated runtime requirements…"}
              </p>
            )}
            <p className="runtime-note">
              Runtime mode is committed with the manifest. Existing sealed evaluations keep their
              approved mode.
            </p>
            <label>
              Evaluation name
              <input
                required
                maxLength={160}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              Red corpus version
              <select required value={redVersion} onChange={(e) => setRedVersion(e.target.value)}>
                <option value="">Select owned corpus</option>
                {versions.data
                  ?.filter((v) => v.kind === "attack")
                  .map((v) => (
                    <option key={v.version_id} value={v.version_id}>
                      {v.version_id}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Authorized Blue version
              <select required value={blueVersion} onChange={(e) => setBlueVersion(e.target.value)}>
                <option value="">Select granted reference</option>
                {versions.data
                  ?.filter((v) => v.kind === "defence")
                  .map((v) => (
                    <option key={v.version_id} value={v.version_id}>
                      {v.version_id}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Mock model mode
              <select value={model} onChange={(e) => setModel(e.target.value as typeof model)}>
                <option value="safe">Safe constant response</option>
                <option value="canary">Private canary output (withheld)</option>
                <option value="error">Preconfigured failure</option>
                <option value="timeout">Preconfigured timeout</option>
              </select>
            </label>
            <label>
              Policy
              <select defaultValue="local-flow-v1">
                <option value="local-flow-v1">
                  local-flow-v1 · default DENY · eight allowed flows
                </option>
              </select>
            </label>
            <div className="live-budget">
              <label>
                Maximum cases
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={cases}
                  onChange={(e) => setCases(Number(e.target.value))}
                />
              </label>
              <label>
                Message budget
                <input
                  type="number"
                  min={1}
                  max={160}
                  value={messages}
                  onChange={(e) => setMessages(Number(e.target.value))}
                />
              </label>
              <label>
                Deadline (seconds)
                <input
                  type="number"
                  min={1}
                  max={30}
                  value={timeout}
                  onChange={(e) => setTimeoutBudget(Number(e.target.value))}
                />
              </label>
            </div>
            <Button type="submit" disabled={busy} variant="primary">
              Create evaluation
            </Button>
            <Button onClick={versions.reload}>Refresh authorized references</Button>
          </form>
        </Panel>
      )}
      <Panel
        title="Authorized live evaluations"
        subtitle="Membership-scoped local mock execution only."
      >
        <div className="live-form">
          <label>
            Evaluation
            <select value={selected} onChange={(e) => setSelected(e.target.value)}>
              <option value="">Select evaluation</option>
              {evaluations.data
                ?.filter((e) => ["local_mock", "isolated_docker"].includes(e.execution_mode))
                .map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.name} · {e.status}
                  </option>
                ))}
            </select>
          </label>
          <Button onClick={evaluations.reload}>Refresh evaluations</Button>
          {!evaluations.data?.length && <p>No authorized evaluations yet.</p>}
        </div>
      </Panel>
      {current && (
        <EvaluationDetail key={current.id} evaluation={current} refresh={evaluations.reload} />
      )}
    </div>
  );
}
