import type { components } from "./api.generated";
type Runtime = components["schemas"]["RuntimeResponse"];
type Event = components["schemas"]["SecurityEventResponse"];
export type SecurityState =
  | "PENDING"
  | "OBSERVED"
  | "TESTED_PASS"
  | "TESTED_FAIL"
  | "INCONCLUSIVE"
  | "UNSUPPORTED"
  | "NOT_TESTED";
export type SecurityCard = {
  id: string;
  title: string;
  property: string;
  state: SecurityState;
  checked: string;
  meaning: string;
  limit: string;
  sequence?: number;
  probeIds?: string[];
};
export function scopedSecurity(
  runtime: Runtime | null,
  events: Event[],
  terminal: boolean,
  signed: boolean,
  verified: boolean,
): SecurityCard[] {
  const snapshot = runtime?.snapshot;
  const probes = (ids: (id: string) => boolean) =>
    snapshot?.probes.filter((p) => ids(p.probe_id)) || [];
  const observed = (type: string) => events.findLast((e) => e.event_type === type);
  const direct = probes((id) => id.startsWith("DIRECT_"));
  const resource = probes((id) =>
    ["RESOURCE_CPU", "RESOURCE_MEMORY", "RESOURCE_PIDS", "BLOCK_IO"].includes(id),
  );
  const stateFor = (rows: typeof direct): SecurityState =>
    rows.some((p) => p.status === "FAIL")
      ? "TESTED_FAIL"
      : rows.some((p) => p.status === "INCONCLUSIVE")
        ? "INCONCLUSIVE"
        : rows.length && rows.every((p) => p.status === "PASS")
          ? "TESTED_PASS"
          : rows.some((p) => p.status === "UNSUPPORTED")
            ? "UNSUPPORTED"
            : terminal
              ? "NOT_TESTED"
              : "PENDING";
  const workloads = snapshot?.workloads || [];
  const controls = [
    "non_root",
    "read_only",
    "no_capabilities",
    "no_new_privileges",
    "private_namespaces",
  ];
  const controlsObserved =
    workloads.length === 3 && workloads.every((w) => controls.every((k) => w.controls[k] === true));
  const allow = observed("POLICY_ALLOWED"),
    cleanup = runtime?.cleanup_status ?? snapshot?.cleanup;
  return [
    {
      id: "workloads",
      title: "Isolated workloads",
      property: "Red, Blue and Qwen use distinct workload identities.",
      state: controlsObserved ? "OBSERVED" : terminal ? "NOT_TESTED" : "PENDING",
      checked: controlsObserved
        ? "Three runtime identities inspected: non-root, read-only, dropped capabilities and private namespaces."
        : "Required workload/control observations are not yet complete.",
      meaning: "Effective container controls are inspected separately from case outcomes.",
      limit:
        "Shared kernel and rootful Docker remain trusted; this is not hardware isolation or physical erasure.",
      sequence: observed("RUNTIME_UPDATED")?.sequence ?? undefined,
    },
    {
      id: "network",
      title: "Network boundaries",
      property: "Direct tenant routes must be denied.",
      state:
        direct.length === 6 && direct.every((p) => p.status === "PASS" && p.expected === "DENIED")
          ? "TESTED_PASS"
          : direct.some((p) => p.status === "FAIL")
            ? "TESTED_FAIL"
            : direct.some((p) => p.status === "INCONCLUSIVE")
              ? "INCONCLUSIVE"
              : direct.some((p) => p.status === "UNSUPPORTED")
                ? "UNSUPPORTED"
                : direct.length
                  ? "OBSERVED"
                  : terminal
                    ? "NOT_TESTED"
                    : "PENDING",
      checked: direct.length
        ? `${direct.filter((p) => p.status === "PASS" && p.expected === "DENIED").length}/${direct.length} recorded direct-route checks observed denial.`
        : "No direct-route probe is attached to this observation.",
      meaning: "A passing expected-denial check means the attempted direct connection was blocked.",
      limit:
        "Untested routes and privileged host access remain outside this result. Logical graph edges are not physical connections.",
      probeIds: direct.map((p) => p.probe_id),
    },
    {
      id: "confidentiality",
      title: "Team privacy",
      property: "Human operators receive only their authorized projection.",
      state: "NOT_TESTED",
      checked:
        "This view uses authenticated membership-scoped endpoints. No per-run Red↔Blue content-authorization test attestation is exposed here.",
      meaning:
        "Safe metadata visibility is not proof that every cross-role content attempt was tested.",
      limit:
        "Do not infer a confidentiality PASS from an approval, hidden UI, runtime probe or another run’s test. Server-denial checks are reported separately.",
    },
    {
      id: "gateway",
      title: "Trusted gateway",
      property: "Permitted operations pass through the Reference Monitor.",
      state: allow ? "OBSERVED" : terminal ? "NOT_TESTED" : "PENDING",
      checked: `${events.filter((e) => e.event_type === "POLICY_ALLOWED").length} visible ALLOW and ${events.filter((e) => e.event_type === "POLICY_DENIED").length} DENY decisions.`,
      meaning:
        "Each original decision binds a source, destination, correlation and policy commitment.",
      limit:
        "These events are application decisions, not packet capture or independent event-truth attestations.",
      sequence:
        events.findLast((e) => ["POLICY_ALLOWED", "POLICY_DENIED"].includes(e.event_type))
          ?.sequence ?? undefined,
    },
    {
      id: "resources",
      title: "Runtime limits",
      property: "Each workload has bounded CPU, memory and process limits.",
      state:
        stateFor(resource) === "TESTED_PASS" &&
        !["RESOURCE_CPU", "RESOURCE_MEMORY", "RESOURCE_PIDS"].every((id) =>
          resource.some((p) => p.probe_id === id),
        )
          ? "OBSERVED"
          : stateFor(resource),
      checked: resource.length
        ? `${resource.length} attached resource checks; expand original results. Samples are not peaks.`
        : "No resource probe is attached yet.",
      meaning:
        "Configured budgets, inspected limits and bounded probe outcomes stay separate; unsupported block I/O is retained.",
      limit:
        "No exclusive-host, continuous telemetry, peak usage, fairness or side-channel elimination claim follows.",
      probeIds: resource.map((p) => p.probe_id),
    },
    {
      id: "integrity",
      title: "Evidence and cleanup",
      property: "Cleanup and trusted evidence are checked independently.",
      state:
        cleanup === "FAILED"
          ? "TESTED_FAIL"
          : cleanup === "VERIFIED" && verified
            ? "TESTED_PASS"
            : signed || cleanup === "VERIFIED"
              ? "OBSERVED"
              : terminal
                ? "NOT_TESTED"
                : "PENDING",
      checked: `Cleanup ${cleanup ?? "PENDING"}; snapshot ${signed ? "SIGNED" : "not signed"}; trusted stored-snapshot verification ${verified ? "VALID" : "not established"}.`,
      meaning:
        "VALID requires an actual trusted check matching this evaluation and a stored signed snapshot.",
      limit:
        "A signature does not prove host integrity, event truth, hidden completeness, latestness or physical memory erasure.",
      sequence:
        (observed("CLEANUP_VERIFIED") ?? observed("EVALUATION_COMPLETED"))?.sequence ?? undefined,
    },
  ];
}
// Primary copy describes only the available run data. Exact QA states and probes
// remain in the inspector, including failures, unsupported and missing checks.
export function securitySummary(
  card: SecurityCard,
  runtime: Runtime | null,
  events: Event[],
): string {
  const snapshot = runtime?.snapshot;
  switch (card.id) {
    case "workloads":
      return card.state === "OBSERVED"
        ? `${snapshot?.workloads.length} restricted workloads inspected.`
        : "Separate workload identities with restricted execution.";
    case "network": {
      const checks = snapshot?.probes.filter((p) => p.probe_id.startsWith("DIRECT_")) || [];
      const denied = checks.filter((p) => p.expected === "DENIED" && p.status === "PASS").length;
      return checks.length
        ? `${denied} of ${checks.length} recorded direct-connection checks were denied.${checks.some((p) => p.status === "FAIL") ? " A check failed; inspect the finding." : ""}`
        : "Direct workload connections are restricted by the runtime.";
    }
    case "confidentiality":
      return "Role and membership checks protect each team’s private content.";
    case "gateway": {
      const count = events.filter((e) => e.event_type === "POLICY_ALLOWED").length;
      return count
        ? `${count} authorized decisions in the available trace.`
        : "Evaluation requests pass through the Reference Monitor.";
    }
    case "resources":
      return snapshot?.workloads.length
        ? `${snapshot.workloads.length} workloads with CPU, memory and process budgets.${snapshot.probes.some((p) => p.probe_id.startsWith("RESOURCE_") && p.status === "FAIL") ? " A resource check failed; inspect details." : ""}`
        : "CPU, memory and process budgets bound workload execution.";
    default:
      return (runtime?.cleanup_status ?? snapshot?.cleanup) === "FAILED"
        ? "Cleanup requires attention. Inspect the recorded failure."
        : (runtime?.cleanup_status ?? snapshot?.cleanup) === "VERIFIED"
          ? "Workload cleanup verified. Open evidence to check signing and verification."
          : "Cleanup and signed evidence are tracked separately.";
  }
}
export function recordedElapsed(
  events: Event[],
  terminal: boolean,
): { start: string; end: string | null } | null {
  // Start at the first persisted provisioning observation, never a page-load clock.
  const first = events.find(
    (e) =>
      ["RUNTIME_UPDATED", "WORKLOAD_STARTING"].includes(e.event_type) &&
      (e.permitted_metadata.runtime_state === "PROVISIONING" ||
        e.event_type === "WORKLOAD_STARTING"),
  );
  const last = events.findLast((e) =>
    ["EVALUATION_COMPLETED", "EVALUATION_FAILED", "EVALUATION_CANCELLED"].includes(e.event_type),
  );
  return first
    ? { start: first.timestamp, end: terminal ? (last?.timestamp ?? null) : null }
    : null;
}
