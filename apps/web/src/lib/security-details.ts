import type { components } from "./api.generated";
export type Runtime = components["schemas"]["RuntimeResponse"];
export type Event = components["schemas"]["SecurityEventResponse"];
export type Proof = components["schemas"]["ProofView"];
export type Probe = components["schemas"]["ProbeView"];
export type Detail = { label: string; value: string | number | boolean };
export type Group = { title: string; rows: Detail[]; note?: string };
export const readable = (value: string) =>
  value
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/^./, (s) => s.toUpperCase());
// Drop only absent/blank values; zero and false are actual observations.
export function detailRows(values: [string, unknown][]): Detail[] {
  return values.flatMap(([label, value]) =>
    (typeof value === "string" && value.trim() !== "") ||
    typeof value === "boolean" ||
    (typeof value === "number" && Number.isFinite(value))
      ? [{ label, value: value as Detail["value"] }]
      : [],
  );
}
const controlNames: Record<string, string> = {
  non_root: "Runs without root",
  read_only: "Read-only filesystem",
  no_capabilities: "Linux capabilities dropped",
  no_new_privileges: "Privilege escalation blocked",
  private_namespaces: "Private namespaces",
  no_host_mounts: "Host mounts blocked",
  no_default_route: "Default network route removed",
  approved_read_only_model_mount: "Approved read-only model mount",
  tmpfs: "Temporary filesystem",
  limits: "Resource limits configured",
  cgroups: "Cgroup controls",
  seccomp: "System-call filter",
};
const probeIds: Record<string, (p: Probe) => boolean> = {
  network: (p) => p.probe_id.startsWith("DIRECT_"),
  resources: (p) =>
    ["RESOURCE_CPU", "RESOURCE_MEMORY", "RESOURCE_PIDS", "BLOCK_IO"].includes(p.probe_id),
  gateway: (p) => p.probe_id === "MEDIATED_FLOW",
};
export function probeFinding(p: Probe): string {
  if (p.status === "FAIL") return "Check failed";
  if (p.status === "UNSUPPORTED") return "Measurement unavailable in this runtime";
  if (p.status === "INCONCLUSIVE") return "The check did not establish an outcome";
  return p.expected === "DENIED"
    ? "Connection denied as expected"
    : p.expected === "AUTHORIZED"
      ? "Authorized flow completed"
      : "Configured limit enforced";
}
export function securityDetails(
  id: string,
  evaluationId: string,
  runtime: Runtime | null,
  events: Event[],
  proof: Proof | null,
  verified: boolean,
) {
  // Never borrow a snapshot or decision from a previous selection or another run.
  const ownRuntime = runtime?.evaluation_id === evaluationId ? runtime : null;
  const ownProof = proof?.evaluation_id === evaluationId ? proof : null;
  const ownEvents = events.filter(
    (e) => e.evaluation_id === evaluationId && e.origin !== "SIMULATED",
  );
  const snapshot = ownRuntime?.snapshot;
  const matchedVerification =
    verified &&
    ownProof?.last_verification_target === "STORED_RECEIPT" &&
    ownProof.last_verification?.status === "VALID" &&
    ownProof.last_verification.evaluation_id === evaluationId &&
    ownProof.receipts.some(
      (r) => r.receipt.payload.snapshot_id === ownProof.last_verification?.snapshot_id,
    );
  const probes = snapshot?.probes.filter(probeIds[id] || (() => false)) || [];
  const relevant = ownEvents.filter((e) => {
    if (id === "gateway")
      return (
        ["POLICY_ALLOWED", "POLICY_DENIED"].includes(e.event_type) ||
        e.permitted_metadata.probe_id === "MEDIATED_FLOW"
      );
    if (id === "confidentiality") return ["ACCESS_GRANTED", "ACCESS_DENIED"].includes(e.event_type);
    if (id === "integrity")
      return [
        "CLEANUP_VERIFIED",
        "CLEANUP_ATTEMPTED",
        "CREDENTIALS_REVOKED",
        "EVIDENCE_SIGNED",
        "RECOVERY_FAILED",
      ].includes(e.event_type);
    if (id === "workloads")
      return ["RUNTIME_UPDATED", "WORKLOAD_READY", "WORKLOAD_DESTROYED"].includes(e.event_type);
    return probes.some((p) => p.probe_id === e.permitted_metadata.probe_id);
  });
  const groups: Group[] = [];
  let note = "";
  if (id === "workloads" || id === "resources") {
    if (!snapshot?.workloads.length)
      note = "No workload inspection is attached to this evaluation yet.";
    for (const w of snapshot?.workloads || []) {
      const missing = [w.memory_bytes == null && "memory", w.cpu_percent == null && "CPU"].filter(
        Boolean,
      );
      groups.push({
        title: `${readable(w.role)} workload`,
        rows: detailRows(
          id === "workloads"
            ? [
                ["Container", w.container_id],
                ["Network", w.network_id],
                ["Lifecycle", readable(w.health)],
                ...Object.entries(w.controls).map(([k, v]): [string, unknown] => [
                  controlNames[k] || readable(k),
                  v,
                ]),
              ]
            : [
                ["Configured profile", w.resource_profile],
                ["CPU limit", `${w.cpu_limit} CPU`],
                ["Memory limit", `${w.memory_limit / 1048576} MiB`],
                ["Process limit", w.pids_limit],
                ["Last memory sample", w.memory_bytes == null ? null : `${w.memory_bytes} bytes`],
                ["Last CPU sample", w.cpu_percent == null ? null : `${w.cpu_percent}%`],
              ],
        ),
        note:
          id === "resources" && missing.length
            ? `No ${missing.join(" or ")} sample is attached to this workload.`
            : undefined,
      });
    }
    if (id === "resources") {
      const i = snapshot?.isolation;
      groups.unshift({
        title: "Execution configuration",
        rows: detailRows([
          ["Security profile", i && readable(i.security_profile)],
          ["Admission wait", i && `${i.queue_wait_ms} ms`],
          ["Managed cores separate", i?.managed_core_nonoverlap],
          ["Exclusive host", i?.host_exclusive],
          ["Snapshot updated", ownRuntime?.updated_at],
        ]),
        note: "Usage values are last available samples, not peaks.",
      });
      // A combined event sample is a separate source, never a per-workload replacement.
      const sample = ownEvents.findLast(
        (e) =>
          ["RUNTIME_UPDATED", "RUNTIME_TEARDOWN"].includes(e.event_type) &&
          (e.permitted_metadata.memory_bytes != null || e.permitted_metadata.cpu_percent != null),
      );
      if (sample)
        groups.push({
          title: "Combined workload sample",
          rows: detailRows([
            [
              "Memory",
              sample.permitted_metadata.memory_bytes == null
                ? null
                : `${sample.permitted_metadata.memory_bytes} bytes`,
            ],
            [
              "CPU",
              sample.permitted_metadata.cpu_percent == null
                ? null
                : `${sample.permitted_metadata.cpu_percent}%`,
            ],
            ["Sample time", sample.timestamp],
            ["Source event", sample.sequence ?? sample.event_id],
          ]),
          note: "Combined across workloads at this event; separate from individual last samples.",
        });
    }
  }
  if (id === "network" && !probes.length)
    note = "No direct-connection check is attached to this evaluation yet.";
  if (id === "confidentiality") {
    note = relevant.length
      ? "These content-access decisions belong to this evaluation and your authorized event projection."
      : "Role and membership checks scope access to each team's content. No run-scoped content-access test is attached to this view.";
  }
  if (id === "gateway") {
    const decisions = relevant.filter((e) =>
      ["POLICY_ALLOWED", "POLICY_DENIED"].includes(e.event_type),
    );
    if (decisions.length)
      groups.push({
        title: "Decisions in the available trace",
        rows: detailRows([
          ["Allowed", decisions.filter((e) => e.event_type === "POLICY_ALLOWED").length],
          ["Denied", decisions.filter((e) => e.event_type === "POLICY_DENIED").length],
        ]),
      });
    else
      note =
        "Evaluation requests pass through the Reference Monitor. No gateway decision is attached to this trace yet.";
  }
  if (id === "integrity") {
    const cleanup = ownRuntime?.cleanup_status ?? snapshot?.cleanup;
    groups.push({
      title: "Cleanup",
      rows: detailRows([
        ["Workload cleanup", cleanup && readable(cleanup)],
        ["Recovery", ownRuntime?.recovery_state && readable(ownRuntime.recovery_state)],
        ["Workload credentials revoked", ownRuntime?.credentials_revoked],
        ["Recovery reason", ownRuntime?.recovery_reason && readable(ownRuntime.recovery_reason)],
      ]),
    });
    groups.push({
      title: "Signed evidence",
      rows: detailRows([
        ["Evidence", ownProof && readable(ownProof.evidence_status)],
        ["Receipts", ownProof?.receipts.length],
        [
          "Stored snapshot verification",
          matchedVerification
            ? "Valid — matched stored receipt"
            : "No matching trusted verification is recorded",
        ],
        [
          "Last verification target",
          ownProof?.last_verification_target && readable(ownProof.last_verification_target),
        ],
        ["Last check result", ownProof?.last_verification?.status],
      ]),
    });
    for (const r of ownProof?.receipts || [])
      groups.push({
        title: "Receipt identity",
        rows: detailRows([
          ["Receipt", r.id],
          ["Snapshot", r.receipt.payload.snapshot_id],
          ["Evaluation", r.receipt.payload.evaluation_id],
        ]),
      });
    if (!cleanup) note = "No cleanup observation is attached to this evaluation yet.";
  }
  return {
    groups: groups.filter((g) => g.rows.length),
    note,
    probes,
    events: relevant,
    raw: {
      evaluation_id: evaluationId,
      runtime: ownRuntime,
      events: relevant,
      ...(id === "integrity" ? { proof: ownProof } : {}),
    },
  };
}
