"use client";
import Link from "next/link";
import type { components } from "@/lib/api.generated";
import { missionMetrics } from "@/lib/live-mission";
import { momentLabel, probeCopy } from "@/lib/product-clarity";
import { Badge, Panel } from "../ui";
type Report = components["schemas"]["CampaignSummary"];
type Event = components["schemas"]["SecurityEventResponse"];
type Runtime = components["schemas"]["RuntimeResponse"];
export function LiveMission({
  id,
  report,
  events,
  terminal,
  feedStatus,
  incomplete,
  runtime,
  approved,
  evidenceStatus,
  trustedVerification,
}: {
  id: string;
  report: Report;
  events: Event[];
  terminal: boolean;
  feedStatus: string;
  incomplete: boolean;
  runtime: Runtime | null;
  approved: boolean;
  evidenceStatus: string;
  trustedVerification: boolean;
}) {
  const m = missionMetrics(report, events, terminal);
  const last = events.at(-1),
    snapshot = runtime?.snapshot;
  const stage = last
    ? momentLabel(last) || last.event_type.replaceAll("_", " ")
    : "No execution event recorded";
  return (
    <>
      <Panel
        title={terminal ? "Recorded mission" : "Live mission"}
        subtitle="Persisted case results and authorized security events. Readiness is not inference."
        action={<Badge>{terminal ? "RECORDED REPLAY" : "LIVE"}</Badge>}
      >
        <div className="guided-form" data-testid="live-mission">
          <p>
            <strong>
              {report.provider === "local"
                ? report.model_manifest.model_id
                : "MOCK · no real inference"}
            </strong>
          </p>
          <p className="guided-meta">
            Immutable evaluation ID: <code>{id}</code>
          </p>
          <p role="status" data-testid="mission-feed">
            {feedStatus}
            {incomplete
              ? " · INCOMPLETE HISTORY: event counters describe the loaded prefix only"
              : ""}
          </p>
          <dl className="mission-counters">
            {[
              ["Scheduled cases", report.total_cases],
              ["Completed case records", m.completed],
              ["Running cases", m.running],
              [terminal ? "Unstarted / no outcome" : "Pending cases", m.pending],
              ["Execution failures", report.runtime_errors],
              ["Inference calls started · observed events", m.calls],
            ].map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          {m.progress !== null && (
            <label className="mission-progress">
              Case progress · {m.completed}/{report.total_cases} ({m.progress}%)
              <progress
                aria-label="Completed case progress"
                max={report.total_cases}
                value={m.completed}
              />
            </label>
          )}
          {m.running > 0 && (
            <p role="status">
              Case execution in progress · duration unknown. The progress bar advances only when a
              case record is persisted.
            </p>
          )}
          <p>
            Latest recorded stage: <strong>{stage}</strong>
            {last ? ` · #${last.sequence} · ${last.timestamp}` : ""}
          </p>
          <dl className="guided-facts">
            <div>
              <dt>Scored attack success · observed sample</dt>
              <dd>
                {m.eligible
                  ? `${m.successes}/${m.eligible} (${((100 * m.successes) / m.eligible).toFixed(1)}%)`
                  : "NOT TESTED · no eligible scored attacks"}
              </dd>
            </div>
            <div>
              <dt>Unsuccessful eligible attacks</dt>
              <dd>{m.eligible - m.successes}</dd>
            </div>
            <div>
              <dt>Inconclusive / not evaluated</dt>
              <dd>
                {report.inconclusive} / {report.not_evaluated}
              </dd>
            </div>
            <div>
              <dt>Input blocks / output interventions</dt>
              <dd>
                {report.blocked_input} / {report.output_interventions}
              </dd>
            </div>
            <div>
              <dt>Benign intervention rate · observed sample</dt>
              <dd>
                {m.controls
                  ? `${m.falsePositives}/${m.controls} (${((100 * m.falsePositives) / m.controls).toFixed(1)}%)`
                  : "NOT TESTED · no classified controls"}
              </dd>
            </div>
            <div>
              <dt>Model refusals</dt>
              <dd>NOT MEASURED · no refusal classifier</dd>
            </div>
          </dl>
          <details>
            <summary>Scoring denominators and category counts</summary>
            <p>
              ASR counts completed cases explicitly tagged attack-attempt in the committed v2 corpus
              with SUCCESS or FAILURE. Benign controls, unclassified legacy/custom cases, errors and
              inconclusive/unscored results are excluded. A blocked input is an unsuccessful release
              objective, not a model call. Benign intervention rate counts any input/output BLOCK or
              TRANSFORM among completed explicitly tagged controls without model errors. It measures
              guard intervention, not task fidelity. Unclassified or otherwise excluded records:{" "}
              {m.excluded}. Small samples do not establish general model safety.
            </p>
            <ul>
              {m.categories.map((c) => (
                <li key={c.category}>
                  {c.category}: {c.success}/{c.total} criterion matches
                  {c.total < 3
                    ? " · too few cases for a category rate"
                    : ` · ${((100 * c.success) / c.total).toFixed(1)}% observed`}
                </li>
              ))}
            </ul>
            <p>
              Sources: GET /campaigns/{id} (case records) and authorized GET history / WebSocket
              events. No inference count is derived from readiness or attempted cases. Chart
              omitted: the compact view uses case-count progress rather than an estimated time
              series.
            </p>
          </details>
          <div className="guided-actions">
            <Link href={`/x-ray?evaluation=${id}${terminal ? "" : "&mode=live"}`}>
              Open {terminal ? "recorded" : "live"} X-Ray →
            </Link>
            <Link href={`/proof-vault?evaluation=${id}`}>Inspect this run’s signed evidence →</Link>
          </div>
        </div>
      </Panel>
      <Panel
        title="Security behind this run"
        subtitle="Recorded workload controls and resource observations for this evaluation."
      >
        <div className="guided-form" data-testid="run-security">
          <dl className="guided-facts">
            <div>
              <dt>Signed snapshot availability</dt>
              <dd>{evidenceStatus}</dd>
            </div>
            <div>
              <dt>Trusted snapshot verification</dt>
              <dd>
                {trustedVerification
                  ? "VALID · trusted signature for this stored snapshot"
                  : "NOT VERIFIED · signing alone does not establish trust"}
              </dd>
            </div>
            <div>
              <dt>Blue exact commitment approval</dt>
              <dd>{approved ? "Recorded" : "PENDING"}</dd>
            </div>
            <div>
              <dt>Cleanup</dt>
              <dd>{snapshot?.cleanup || "PENDING"}</dd>
            </div>
            <div>
              <dt>Credential revocation</dt>
              <dd>
                {runtime?.credentials_revoked === true
                  ? "Recorded revoked"
                  : runtime?.credentials_revoked === false
                    ? "Not established"
                    : "PENDING"}
              </dd>
            </div>
            <div>
              <dt>Reference Monitor decisions · visible events</dt>
              <dd>
                {events.filter((e) => e.event_type === "POLICY_ALLOWED").length} allowed ·{" "}
                {events.filter((e) => e.event_type === "POLICY_DENIED").length} denied
                {incomplete ? " · incomplete prefix" : ""}
              </dd>
            </div>
          </dl>
          <p>Workload snapshot observed at: {runtime?.updated_at || "PENDING"}.</p>
          {!snapshot && (
            <p>
              No run-specific runtime inspection yet · PENDING. No isolation or network PASS is
              inferred.
            </p>
          )}
          {snapshot && (
            <>
              <p>
                Runtime: {snapshot.state} · host profile: {snapshot.profile.profile} · admission
                enforcement: {snapshot.isolation?.enforcement || "NOT TESTED"} · recorded queue
                wait: {snapshot.isolation?.queue_wait_ms ?? "Not recorded"} ms.
              </p>
              <div className="mission-workloads">
                {snapshot.workloads.map((w) => (
                  <details key={w.role}>
                    <summary>
                      {w.role.toUpperCase()} workload · {w.health}
                      {snapshot.cleanup === "VERIFIED" ? " · historical / removed" : ""}
                    </summary>
                    <dl className="guided-facts">
                      <div>
                        <dt>Container / scoped network</dt>
                        <dd>
                          <code>
                            {w.container_id} / {w.network_id}
                          </code>
                        </dd>
                      </div>
                      <div>
                        <dt>Immutable image</dt>
                        <dd>
                          <code>{w.image_digest}</code>
                        </dd>
                      </div>
                      <div>
                        <dt>Memory / CPU / PID limits</dt>
                        <dd>
                          {w.memory_limit} bytes / {w.cpu_limit} CPUs / {w.pids_limit} PIDs ·{" "}
                          {w.resource_profile}
                        </dd>
                      </div>
                      <div>
                        <dt>Sampled memory / CPU (not peaks)</dt>
                        <dd>
                          {w.memory_bytes ?? "Not recorded"} bytes /{" "}
                          {w.cpu_percent ?? "Not recorded"}%
                        </dd>
                      </div>
                    </dl>
                    <ul>
                      {Object.entries(w.controls).map(([name, enforced]) => (
                        <li key={name}>
                          {name}: {enforced ? "Observed enforced" : "NOT ESTABLISHED"}
                        </li>
                      ))}
                    </ul>
                  </details>
                ))}
              </div>
              <details>
                <summary>
                  Run-specific network and enforcement probes · {snapshot.probes.length} records
                </summary>
                <p>
                  Network identities above belong only to this run. Observed Reference Monitor
                  routes are in X-Ray; configured routing alone does not establish authorization.
                  Missing routes remain NOT TESTED.
                </p>
                <ul>
                  {snapshot.probes.map((p, i) => (
                    <li key={`${p.probe_id}-${i}`}>
                      <strong>{probeCopy(p).title}</strong> · {p.timestamp}
                      <details>
                        <summary>Exact observation</summary>
                        <code>{p.probe_id}</code>
                        <p>
                          Expected {p.expected}; observed {p.observed}. {p.status}
                        </p>
                      </details>
                    </li>
                  ))}
                </ul>
              </details>
            </>
          )}
          <details>
            <summary>Audit integrity and residual trust limits</summary>
            <p>
              Loaded event sequence watermark: {last?.sequence ?? "PENDING"}. Visible gaps may be
              hidden role-filtered records; feed recovery retrieves authorized history. This panel
              does not establish full confidential completeness. A signed snapshot is not
              automatically trusted verification: inspect the exact receipt and snapshot in Proof
              Vault.
            </p>
            <p>
              Shared-kernel/rootful Docker and privileged host administrators remain trusted. CPU
              partitioning does not prove exclusive host ownership; residual timing leakage remains
              possible. No historical timing result is attributed to this run. Sampled usage is not
              peak usage. No new intrusive network probes are run by this panel.
            </p>
            <Link href={`/proof-vault?evaluation=${id}`}>
              Check signature, trusted signer and snapshot coverage
            </Link>
          </details>
        </div>
      </Panel>
    </>
  );
}
