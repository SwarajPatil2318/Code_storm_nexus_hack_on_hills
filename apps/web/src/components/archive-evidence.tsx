"use client";
import { useState } from "react";
import Link from "next/link";
import type { components } from "@/lib/api.generated";
import { CopyValue } from "./ui";
import { useResource } from "./use-resource";
type Source = components["schemas"]["CenterSource"];
type History = components["schemas"]["ArchiveHistory"];
export function ArchiveEvidence({
  id,
  mode,
  sequence = "",
}: {
  id: string;
  mode: "trace" | "proof";
  sequence?: string;
}) {
  const source = useResource<Source>(`/assurance-center/archives/${encodeURIComponent(id)}`);
  const [cursor, setCursor] = useState(0);
  const history = useResource<History>(
    mode === "trace"
      ? `/assurance-center/archives/${encodeURIComponent(id)}/history?after=${cursor}`
      : null,
  );
  const s = source.data;
  return (
    <section className="assurance-center ac-archive">
      <p className="ac-eyebrow">
        {mode === "trace"
          ? "NEXUS X-RAY / ORIGINAL SIGNED PROJECTION"
          : "PROOF VAULT / ORIGINAL ARCHIVE"}
      </p>
      <h1>{mode === "trace" ? "Recorded evidence timeline" : "Verify the original evidence."}</h1>
      <p>
        Original source identity and bytes. Recorded history does not establish current source
        availability or full hidden completeness.
      </p>
      <Link href="/assurance-center">Return to Assurance Center</Link>
      {(source.loading || source.refreshing) && <p role="status">Checking authorized source…</p>}
      {(source.error || history.error) && (
        <p role="alert">Evidence is unavailable under this identity or cannot be verified.</p>
      )}
      {s && (
        <>
          <div className="ac-context">
            <div>
              <strong>{s.environment}</strong>
              <p>Original evaluation: {s.evaluation_id}</p>
              <p>Original snapshot: {s.snapshot_id || "Unconfirmed"}</p>
            </div>
            <div>
              <strong data-testid="archive-verification">
                {source.refreshing ? "CHECKING" : s.verification?.status || s.condition}
              </strong>
              <p>
                Signature valid: {String(s.verification?.signature_valid || false)} · Signer
                trusted: {String(s.verification?.signer_trusted || false)}
              </p>
              <p>
                {s.coverage} · {s.signed_at || "No verified signer time"}
              </p>
            </div>
          </div>
          {mode === "proof" ? (
            <>
              <p>
                Bundle SHA-256:{" "}
                <CopyValue label="bundle SHA-256" value={s.bundle_sha256 || "Unavailable"} />
              </p>
              <p>
                Receipt digest: <code>{s.receipt_digest || "Unconfirmed"}</code>
              </p>
              <p>
                Profile: {s.profile}. Original subject: {s.original_subject}. Local access requires
                a separate explicit subject/role grant.
              </p>
              <button type="button" onClick={source.reload}>
                Verify archive again
              </button>
              {s.export_url && (
                <p>
                  <a href={`/api${s.export_url}`}>Export original signed bundle</a>
                </p>
              )}
              {sequence && <p>Referenced original source event sequence: {sequence}</p>}
              {s.trace_url && <Link href={s.trace_url}>Open original X-Ray trace</Link>}
              <p>
                Independently verify the downloaded original with tools/nexus-verify and your
                separately pinned keyring. Bundled public keys alone do not establish trust. A valid
                signature does not prove host integrity or test truth.
              </p>
            </>
          ) : (
            <>
              {history.data && (
                <>
                  <p>
                    {history.data.recorded_events} recorded projection events · source watermark{" "}
                    {history.data.source_watermark}. {history.data.coverage}. This is a page of
                    original events, not a full-internal-history claim.
                  </p>
                  <ol className="ac-events">
                    {history.data.events.map((e) => (
                      <li key={e.event_id}>
                        <span>{e.timestamp}</span>
                        <strong>{e.event_type}</strong>
                        <small>
                          Source sequence {e.source_sequence} · {e.event_id}
                        </small>
                        <details>
                          <summary>Authorized metadata</summary>
                          <pre>{JSON.stringify(e.metadata, null, 2)}</pre>
                        </details>
                        <Link
                          href={`/proof-vault?archive=${encodeURIComponent(id)}&sequence=${e.source_sequence}`}
                        >
                          Inspect original signed evidence for this event
                        </Link>
                      </li>
                    ))}
                  </ol>
                  <button type="button" onClick={() => setCursor(0)} disabled={cursor === 0}>
                    First page
                  </button>{" "}
                  <button
                    type="button"
                    onClick={() => setCursor(history.data!.next_after)}
                    disabled={!history.data.has_more}
                  >
                    Next recorded page
                  </button>
                </>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
