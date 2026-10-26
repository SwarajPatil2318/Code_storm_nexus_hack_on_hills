"""Pure evidence-to-objective mapping; signatures never promote test outcomes."""

from collections import Counter

from nexus_api.assurance_schemas import AssuranceReport
from nexus_api.center_schemas import CenterFinding, CenterObjective
from nexus_api.resource_schemas import ResourceReport
from nexus_api.runtime_dto import RuntimeSnapshot
from nexus_api.timing_schemas import TimingReport

OBJECTIVES = [
    ("functional", "Functional Isolation"),
    ("confidentiality", "Information Confidentiality"),
    ("audit", "Audit Integrity"),
    ("deployment", "Reproducible Deployment"),
    ("llm", "LLM-Native Isolation"),
    ("resources", "Resource Fairness & Side Channels"),
]


def aggregate(outcomes):
    counts = Counter(outcomes)
    if counts["FAIL"]:
        return "FAIL"
    if not counts or set(counts) == {"NOT_TESTED"}:
        return "NOT_TESTED"
    if counts["PARTIAL"] or (counts["PASS"] and any(k != "PASS" for k in counts)):
        return "PARTIAL"
    if counts["INCONCLUSIVE"]:
        return "INCONCLUSIVE"
    if counts["UNSUPPORTED"]:
        return "UNSUPPORTED"
    return "PASS"


def objectives(findings):
    # Each whole objective has a mandatory unproven qualification. A bounded probe
    # cannot certify a whole Bayora objective by itself.
    qualifications = {
        "functional": "Arbitrary hostile code and uncompromised host isolation are unproven.",
        "confidentiality": (
            "General confidentiality and confidential-content recovery are not "
            "established by bounded activity tests."
        ),
        "audit": (
            "Authorized signed projections do not prove full hidden "
            "completeness, event truth or host integrity."
        ),
        "deployment": (
            "Independent clean-host installation and production qualification are not tested here."
        ),
        "llm": "Physical memory erasure and universal model confidentiality remain unproven.",
        "resources": (
            "Complete side-channel elimination and host-exclusive CPU ownership are not proven."
        ),
    }
    result = []
    for oid, title in OBJECTIVES:
        rows = [f for f in findings if f.objective == oid]
        rows.append(
            CenterFinding(
                id=oid + "-qualification",
                objective=oid,
                title="Qualification still required",
                outcome="NOT_TESTED",
                detail=qualifications[oid],
                provenance="UNPROVEN",
            )
        )
        result.append(
            CenterObjective(
                id=oid,
                title=title,
                outcome=aggregate([f.outcome for f in rows]),
                outcomes=dict(Counter(f.outcome for f in rows)),
                findings=rows,
            )
        )
    return result


def derive(source_id, runtime=None, corpus=None):
    found = []

    def add(
        key, objective, title, outcome, detail, measurements=None, attested=False, limitations=None
    ):
        found.append(
            CenterFinding(
                id=source_id + "-" + key,
                objective=objective,
                title=title,
                outcome=outcome,
                source_id=source_id,
                detail=detail,
                measurements=measurements or {},
                provenance="OPERATOR_EXPERIMENT_ATTESTATION"
                if attested
                else "RECORDED_APPLICATION",
                limitations=limitations or [],
            )
        )

    if runtime:
        rt = RuntimeSnapshot.model_validate(runtime)
        categories = {}
        for p in rt.probes:
            oid = (
                "llm"
                if p.probe_id == "FRESH_CASE_CONTEXT"
                else "resources"
                if p.probe_id.startswith("RESOURCE_") or p.probe_id == "BLOCK_IO"
                else "confidentiality"
                if p.type == "AUTHENTICATION" or p.probe_id == "BLUE_FILE_PRIVATE"
                else "functional"
            )
            categories.setdefault(oid, []).append(p)
        for oid, probes in categories.items():
            add(
                "probes-" + oid,
                oid,
                "Recorded runtime probes",
                aggregate(
                    [
                        p.status
                        if p.status in {"PASS", "FAIL", "INCONCLUSIVE", "UNSUPPORTED"}
                        else "NOT_TESTED"
                        for p in probes
                    ]
                ),
                "Bounded probes recorded by the trusted application; no host attestation.",
                {
                    "tests": len(probes),
                    "passed": sum(p.status == "PASS" for p in probes),
                    "failed": sum(p.status == "FAIL" for p in probes),
                    "unsupported": sum(p.status == "UNSUPPORTED" for p in probes),
                },
                limitations=["Recorded observations, not current operational health."],
            )
        add(
            "cleanup",
            "deployment",
            "Recorded cleanup",
            "PASS"
            if rt.cleanup == "VERIFIED"
            else "FAIL"
            if rt.cleanup == "FAILED"
            else "NOT_TESTED",
            "Historical cleanup state does not establish restart or deployment reproducibility.",
            {"cleanup": rt.cleanup},
        )
        if rt.isolation:
            iso = rt.isolation
            add(
                "cpu-enforcement",
                "resources",
                "CPU isolation enforcement",
                "PASS"
                if iso.enforcement == "VERIFIED"
                else "FAIL"
                if iso.enforcement == "FAILED"
                else "NOT_TESTED",
                (
                    "Effective affinity recorded for this execution profile; "
                    "host-exclusive ownership is not provided."
                ),
                {
                    "profile": iso.security_profile,
                    "enforcement": iso.enforcement,
                    "managed_nonoverlap": iso.managed_core_nonoverlap,
                    "host_exclusive": False,
                    "queue_wait_ms": iso.queue_wait_ms,
                },
            )
    corpus = corpus or {}
    if corpus.get("assurance_report"):
        r = AssuranceReport.model_validate(corpus["assurance_report"])
        for i, o in enumerate(r.observations):
            oid = (
                "confidentiality"
                if o.threat
                in {
                    "RED_BLUE_POLICY",
                    "BLUE_RED_PAYLOAD",
                    "TELEMETRY",
                    "UNAUTHORIZED_ACCESS",
                    "GUARDED_OUTPUT",
                }
                else "deployment"
                if o.threat == "CRASH_RESTART"
                else "llm"
            )
            add(
                "llm-" + str(i),
                oid,
                o.threat.replace("_", " ").title(),
                o.status,
                "Operator-attested experiment at the named application boundary.",
                {"trials": o.trials, "violations": o.violations, "scope": o.scope},
                True,
                ["Physical erasure is unproven; no universal model-safety claim."],
            )
        add(
            "llm-utility",
            "llm",
            "Benign utility",
            "PASS"
            if r.metrics.benign_cases and r.metrics.benign_completed == r.metrics.benign_cases
            else "INCONCLUSIVE",
            "Recorded bounded utility cohort.",
            r.metrics.model_dump(),
            True,
        )
    if corpus.get("resource_report"):
        r = ResourceReport.model_validate(corpus["resource_report"])
        for i, o in enumerate(r.observations):
            add(
                "resource-" + str(i),
                "resources",
                o.threat.replace("_", " ").title() + " · " + o.condition,
                o.status,
                (
                    "Operator-attested resource experiment; machine captures remain "
                    "separately committed."
                ),
                {f"{m.metric} ({m.unit})": m.value for m in o.measurements},
                True,
                o.limitations,
            )
        add(
            "original-timing",
            "resources",
            "Original shared-CPU timing signal",
            r.timing.status,
            "Historical activity prediction; does not demonstrate confidential payload recovery.",
            {
                "trials": r.timing.trials,
                "correct": r.timing.correct,
                "active_trials": r.timing.active,
                "inactive_trials": r.timing.inactive,
                "false_positives": r.timing.false_positives,
                "positive_control_passed": r.timing.positive_control_passed,
                "negative_control_passed": r.timing.negative_control_passed,
            },
            True,
        )
        add(
            "matched-contention",
            "resources",
            "Matched baseline and resource contention",
            "PARTIAL" if r.baseline.samples and r.stressed.samples else "INCONCLUSIVE",
            "This matched latency cohort is separate from the original timing classifier trials.",
            {
                "idle_samples": r.baseline.samples,
                "idle_failures": r.baseline.failures,
                "active_samples": r.stressed.samples,
                "active_failures": r.stressed.failures,
                "idle_p50_ms": r.baseline.p50_ms,
                "active_p50_ms": r.stressed.p50_ms,
            },
            True,
        )
    if corpus.get("timing_report"):
        r = TimingReport.model_validate(corpus["timing_report"])
        for key, p in [("shared", r.standard), ("reduced", r.reduced)]:
            d = p.detector
            add(
                "timing-" + key,
                "resources",
                "Shared-core control" if key == "shared" else "Reduced frozen detector",
                d.status,
                (
                    "Separately calibrated held-out classifier; correlated single-host "
                    "trials. Near chance does not prove channel absence."
                ),
                {
                    "trials": p.held_out_trials,
                    "correct": d.true_positive + d.true_negative,
                    "accuracy": d.accuracy,
                    "ci_low": d.accuracy_95.low,
                    "ci_high": d.accuracy_95.high,
                    "tp": d.true_positive,
                    "tn": d.true_negative,
                    "fp": d.false_positive,
                    "fn": d.false_negative,
                    "missing": d.missing,
                    "idle_p50_ms": p.inactive_latency.p50_ms,
                    "active_p50_ms": p.active_latency.p50_ms,
                    "physical_overlap": p.physical_core_overlap,
                    "correct_outputs": p.correct_outputs,
                    "cases_per_second": p.cases_per_second,
                },
                True,
            )
        add(
            "interference",
            "resources",
            "Reduced observed interference",
            "PARTIAL",
            (
                "Matched p50 activity slowdown is lower under reduced placement. "
                "This supports reduced interference in this cohort, not complete "
                "confidentiality."
            ),
            {
                "standard_active_idle_ratio": r.standard.active_latency.p50_ms
                / r.standard.inactive_latency.p50_ms
                if r.standard.inactive_latency.p50_ms
                else None,
                "reduced_active_idle_ratio": r.reduced.active_latency.p50_ms
                / r.reduced.inactive_latency.p50_ms
                if r.reduced.inactive_latency.p50_ms
                else None,
            },
            True,
        )
        if r.residual:
            add(
                "residual",
                "resources",
                "Residual timing leakage",
                r.residual.status,
                (
                    "Post hoc exploratory association, not a validated new classifier. "
                    "Shared caches, memory bandwidth, kernel, power and host activity "
                    "remain possible mechanisms. No private prompt or defence-rule "
                    "contents were recovered."
                ),
                r.residual.model_dump(exclude={"provenance", "method", "status"}),
                True,
                ["POST_HOC_EXPLORATORY", "CORRELATED_TRIALS", "SINGLE_HOST", "MECHANISM_UNPROVEN"],
            )
    return found
