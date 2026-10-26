"use client";
import { useEffect, useMemo, useState } from "react";
import { Background, Controls, ReactFlow, MarkerType, type Node, type Edge } from "@xyflow/react";
import { useReducedMotion } from "motion/react";
import type { components } from "@/lib/api.generated";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { probeCopy } from "@/lib/product-clarity";
import { operatorRequest } from "@/lib/operator-api";
import { useAuth } from "./auth-provider";
import { useResource } from "./use-resource";
import { useEvaluationEvents } from "./use-evaluation-events";
import { RecordedGraphFit } from "./recorded-graph-fit";
import { Badge, Button, Panel } from "./ui";
import "@xyflow/react/dist/style.css";

type Runtime = components["schemas"]["RuntimeResponse"];
type Caps = components["schemas"]["RuntimeCapabilities"];
type Evaluation = components["schemas"]["EvaluationResponse"];
type Event = components["schemas"]["SecurityEventResponse"];
const tone = (status: string) =>
  status === "PASS" || status === "VERIFIED"
    ? "green"
    : status === "FAIL" || status === "FAILED"
      ? "red"
      : status === "INCONCLUSIVE"
        ? "amber"
        : "neutral";

export function RuntimeInspection({
  evaluation,
  events = [],
}: {
  evaluation: Evaluation;
  events?: Event[];
}) {
  const { session } = useAuth();
  const runtime = useResource<Runtime>(`/evaluations/${evaluation.id}/runtime`);
  const reduced = useReducedMotion();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const snapshot = runtime.data?.snapshot;
  const latest = events.findLast((e) =>
    ["RUNTIME_UPDATED", "RUNTIME_TEARDOWN", "SECURITY_PROBE_RESULT"].includes(e.event_type),
  );
  useEffect(() => {
    if (!latest) return;
    const timer = setTimeout(runtime.reload, 0);
    return () => clearTimeout(timer);
  }, [latest, runtime.reload]);
  useEffect(() => {
    const timer = setInterval(runtime.reload, 1500);
    return () => clearInterval(timer);
  }, [runtime.reload]);
  const nodes: Node[] = useMemo(
    () =>
      [
        { id: "broker", position: { x: 260, y: 115 }, data: { label: "Trusted broker gateway" } },
        ...(snapshot?.workloads || []).map((w, i) => ({
          id: w.role,
          position: { x: i * 260, y: 0 },
          data: { label: `${w.role.toUpperCase()} · net ${w.network_id}` },
        })),
      ].map((n) => ({
        ...n,
        style: { background: "#ffffff", color: "#1d2c45", border: "1px solid #c8d2e1", width: 210 },
      })),
    [snapshot?.workloads],
  );
  const edges: Edge[] = (snapshot?.workloads || []).map((w) => ({
    id: `${w.role}-broker`,
    source: w.role,
    target: "broker",
    label: "Scoped authenticated route",
    animated: !reduced && snapshot?.state === "PROBING",
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: "#176a52" },
    labelStyle: { fill: "#596980", fontSize: 10 },
    labelBgStyle: { fill: "#ffffff" },
  }));
  for (const [source, target] of [
    ["red", "blue"],
    ["red", "model"],
    ["blue", "model"],
  ]) {
    const observed = snapshot?.probes.find(
      (p) => p.probe_id === `DIRECT_${source.toUpperCase()}_${target.toUpperCase()}`,
    );
    if (observed)
      edges.push({
        id: `deny-${source}-${target}`,
        source,
        target,
        label: `Direct: ${observed.status}`,
        style: {
          stroke: observed.status === "PASS" ? "#a83c4d" : "#845c16",
          strokeDasharray: "5 5",
        },
        labelStyle: { fill: "#a83c4d", fontSize: 10 },
        labelBgStyle: { fill: "#ffffff" },
      });
  }
  const runProbes = async () => {
    setBusy(true);
    setError("");
    try {
      await operatorRequest(`/evaluations/${evaluation.id}/probes`, {
        method: "POST",
        csrf: session.csrf_token,
      });
      runtime.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Probe launch failed");
    } finally {
      setBusy(false);
    }
  };
  if (evaluation.execution_mode !== "isolated_docker")
    return (
      <Panel title="Runtime inspection" subtitle="Local application mode">
        <p className="live-detail">
          This evaluation uses trusted in-process mocks. It has no container-isolation proof. Select
          isolated mode when creating a new evaluation to bind that choice before commitment.
        </p>
      </Panel>
    );
  return (
    <div className="runtime-observatory" data-testid="runtime-inspection">
      <Panel
        title="Isolated runtime overview"
        subtitle="ISOLATED DOCKER EVALUATION · actual persisted observations"
        action={
          <Badge tone={snapshot?.cleanup === "FAILED" ? "red" : "blue"}>
            {snapshot?.state || "NO RECORDED RUNTIME"}
          </Badge>
        }
      >
        <p className="clarity-lead">
          {snapshot
            ? `${snapshot.workloads.length} workload identities recorded · ${snapshot.container_count} present at the last runtime observation · Cleanup ${snapshot.cleanup}`
            : "No recorded runtime snapshot is available."}
        </p>
        <p className="runtime-note">
          {snapshot?.cleanup === "VERIFIED"
            ? "Cleanup verified. The cards below show the recorded workloads before removal."
            : "Recorded workload inspection. Refresh to check for newer observations."}
        </p>
        <nav className="guided-actions">
          <Link href={`/evaluations/${evaluation.id}`}>Back to evaluation</Link>
          <Link href={`/x-ray?evaluation=${evaluation.id}`}>Explore recorded execution</Link>
          <Link href={`/proof-vault?evaluation=${evaluation.id}`}>Inspect signed evidence</Link>
        </nav>
        <details className="guided-advanced">
          <summary>Runtime identity and host profile</summary>
          <div className="runtime-overview">
            <div>
              <small>Evaluation</small>
              <code>{evaluation.id.slice(0, 12)}</code>
            </div>
            <div>
              <small>Workloads present at last observation</small>
              <strong data-testid="container-count">
                {snapshot?.container_count ?? "Not recorded"}
              </strong>
            </div>
            <div>
              <small>Host profile</small>
              <strong>
                {snapshot
                  ? `${snapshot.profile.profile} · ${snapshot.profile.cgroups}`
                  : "Unverified"}
              </strong>
            </div>
            <div>
              <small>Teardown</small>
              <Badge tone={tone(snapshot?.cleanup || "")}>
                {snapshot?.cleanup || "NOT STARTED"}
              </Badge>
            </div>
          </div>
        </details>
        <details className="runtime-note">
          <summary>Network configuration and technical scope</summary>
          <p>
            Scoped workload networks; no published tenant ports. Red/Blue have no host mounts; a
            real model receives only its approved read-only artifact cache. Historical cards remain
            after verified removal. Rootful Docker and the host remain trusted; shared-kernel side
            channels are not eliminated.
          </p>
        </details>
        {(runtime.error || error) && (
          <p className="form-error" role="alert">
            {runtime.error || error}
          </p>
        )}
      </Panel>
      {snapshot && (
        <>
          <div className="runtime-workload-grid">
            {snapshot.workloads.map((w) => (
              <Panel
                key={w.role}
                title={
                  w.role === "blue"
                    ? "Sealed Blue defence"
                    : w.role === "model"
                      ? "Model worker"
                      : "Red runner"
                }
                subtitle={`Container ${w.container_id}`}
                action={
                  <Badge
                    tone={
                      snapshot.cleanup === "VERIFIED"
                        ? "neutral"
                        : w.health === "READY"
                          ? "green"
                          : "neutral"
                    }
                  >
                    {snapshot.cleanup === "VERIFIED" ? "Historical · removed" : w.health}
                  </Badge>
                }
              >
                <dl className="runtime-workload-data">
                  <div>
                    <dt>Resource profile / image</dt>
                    <dd>
                      {w.resource_profile} ·{" "}
                      <code title={w.image_digest}>{w.image_digest.slice(0, 24)}…</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Network</dt>
                    <dd>
                      <code>{w.network_id}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>CPU sample / quota</dt>
                    <dd>
                      {w.cpu_percent == null ? "—" : w.cpu_percent.toFixed(2)}% / {w.cpu_limit} CPU
                    </dd>
                  </div>
                  <div>
                    <dt>Memory sample / limit</dt>
                    <dd>
                      {w.memory_bytes == null ? "—" : (w.memory_bytes / 1048576).toFixed(1)} /{" "}
                      {w.memory_limit / 1048576} MiB
                    </dd>
                  </div>
                  <div>
                    <dt>PID maximum</dt>
                    <dd>{w.pids_limit}</dd>
                  </div>
                </dl>
                <details className="runtime-evidence">
                  <summary>Effective security controls</summary>
                  {Object.entries(w.controls).map(([key, pass]) => (
                    <div key={key}>
                      <span>{key.replaceAll("_", " ")}</span>
                      <Badge tone={pass ? "green" : "red"}>{pass ? "VERIFIED" : "FAIL"}</Badge>
                    </div>
                  ))}
                </details>
              </Panel>
            ))}
          </div>
          <Panel
            title="Observed network segmentation"
            subtitle={
              snapshot.cleanup === "VERIFIED"
                ? "Historical inspected membership · these containers and networks have been removed."
                : "Inspected membership · dashed edges show actual direct-access probe outcomes."
            }
          >
            <div className="runtime-network">
              <ReactFlow
                key={snapshot.workloads.map((w) => w.container_id).join(":")}
                nodes={nodes}
                edges={edges}
                fitView
                fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
                nodesDraggable={false}
                nodesConnectable={false}
              >
                <RecordedGraphFit />
                <Background color="#dce3ee" />
                <Controls showInteractive={false} />
              </ReactFlow>
            </div>
          </Panel>
          <Panel
            title="Security probe console"
            subtitle="Fixed authorized probes only · expected and observed results remain distinct"
            action={
              <Button
                disabled={
                  busy ||
                  session.user.role !== "RED_OPERATOR" ||
                  !["SEALED", "COMPLETED", "FAILED", "CANCELLED"].includes(evaluation.status) ||
                  !["CLEANED", "CLEANUP_FAILED"].includes(snapshot.state)
                }
                onClick={() => void runProbes()}
              >
                Run predefined security probes
              </Button>
            }
          >
            <p className="runtime-note">
              Startup runs the probe suite automatically. A separate verification run creates and
              cleans fresh scoped workloads without executing new inference. Full mediated-flow
              evidence comes from an evaluation run. Unsupported/inconclusive checks are never
              counted as passes.
            </p>
            <div className="runtime-probes">
              {snapshot.probes.map((p, i) => (
                <details key={`${p.probe_id}-${i}`} className="runtime-probe">
                  <summary>
                    <Badge tone={tone(p.status)}>{p.status}</Badge>
                    <strong>{probeCopy(p).title}</strong>
                    <span>
                      {p.source} → {p.target}
                    </span>
                  </summary>
                  <p>{probeCopy(p).detail}</p>
                  <dl>
                    <div>
                      <dt>Original probe identifier</dt>
                      <dd>{p.probe_id}</dd>
                    </div>
                    <div>
                      <dt>Expected</dt>
                      <dd>{p.expected}</dd>
                    </div>
                    <div>
                      <dt>Observed</dt>
                      <dd>{p.observed}</dd>
                    </div>
                    <div>
                      <dt>Observation time</dt>
                      <dd>{new Date(p.timestamp).toISOString()}</dd>
                    </div>
                    <div>
                      <dt>Runtime profile</dt>
                      <dd>
                        {p.profile} · {snapshot.profile.engine_version}
                      </dd>
                    </div>
                  </dl>
                </details>
              ))}
            </div>
            {!snapshot.probes.length && (
              <p className="runtime-note">No completed probe observations yet.</p>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}

export function RuntimeObservatory() {
  const caps = useResource<Caps>("/runtime/capabilities");
  const evaluations = useResource<Evaluation[]>("/evaluations");
  const params = useSearchParams(),
    router = useRouter();
  const selected = params.get("evaluation") || "";
  const current = evaluations.data?.find((e) => e.id === selected);
  return (
    <div className="page-stack">
      <Panel
        title="Runtime host availability"
        subtitle="Availability is checked through the confined API and trusted provisioner"
        action={
          <Badge tone={caps.data?.available ? "green" : "amber"}>
            {caps.data
              ? caps.data.available
                ? "ISOLATED MODE AVAILABLE"
                : "ISOLATED MODE UNAVAILABLE"
              : caps.error
                ? "AVAILABILITY UNKNOWN"
                : "CHECKING AVAILABILITY"}
          </Badge>
        }
      >
        <p className="runtime-note">
          {caps.data?.reason || caps.error || "Checking host requirements…"}
        </p>
        <div className="live-form">
          <label>
            Inspect evaluation
            <select
              value={selected}
              onChange={(e) =>
                router.replace(
                  `/isolation-observatory${e.target.value ? `?evaluation=${e.target.value}` : ""}`,
                  { scroll: false },
                )
              }
            >
              <option value="">Select an authorized evaluation</option>
              {evaluations.data?.map((e) => (
                <option value={e.id} key={e.id}>
                  {e.name} · {e.execution_mode} · {e.status}
                </option>
              ))}
            </select>
          </label>
          <Button
            onClick={() => {
              evaluations.reload();
              caps.reload();
            }}
          >
            Refresh runtime availability
          </Button>
        </div>
      </Panel>
      {selected && !evaluations.loading && !current && (
        <p role="alert">
          This evaluation is unavailable under your identity. Choose an authorized record.
        </p>
      )}
      {current && (
        <ObservedRuntime key={current.id} evaluation={current} refresh={evaluations.reload} />
      )}
    </div>
  );
}

function ObservedRuntime({ evaluation, refresh }: { evaluation: Evaluation; refresh: () => void }) {
  const { events, connection } = useEvaluationEvents(evaluation.id, refresh);
  return (
    <>
      <RuntimeInspection evaluation={evaluation} events={events} />
      <Panel title="Runtime event timeline" subtitle={`${connection} · last 500 permitted events`}>
        <ol className="live-trace" aria-label="Runtime event timeline">
          {events.map((event) => (
            <li key={event.event_id}>
              <code>#{event.sequence}</code>
              <strong>{event.event_type}</strong>
              <span>
                {event.source} → {event.destination}
              </span>
              <small>
                {event.permitted_metadata.runtime_state ||
                  event.permitted_metadata.probe_status ||
                  event.permitted_metadata.reason_code ||
                  event.permitted_metadata.status}
              </small>
            </li>
          ))}
        </ol>
        {!events.length && (
          <p className="runtime-note">No permitted runtime events observed yet.</p>
        )}
      </Panel>
    </>
  );
}
