"use client";
import { useState } from "react";
import Link from "next/link";
import {
  securityDetails,
  readable,
  probeFinding,
  detailRows,
  type Detail,
  type Runtime,
  type Event,
  type Proof,
} from "@/lib/security-details";
import type { SecurityCard } from "@/lib/run-security";
import { securitySummary } from "@/lib/run-security";
import { InspectorDrawer } from "../ui";
function Rows({ rows }: { rows: Detail[] }) {
  return (
    <dl className="security-detail-values">
      {rows.map(({ label, value }) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{typeof value === "boolean" ? (value ? "Yes" : "No") : value}</dd>
        </div>
      ))}
    </dl>
  );
}
export function SecurityInspector({
  card,
  evaluationId,
  runtime,
  events,
  proof,
  verified,
  onClose,
  errors = [],
}: {
  card: SecurityCard;
  evaluationId: string;
  runtime: Runtime | null;
  events: Event[];
  proof: Proof | null;
  verified: boolean;
  onClose: () => void;
  errors?: string[];
}) {
  const data = securityDetails(card.id, evaluationId, runtime, events, proof, verified);
  const [copy, setCopy] = useState("");
  const raw = JSON.stringify(data.raw, null, 2);
  return (
    <InspectorDrawer title={card.title} closeLabel="Close security inspector" onClose={onClose}>
      <div className="security-readable" data-testid="security-readable">
        <p className="security-mechanism">{card.property}</p>
        <p>
          {securitySummary(
            card,
            runtime?.evaluation_id === evaluationId ? runtime : null,
            events.filter((e) => e.evaluation_id === evaluationId && e.origin !== "SIMULATED"),
          )}
        </p>
        <p className="security-scope">
          Evaluation <code>{evaluationId}</code>
        </p>
        {errors.filter(Boolean).map((e) => (
          <p role="alert" key={e}>
            Evidence could not be loaded: {e}
          </p>
        ))}
        {data.note && <p>{data.note}</p>}
        {data.groups.map((g) => (
          <section className="security-detail-group" key={g.title}>
            <h3>{g.title}</h3>
            <Rows rows={g.rows} />
            {g.note && <p className="muted">{g.note}</p>}
          </section>
        ))}
        {data.probes.length > 0 && (
          <section className="security-detail-group">
            <h3>Recorded checks</h3>
            {data.probes.map((p) => (
              <details className="security-check" key={p.probe_id}>
                <summary>
                  {readable(p.probe_id)}
                  <span>{probeFinding(p)}</span>
                </summary>
                <Rows
                  rows={detailRows([
                    ["From", readable(p.source)],
                    ["Target", p.target],
                    ["Expected", readable(p.expected)],
                    ["Observation", p.observed],
                    ["Measured at", p.timestamp],
                  ])}
                />
                {data.events
                  .filter((e) => e.permitted_metadata.probe_id === p.probe_id)
                  .map((e) => (
                    <p key={e.event_id} className="security-scope">
                      Trace event #{e.sequence ?? e.event_id}
                    </p>
                  ))}
              </details>
            ))}
          </section>
        )}
        {data.events.length > 0 && (
          <section className="security-detail-group">
            <h3>Supporting events</h3>
            <p>{data.events.length} matching events in the available trace.</p>
            {data.events.slice(-5).map((e) => (
              <details className="security-check" key={e.event_id}>
                <summary>
                  #{e.sequence ?? e.event_id} · {readable(e.event_type)}
                </summary>
                <Rows
                  rows={detailRows([
                    ["Time", e.timestamp],
                    ["From", readable(e.source)],
                    ["To", readable(e.destination)],
                    ["Correlation", e.correlation_id],
                    ["Decision", e.permitted_metadata.decision],
                    [
                      "Reason",
                      e.permitted_metadata.reason_code &&
                        readable(e.permitted_metadata.reason_code),
                    ],
                    [
                      "Message",
                      e.permitted_metadata.message_type &&
                        readable(e.permitted_metadata.message_type),
                    ],
                    ["Policy", e.permitted_metadata.policy_version],
                    ["Policy commitment", e.permitted_metadata.policy_digest],
                    [
                      "Runtime",
                      e.permitted_metadata.runtime_state &&
                        readable(e.permitted_metadata.runtime_state),
                    ],
                    ["Workloads present", e.permitted_metadata.workload_count],
                    [
                      "Cleanup",
                      e.permitted_metadata.cleanup_status &&
                        readable(e.permitted_metadata.cleanup_status),
                    ],
                  ])}
                />
              </details>
            ))}
          </section>
        )}
        <nav className="security-evidence-links" aria-label="Original security evidence">
          <Link href={`/x-ray?evaluation=${evaluationId}`}>Open original trace ↗</Link>
          <Link href={`/proof-vault?evaluation=${evaluationId}`}>Open Proof Vault ↗</Link>
          {card.id === "resources" && (
            <Link href={`/resource-assurance?evaluation=${evaluationId}`}>
              Inspect resource measurements ↗
            </Link>
          )}
          {card.id === "confidentiality" && (
            <Link href="/assurance-center">Review separate security experiments ↗</Link>
          )}
        </nav>
      </div>
      <details className="security-raw">
        <summary>View raw evidence</summary>
        <p>
          Authorized API projections with their original values. Signed exports are available in
          Proof Vault.
        </p>
        <button
          className="button secondary"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(raw);
              setCopy("Raw evidence copied");
            } catch {
              setCopy("Copy unavailable. Select the JSON below to copy.");
            }
          }}
        >
          Copy raw evidence
        </button>
        <span role="status">{copy}</span>
        <pre className="guided-output" data-testid="security-raw-json">
          {raw}
        </pre>
      </details>
    </InspectorDrawer>
  );
}
