"use client";
import { TimingMitigation } from "./timing-mitigation";
import { useState } from "react";
import Link from "next/link";
import type { components } from "@/lib/api.generated";
type Report = components["schemas"]["ResourceReport"];
const labels: Record<string, string> = {
  CPU_CONTENTION: "CPU quota under load",
  MEMORY_PRESSURE: "Memory ceiling",
  PID_EXHAUSTION: "Process ceiling",
  QUEUE_CONGESTION: "Admission and backpressure",
  STARVATION: "Account fairness",
  TIMING: "Timing distinguishability",
  METADATA: "Confidential metadata",
  RECOVERY: "Cleanup and recovery",
  BLOCK_IO: "Block I/O",
  SCHEDULING: "Concurrent scheduling",
};
const milliseconds = (value: number | null | undefined) =>
  value == null ? "Not measured" : `${Math.round(value).toLocaleString()} ms`;
export function ResourceExperiment({
  report,
  timingReport,
  isolation,
  evaluationId,
  links,
  related,
}: {
  report: Report | null;
  timingReport?: components["schemas"]["TimingReport"] | null;
  isolation?: components["schemas"]["IsolationView"] | null;
  evaluationId: string;
  links: { trace: string; proof: string };
  related: (id: string) => string | null;
}) {
  const [inspected, setInspected] = useState<number | null>(null);
  const observation = inspected === null ? null : report?.observations[inspected];
  return (
    <section className="assurance-experiment" aria-label="Dedicated resource experiment">
      {timingReport && (
        <TimingMitigation
          key={evaluationId}
          report={timingReport}
          isolation={isolation}
          evaluationId={evaluationId}
          links={links}
        />
      )}
      {report && (
        <>
          <div className="resource-summary">
            <div>
              <span className="resource-eyebrow">RECORDED TEST STATUS</span>
              <strong data-testid="resource-overall-status">{report.status}</strong>
            </div>
            <p>
              Dedicated resource experiment · original evaluation <code>{evaluationId}</code>
            </p>
          </div>
          <section aria-label="Matched performance comparison" className="resource-comparison">
            <h2>Baseline and CPU contention</h2>
            <p>Same corpus, model and generation settings. Warm-up is excluded.</p>
            <div className="resource-table-scroll">
              <table>
                <caption className="sr-only">Actual successful case inference latency</caption>
                <thead>
                  <tr>
                    <th>Measurement</th>
                    <th>Baseline</th>
                    <th>Contention</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th>Samples / failures</th>
                    <td>
                      {report.baseline.samples} / {report.baseline.failures}
                    </td>
                    <td>
                      {report.stressed.samples} / {report.stressed.failures}
                    </td>
                  </tr>
                  <tr>
                    <th>Median inference</th>
                    <td>{milliseconds(report.baseline.p50_ms)}</td>
                    <td>{milliseconds(report.stressed.p50_ms)}</td>
                  </tr>
                  <tr>
                    <th>Range</th>
                    <td>
                      {milliseconds(report.baseline.minimum_ms)} –{" "}
                      {milliseconds(report.baseline.maximum_ms)}
                    </td>
                    <td>
                      {milliseconds(report.stressed.minimum_ms)} –{" "}
                      {milliseconds(report.stressed.maximum_ms)}
                    </td>
                  </tr>
                  <tr>
                    <th>p95</th>
                    <td>
                      {report.baseline.p95_ms == null
                        ? "Not estimated · fewer than 20 successes"
                        : milliseconds(report.baseline.p95_ms)}
                    </td>
                    <td>
                      {report.stressed.p95_ms == null
                        ? "Not estimated · fewer than 20 successes"
                        : milliseconds(report.stressed.p95_ms)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
          <div className="resource-findings" aria-label="Measured resource boundaries">
            {report.observations.map((item, i) => (
              <button
                type="button"
                key={item.experiment_id}
                aria-expanded={inspected === i}
                aria-controls="resource-inspector"
                onClick={() => setInspected(inspected === i ? null : i)}
              >
                <span>
                  {item.condition === "DISJOINT_CPU_TIMING"
                    ? "Timing · disjoint CPU follow-up"
                    : labels[item.threat] || item.threat}
                </span>
                <strong data-testid="resource-observation-status" data-state={item.status}>
                  {item.status}
                </strong>
                <span aria-hidden="true">↗</span>
              </button>
            ))}
          </div>
          {observation && (
            <aside
              id="resource-inspector"
              className="resource-inspector"
              aria-label="Resource observation inspector"
            >
              <div>
                <h2>{labels[observation.threat]}</h2>
                <button type="button" onClick={() => setInspected(null)}>
                  Close inspector
                </button>
              </div>
              <p>
                {observation.provenance.replaceAll("_", " ")}. Aggregated measurements; raw host
                counters remain private.
              </p>
              <dl>
                {observation.measurements?.map((m, i) => (
                  <div key={i}>
                    <dt>
                      {m.metric === "throttled_periods" && observation.threat === "CPU_CONTENTION"
                        ? "background witness throttled periods"
                        : m.metric.replaceAll("_", " ")}
                    </dt>
                    <dd>
                      {Number(m.value.toFixed(3)).toLocaleString()} {m.unit}
                    </dd>
                  </div>
                ))}
              </dl>
              <p>
                Condition: {(observation.condition ?? "ORIGINAL").replaceAll("_", " ")}. Experiment:{" "}
                <code>{observation.experiment_id}</code>
              </p>
              {observation.budget && (
                <p>
                  {observation.condition === "RESOURCE_CEILING"
                    ? "Standalone witness budget"
                    : observation.condition === "DISJOINT_CPU_TIMING"
                      ? "Background witness budget"
                      : "Native evaluation budget"}
                  : {observation.budget.cpu_cores} CPU · {observation.budget.memory_bytes / 1048576}{" "}
                  MiB · {observation.budget.pids} PIDs · {observation.budget.duration_seconds}{" "}
                  second ceiling.
                </p>
              )}
              <p>
                Native evaluation profile: {report.environment.model_cpu_limit} CPU ·{" "}
                {report.environment.model_memory_mib} MiB · {report.environment.model_pids} PIDs.
                Controlled comparison uses {report.environment.compared_cpuset_size} logical CPUs.
              </p>
              <p>Limitations: {observation.limitations.join(", ").replaceAll("_", " ")}</p>
              <p className="resource-digest">
                Observation digest: <code>{observation.evidence_digest}</code>
              </p>
              {observation.evaluation_ids
                ?.filter((id) => related(id))
                .map((id) => (
                  <Link key={id} href={related(id) || links.trace}>
                    Inspect authorized evaluation {id.slice(0, 8)}
                  </Link>
                ))}
            </aside>
          )}
          <details className="resource-limit">
            <summary>Timing finding and experiment scope</summary>
            <p>
              Timing classifier: {report.timing.correct}/{report.timing.trials} correct,{" "}
              {report.timing.false_positives} false positives across {report.timing.inactive}{" "}
              inactive trials. {report.timing.status}. Small randomized trials do not prove
              side-channel absence. Shared Linux kernel and privileged host remain trusted.
            </p>
          </details>
          <div className="resource-actions">
            <Link className="button button-primary" href={links.proof}>
              Inspect signed evidence
            </Link>
            <Link className="button button-secondary" href={links.trace}>
              Inspect X-Ray record
            </Link>
          </div>
        </>
      )}
    </section>
  );
}
