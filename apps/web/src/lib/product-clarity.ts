import type { components } from "./api.generated";
type Verification = components["schemas"]["Verification"];
type Event = components["schemas"]["SecurityEventResponse"];
type Probe = components["schemas"]["ProbeView"];

// Presentation only: these helpers never infer enforcement from configuration or rewrite records.
export function verificationCopy(check?: Verification | null) {
  if (!check)
    return {
      title: "Verification has not been run",
      detail: "A signed record still needs a check against an approved signing key.",
      verified: false,
    };
  if (check.status === "VALID" && check.signature_valid && check.signer_trusted)
    return {
      title: "Evidence integrity verified",
      detail:
        "The checked record matches its trusted signature. This checks recorded bytes, not event truth or model safety.",
      verified: true,
    };
  if (check.status === "UNTRUSTED_SIGNER" || (check.status === "VALID" && !check.signer_trusted))
    return {
      title: "Signing key not trusted",
      detail:
        "The signature cannot be trusted because an approved signing key has not been established for this check.",
      verified: false,
    };
  if (check.status === "INVALID")
    return {
      title: "Verification failed",
      detail:
        "The checked evidence did not pass integrity verification. Inspect the verifier's reason before drawing conclusions.",
      verified: false,
    };
  return {
    title: "Evidence verification incomplete",
    detail:
      "The verifier could not establish valid, trusted evidence. Inspect the format, completeness and verification details.",
    verified: false,
  };
}
const momentLabels: Record<string, string> = {
  ARTIFACT_COMMITTED: "Attack version locked for this test",
  BLUE_APPROVED: "Blue approved this exact test",
  EVALUATION_SEALED: "Test configuration locked",
  INPUT_GUARD_EVALUATED: "Input defence applied",
  MODEL_INFERENCE_STARTED: "AI inference started",
  MODEL_INFERENCE_COMPLETED: "AI inference finished",
  OUTPUT_GUARD_EVALUATED: "Output defence applied",
  POLICY_DENIED: "Security gateway denied a request",
  EVALUATION_COMPLETED: "Evaluation completed",
  EVALUATION_FAILED: "Evaluation failed",
  EVALUATION_CANCELLED: "Evaluation cancelled",
};
export function momentLabel(event: Event): string | null {
  const m = event.permitted_metadata;
  if (["RUNTIME_TEARDOWN", "RUNTIME_UPDATED"].includes(event.event_type)) {
    if (m.cleanup_status === "VERIFIED") return "Cleanup verified";
    if (m.cleanup_status === "FAILED") return "Cleanup failed";
    if (m.runtime_state === "TEARDOWN") return "Cleanup in progress · not yet verified";
    return null;
  }
  const label = momentLabels[event.event_type];
  if (!label) return null;
  return ["INPUT_GUARD_EVALUATED", "OUTPUT_GUARD_EVALUATED"].includes(event.event_type) &&
    m.defence_action
    ? `${label} · ${m.defence_action}`
    : label;
}
export function keyMoments(events: Event[]): { event: Event; label: string }[] {
  return events.flatMap((event) => {
    const label = momentLabel(event);
    return label ? [{ event, label }] : [];
  });
}
export function probeCopy(probe: Probe) {
  const direct = /^DIRECT_(RED|BLUE|MODEL)_(RED|BLUE|MODEL)$/.exec(probe.probe_id);
  if (direct) {
    const route = `${direct[1]} → ${direct[2]}`;
    if (probe.status === "PASS" && probe.expected === "DENIED")
      return {
        title: `Direct ${route} connection blocked`,
        detail: "Security check passed. The observed connection attempt was denied as required.",
      };
    return {
      title: `Direct ${route} connection check · ${probe.status}`,
      detail:
        probe.status === "FAIL"
          ? "The connection check failed. Inspect the expected and observed results."
          : "Blocking has not been established by this observation. Inspect the recorded result.",
    };
  }
  return {
    title: `${probe.probe_id.replaceAll("_", " ")} · ${probe.status}`,
    detail:
      "This status applies to the recorded probe only; expand for the expected and observed results.",
  };
}
export const outcomeMeaning: Record<string, string> = {
  PASS: "The specific recorded check met its criterion.",
  FAIL: "The specific recorded security check failed; inspect its scope.",
  PARTIAL: "Some evidence supports this objective; important limits remain.",
  INCONCLUSIVE: "The measurements do not establish a definite conclusion.",
  UNSUPPORTED: "This environment or evidence format cannot establish this check.",
  NOT_TESTED: "No relevant test is recorded in this evidence scope.",
  UNVERIFIED: "Evidence trust has not been established by an approved verification.",
};
