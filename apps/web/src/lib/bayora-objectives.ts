export const bayoraObjectives = [
  {
    id: "functional",
    title: "Isolate Without Breaking Function",
    description: "Keep mutually untrusted workloads separate while real evaluation still works.",
    mechanism:
      "Restricted Red/Blue/Qwen containers, mediated evaluation lifecycle and explicit case outcomes.",
    limit: "A working case alone does not prove every isolation boundary.",
  },
  {
    id: "confidentiality",
    title: "Prevent Information Leakage",
    description: "Keep each team’s private material inside its authorized domain.",
    mechanism: "Role/owner/membership checks, sealed versions and scoped output projections.",
    limit: "Runtime network probes do not certify all human content permissions or side channels.",
  },
  {
    id: "audit",
    title: "Guarantee Audit Integrity",
    description: "Check the committed evidence bytes and who signed them.",
    mechanism:
      "Ordered snapshots, immutable receipts and independently pinned signer verification.",
    limit:
      "Signed is distinct from verified; signatures do not prove event truth or full hidden completeness.",
  },
  {
    id: "deployment",
    title: "Build for Deployability",
    description: "Reproduce setup using documented, bounded deployment procedures.",
    mechanism:
      "Pinned dependencies, migrations, scoped launchers and documented clean same-host qualification.",
    limit:
      "Same-host qualification is documented; independent-host deployment remains unverified. A single run is not deployment qualification.",
  },
  {
    id: "llm",
    title: "Address LLM-Native Threats",
    description: "Measure specific adversarial objectives with the actual Qwen model.",
    mechanism:
      "Immutable synthetic corpora, literal input/output guards and explicit scoring criteria.",
    limit:
      "Literal rules can be bypassed and can intervene on benign input; no semantic safety classifier is claimed.",
  },
  {
    id: "resources",
    title: "Quantify Residual Risk",
    description: "Measure bounded resource and timing risks, keeping unresolved findings visible.",
    mechanism: "Inspected limits, scoped probes and separately signed resource/timing experiments.",
    limit:
      "Shared kernel/rootful Docker trust, physical erasure limits and residual timing leakage remain. Historical residual timing FAIL must not be turned green by a passing receipt.",
  },
] as const;
