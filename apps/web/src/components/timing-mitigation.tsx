"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { components } from "@/lib/api.generated";

type Report = components["schemas"]["TimingReport"];
type Isolation = components["schemas"]["IsolationView"];
const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
export function TimingMitigation({
  report,
  isolation,
  evaluationId,
  links,
}: {
  report: Report;
  isolation?: Isolation | null;
  evaluationId: string;
  links?: { trace: string; proof: string };
}) {
  const [inspected, setInspected] = useState<"standard" | "reduced" | null>(null);
  const close = useRef<HTMLButtonElement>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (inspected) close.current?.focus();
    else trigger.current?.focus();
  }, [inspected]);
  const rows = [report.standard, report.reduced];
  const detail = inspected ? report[inspected] : null;
  return (
    <section aria-label="Timing mitigation comparison" className="timing-mitigation">
      <div className="resource-summary">
        <div>
          <span className="resource-eyebrow">RECORDED MITIGATION STUDY</span>
          <strong data-testid="timing-study-status" data-status={report.status}>
            {report.status}
          </strong>
        </div>
        <p>
          Original operator-recorded study · <code>{report.experiment_id}</code>
        </p>
      </div>
      <header>
        <h2>Separate cores. Measured effect.</h2>
        <p>
          Matched native Qwen requests, separately calibrated detectors and held-out active/idle
          trials. The observer used only its own permitted inference timing.
        </p>
      </header>
      <p data-testid="timing-current-profile">
        Evidence carrier: {isolation?.security_profile.replaceAll("_", " ") || "Unobserved profile"}{" "}
        · Enforcement: {isolation?.enforcement || "Unobserved"} · Host-exclusive: No
      </p>
      <svg
        viewBox="0 0 520 170"
        className="timing-chart"
        role="img"
        aria-label="Held-out activity prediction accuracy with descriptive 95 percent intervals"
      >
        <line x1="190" y1="14" x2="190" y2="126" stroke="#d7d4e3" />
        <line x1="340" y1="14" x2="340" y2="126" stroke="#a39bb7" strokeDasharray="4 4" />
        {rows.map((row, i) => {
          const y = 36 + i * 62;
          const d = row.detector;
          return (
            <g key={row.security_profile}>
              <text x="0" y={y + 5} fill="#27314b" fontSize="12">
                {i ? "Reduced interference" : "Standard control"}
              </text>
              <rect
                x="190"
                y={y - 13}
                width={d.accuracy * 300}
                height="26"
                rx="5"
                fill={d.status === "FAIL" ? "#c34b5d" : "#8370b4"}
              />
              <line
                x1={190 + d.accuracy_95.low * 300}
                x2={190 + d.accuracy_95.high * 300}
                y1={y}
                y2={y}
                stroke="#26314a"
                strokeWidth="2"
              />
              <title>
                {row.security_profile}: {percent(d.accuracy)}, interval {percent(d.accuracy_95.low)}
                –{percent(d.accuracy_95.high)}, {row.held_out_trials} trials
              </title>
            </g>
          );
        })}
        <text x="190" y="150" fill="#655b79" fontSize="11">
          0%
        </text>
        <text x="306" y="150" fill="#655b79" fontSize="11">
          50% chance
        </text>
        <text x="467" y="150" fill="#655b79" fontSize="11">
          100%
        </text>
      </svg>
      <div className="resource-table-scroll">
        <table>
          <caption className="sr-only">Actual held-out results and performance</caption>
          <thead>
            <tr>
              <th>Observation</th>
              <th>Standard control</th>
              <th>Reduced interference</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>Activity prediction</th>
              {rows.map((r) => (
                <td key={r.security_profile}>
                  {percent(r.detector.accuracy)} · {r.held_out_trials} trials · {r.detector.status}
                </td>
              ))}
            </tr>
            <tr>
              <th>False positive / negative</th>
              {rows.map((r) => (
                <td key={r.security_profile}>
                  {percent(r.detector.false_positive_rate)} /{" "}
                  {percent(r.detector.false_negative_rate)}
                </td>
              ))}
            </tr>
            <tr>
              <th>Idle / active p50</th>
              {rows.map((r) => (
                <td key={r.security_profile}>
                  {r.inactive_latency.p50_ms ?? "Unmeasured"} /{" "}
                  {r.active_latency.p50_ms ?? "Unmeasured"} ms
                </td>
              ))}
            </tr>
            <tr>
              <th>Active p95</th>
              {rows.map((r) => (
                <td key={r.security_profile}>
                  {r.active_latency.p95_ms == null
                    ? "Not estimated"
                    : `${r.active_latency.p95_ms} ms`}
                </td>
              ))}
            </tr>
            <tr>
              <th>Recorded physical-core overlap</th>
              {rows.map((r) => (
                <td key={r.security_profile}>
                  {r.effective_affinity_verified
                    ? `${r.physical_core_overlap ?? "Unobserved"} cores`
                    : "Unverified"}
                </td>
              ))}
            </tr>
            <tr>
              <th>Cases / wall second</th>
              {rows.map((r) => (
                <td key={r.security_profile}>{r.cases_per_second.toFixed(3)}</td>
              ))}
            </tr>
            <tr>
              <th>Correct benign outputs</th>
              {rows.map((r) => (
                <td key={r.security_profile}>
                  {r.correct_outputs} / {r.held_out_trials}
                </td>
              ))}
            </tr>
            <tr>
              <th>Details</th>
              <td>
                <button
                  type="button"
                  onClick={(event) => {
                    trigger.current = event.currentTarget;
                    setInspected("standard");
                  }}
                >
                  Inspect standard control
                </button>
              </td>
              <td>
                <button
                  type="button"
                  onClick={(event) => {
                    trigger.current = event.currentTarget;
                    setInspected("reduced");
                  }}
                >
                  Inspect reduced interference
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <details className="resource-limitations">
        <summary>Study methodology and limitations</summary>
        <p>
          Operator experiment attestation. Signatures authenticate recorded bytes, not experiment
          truth or host integrity.
        </p>
        <p>
          Standard was deliberately placed on a shared physical core for this control; its normal
          default remains shared host scheduling. Reduced placement coordinates participating
          provisioners, not arbitrary host processes or legacy services. Small, correlated
          single-host trials cannot establish channel absence. Shared caches, power, kernel and
          service activity remain possible channels. No side-channel elimination is claimed.
        </p>
      </details>
      {report.residual && (
        <section aria-label="Exploratory residual timing association">
          <h3>Residual association · {report.residual.status}</h3>
          <p>
            Post hoc exploratory analysis: active requests averaged{" "}
            {report.residual.active_minus_inactive_mean_ms.toFixed(2)} ms slower. Active-slower AUC{" "}
            {report.residual.active_slower_auc.toFixed(3)}; two-sided within-block permutation p{" "}
            {report.residual.two_sided_permutation_p.toPrecision(3)}. AUC is not prediction
            accuracy. This analysis does not replace the frozen detector or validate a new
            classifier. Correlation, carryover and the single host limit interpretation; the
            mechanism remains unproven. Residual timing leakage stays a failed security assessment.
          </p>
        </section>
      )}
      <p>
        <Link href={links?.trace || `/x-ray?evaluation=${evaluationId}`}>
          Inspect resource events
        </Link>{" "}
        ·{" "}
        <Link href={links?.proof || `/proof-vault?evaluation=${evaluationId}`}>
          Verify signed timing evidence
        </Link>
      </p>
      {detail && (
        <aside
          className="resource-inspector"
          aria-label="Timing observation inspector"
          onKeyDown={(event) => {
            if (event.key === "Escape") setInspected(null);
          }}
        >
          <button ref={close} type="button" onClick={() => setInspected(null)}>
            Close timing inspector
          </button>
          <h2>{detail.security_profile.replaceAll("_", " ")}</h2>
          <p>
            Frozen calibration threshold: {detail.detector.threshold_ms} ms ·{" "}
            {detail.detector.direction}
          </p>
          <p>
            Confusion matrix: TP {detail.detector.true_positive} · TN{" "}
            {detail.detector.true_negative} · FP {detail.detector.false_positive} · FN{" "}
            {detail.detector.false_negative} · Missing {detail.detector.missing}
          </p>
          <p>
            Descriptive accuracy interval: {percent(detail.detector.accuracy_95.low)}–
            {percent(detail.detector.accuracy_95.high)}. Correlated trials limit interpretation.
          </p>
          <p>
            Exact binomial tail: {detail.detector.exact_binomial_tail.toPrecision(4)} · two-profile
            decision threshold 0.025.
          </p>
          <p>
            Own allocation wait: {detail.queue_wait_ms} ms. Median campaign completion:{" "}
            {(detail.median_completion_ms / 1000).toFixed(2)} seconds.
          </p>
          <p>Provenance: {report.provenance.replaceAll("_", " ")}. Raw evidence commitment:</p>
          <code>{report.raw_evidence_digest}</code>
        </aside>
      )}
    </section>
  );
}
