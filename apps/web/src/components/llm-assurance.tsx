"use client";
import Link from "next/link";
import { useState } from "react";
import type { components } from "@/lib/api.generated";
const names: Record<string, string> = {
  PROMPT_CONTAMINATION: "Input context",
  OUTPUT_CONTAMINATION: "Released output",
  RESIDUAL_CONTEXT: "Cross-evaluation recall",
  KV_CACHE: "Cache configuration",
  WRITABLE_STATE: "Worker filesystem",
  CREDENTIAL_TEARDOWN: "Scoped credentials",
  RED_BLUE_POLICY: "Blue policy privacy",
  BLUE_RED_PAYLOAD: "Red payload privacy",
  TELEMETRY: "Filtered telemetry",
  UNAUTHORIZED_ACCESS: "Cross-scope access",
  CRASH_RESTART: "Lifecycle recovery",
  GUARDED_OUTPUT: "Guarded release",
};
export function LLMExperiment({
  report,
  evaluationId,
  links,
  related,
}: {
  report: components["schemas"]["AssuranceReport"];
  evaluationId: string;
  links: { trace: string; proof: string };
  related: (id: string) => string | null;
}) {
  const metrics = report.metrics;
  const failed = report.observations.filter((o) => o.status === "FAIL").length;
  const [category, setCategory] = useState("context");
  const contextThreats = [
    "PROMPT_CONTAMINATION",
    "RESIDUAL_CONTEXT",
    "KV_CACHE",
    "WRITABLE_STATE",
    "CRASH_RESTART",
  ];
  return (
    <section className="assurance-experiment" aria-label="Dedicated model-security experiment">
      {metrics && (
        <>
          {failed > 0 && (
            <p role="alert" className="form-error">
              The original experiment includes {failed} failed finding(s). Inspect the context or
              access findings below.
            </p>
          )}
          <article className="proof-verification">
            <h2>Information-leakage experiments</h2>
            <p>
              Dedicated experiment · original evaluation <code>{evaluationId}</code>
            </p>
            <dl className="proof-facts" aria-label="Separate measurements">
              {[
                ["Attack success", `${metrics.attack_successes} / ${metrics.attack_cases}`],
                ["Input blocks", metrics.input_blocks],
                ["Output interventions", metrics.output_interventions],
                ["Benign utility", `${metrics.benign_completed} / ${metrics.benign_cases}`],
                [
                  "Observed released-output leaks",
                  `${metrics.observed_leaks} / ${metrics.leakage_trials}`,
                ],
                [
                  "Boundary violations",
                  `${metrics.boundary_violations} / ${metrics.boundary_checks}`,
                ],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            <details>
              <summary>Experiment methodology and limits</summary>
              <p>
                Operator-recorded observations. Physical memory erasure: <strong>UNPROVEN</strong>.
                Results cover the recorded prompts and lifecycle conditions. Signed evidence
                authenticates the included bytes.
              </p>
              <p>
                Experiment digest: <code>{report.experiment_digest}</code>
              </p>
              <p>
                Model {report.model_id} · revision {report.model_revision}
              </p>
              <p>
                Context and worker findings are original operator observations. This projection does
                not include per-trial worker IDs; inspect the separately authorized source for
                available event detail.
              </p>
            </details>
          </article>
          <h3>Supporting evidence</h3>
          <div className="proof-actions">
            <Link className="button button-primary" href={links.trace}>
              Inspect X-Ray evidence
            </Link>
            <Link className="button button-secondary" href={links.proof}>
              Inspect signed evidence
            </Link>
          </div>
          <nav className="assurance-tabs" aria-label="Model experiment findings">
            <button
              className="button"
              aria-pressed={category === "context"}
              onClick={() => setCategory("context")}
            >
              Context and recall
            </button>
            <button
              className="button"
              aria-pressed={category === "access"}
              onClick={() => setCategory("access")}
            >
              Access and lifecycle
            </button>
          </nav>
          {["context", "access"].map((group) => (
            <div key={group}>
              {" "}
              <section
                className="assurance-observations"
                hidden={category !== group}
                aria-label={
                  group === "context"
                    ? "Context and cross-session contamination"
                    : "Access and lifecycle findings"
                }
              >
                {report.observations
                  .filter((o) => contextThreats.includes(o.threat) === (group === "context"))
                  .map((o, i) => (
                    <article className="proof-verification" key={`${o.threat}-${i}`}>
                      <header>
                        <h2>
                          {o.scope === "UNPROVEN_PHYSICAL_ERASURE"
                            ? "Physical memory erasure"
                            : names[o.threat] || o.threat.replaceAll("_", " ")}
                        </h2>
                        <strong data-testid="assurance-status">{o.status}</strong>
                      </header>
                      <p>
                        {o.trials} observations · {o.violations} violations
                      </p>
                      <details>
                        <summary>Technical scope and evidence</summary>
                        <p>{o.scope.replaceAll("_", " ")}</p>
                        <p>
                          Observation digest: <code>{o.evidence_digest}</code>
                        </p>
                        {(o.evidence_evaluations ?? [])
                          .filter((id) => related(id))
                          .map((id) => (
                            <p key={id}>
                              <Link href={related(id) || links.trace}>
                                Inspect authorized recorded evaluation
                              </Link>
                            </p>
                          ))}
                      </details>
                    </article>
                  ))}
              </section>
            </div>
          ))}
        </>
      )}
    </section>
  );
}
