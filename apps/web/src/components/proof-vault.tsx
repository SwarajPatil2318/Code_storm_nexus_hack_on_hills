"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  FileCheck2,
  Fingerprint,
  Layers3,
  LockKeyhole,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { verificationCopy } from "@/lib/product-clarity";
import { InspectorDrawer, CopyValue } from "./ui";
import type { components } from "@/lib/api.generated";
import { operatorRequest } from "@/lib/operator-api";
import { useAuth } from "./auth-provider";
import { useResource } from "./use-resource";
type View = components["schemas"]["ProofView"];
type Result = components["schemas"]["Verification"];
type EventRef = components["schemas"]["Record"];
type Drawer = "receipt" | "manifest" | "chain" | "verification" | "event";
function Inspector({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
}) {
  return (
    <InspectorDrawer title={title} onClose={close} closeLabel="Close forensic inspector">
      {children}
    </InspectorDrawer>
  );
}
export function ProofVault({
  initialSequence = "",
}: {
  initialEvaluation?: string;
  initialSequence?: string;
}) {
  const { session } = useAuth();
  const index = useResource<components["schemas"]["ProofIndex"][]>("/proof/evaluations");
  const query = useSearchParams(),
    router = useRouter();
  const [receiptId, setReceiptId] = useState("");
  const eid = query.get("evaluation") || index.data?.[0]?.evaluation_id || "";
  function setChosen(value: string) {
    router.replace(
      `/proof-vault?evaluation=${encodeURIComponent(value || index.data?.[0]?.evaluation_id || "")}`,
      { scroll: false },
    );
  }
  useEffect(() => {
    if (eid && !query.get("evaluation")) {
      const next = new URLSearchParams(query);
      next.set("evaluation", eid);
      window.history.replaceState(null, "", `/proof-vault?${next}`);
    }
  }, [eid, query]);
  const resource = useResource<View>(eid ? `/proof/evaluations/${eid}` : null);
  const proof = resource.data?.evaluation_id === eid ? resource.data : null;
  const receipt = proof?.receipts.find((r) => r.id === receiptId) || proof?.receipts[0];
  const [drawer, setDrawer] = useState<Drawer | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [retrospective, setRetrospective] = useState(false);
  const [inspection, setInspection] = useState<unknown>(null),
    [inspectionError, setInspectionError] = useState("");
  const [result, setResult] = useState<Result | null>(null),
    [target, setTarget] = useState("Stored receipt");
  const file = useRef<HTMLInputElement>(null);
  const base = `/proof/evaluations/${eid}`;
  const pending = proof?.requests.some((r) => r.state === "PENDING");
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(resource.reload, 1500);
    return () => clearInterval(timer);
  }, [pending, resource.reload]);
  useEffect(() => {
    if (!drawer || !receipt) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setInspection(null);
      setInspectionError("");
      if (drawer === "manifest")
        operatorRequest<{ files: { name: string; content: string }[] }>(
          `${base}/receipts/${receipt.id}/bundle`,
          { signal: controller.signal },
        )
          .then((b) => {
            const f = b.files.find((f) => f.name === "manifest.json");
            if (!f) throw Error("Manifest missing");
            const bytes = Uint8Array.from(atob(f.content), (c) => c.charCodeAt(0));
            setInspection(JSON.parse(new TextDecoder().decode(bytes)));
          })
          .catch((e) => {
            if (!controller.signal.aborted)
              setInspectionError(e instanceof Error ? e.message : "Inspection failed");
          });
      if (drawer === "event")
        operatorRequest<EventRef>(
          `${base}/receipts/${receipt.id}/events/${Number(initialSequence)}`,
          { signal: controller.signal },
        )
          .then(setInspection)
          .catch((e) => {
            if (!controller.signal.aborted)
              setInspectionError(
                e instanceof Error ? e.message : "Event is not in this projection",
              );
          });
    }, 0);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [drawer, receipt, base, initialSequence]);
  const payload = receipt?.receipt.payload;
  const last = result || proof?.last_verification;
  const lastTarget = result
    ? target
    : proof?.last_verification_target === "SUBMITTED_BUNDLE"
      ? "Submitted bundle"
      : "Stored receipt";
  async function act(kind: "finalize" | "verify") {
    setBusy(true);
    setError("");
    try {
      if (kind === "finalize")
        await operatorRequest(`${base}/finalize`, {
          method: "POST",
          csrf: session.csrf_token,
          body: { retrospective },
        });
      else if (receipt) {
        const value = await operatorRequest<Result>(`${base}/receipts/${receipt.id}/verify`, {
          method: "POST",
          csrf: session.csrf_token,
        });
        setResult(value);
        setTarget("Stored receipt");
      }
      resource.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Evidence action failed");
    } finally {
      setBusy(false);
    }
  }
  async function upload(selected: File) {
    setError("");
    setBusy(true);
    try {
      if (selected.size > 8388608) throw Error("Evidence exceeds the 8 MiB upload limit.");
      const response = await fetch(`/api${base}/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream", "X-CSRF-Token": session.csrf_token },
        body: selected,
        credentials: "same-origin",
        signal: AbortSignal.timeout(12000),
      });
      const value = await response.json();
      if (!response.ok) throw Error(value.error?.message || "Verification request failed");
      setResult(value as Result);
      setTarget("Submitted bundle");
      resource.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Verification failed");
    } finally {
      setBusy(false);
      if (file.current) file.current.value = "";
    }
  }
  const matched =
    lastTarget === "Stored receipt" &&
    last?.evaluation_id === eid &&
    last?.snapshot_id === payload?.snapshot_id;
  const checked = lastTarget === "Submitted bundle" || matched ? last : null;
  const trust = verificationCopy(checked);
  const valid = trust.verified,
    invalid = checked?.status === "INVALID";
  return (
    <section aria-label="Proof Vault workspace" className="proof-vault" data-testid="proof-vault">
      <header className="proof-header">
        <span className="proof-brand">
          <Fingerprint size={30} />
        </span>
        <div>
          <span className="proof-eyebrow">NEXUS · EVIDENCE INTEGRITY</span>
          <h1>Proof Vault</h1>
          <p>Check whether authorized signed evidence has been altered.</p>
        </div>
        <span className="proof-header-note">
          <LockKeyhole size={15} />
          Evidence available to your role
        </span>
      </header>
      <nav className="evidence-journey" aria-label="Evidence workflow">
        <Link href={eid ? `/x-ray?evaluation=${eid}` : "/x-ray"}>01 · Inspect execution</Link>
        <span aria-current="step">02 · Verify evidence</span>
        <Link href={eid ? `/assurance-center?evaluation=${eid}` : "/assurance-center"}>
          03 · Review assurance
        </Link>
        {eid && <Link href={`/evaluations/${eid}`}>Back to evaluation</Link>}
      </nav>
      <section className="proof-selection" aria-label="Evaluation selection">
        <label htmlFor="proof-evaluation">Closed evaluation</label>
        <select
          id="proof-evaluation"
          value={eid}
          onChange={(e) => {
            setChosen(e.target.value);
            setReceiptId("");
            setResult(null);
            setRetrospective(false);
            setDrawer(null);
            setError("");
          }}
        >
          <option value="">Choose an authorized evaluation</option>
          {index.data?.map((e) => (
            <option value={e.evaluation_id} key={e.evaluation_id}>
              {e.evaluation_name} · {e.terminal_status}
            </option>
          ))}
        </select>
        <button
          onClick={() => {
            index.reload();
            resource.reload();
          }}
        >
          Refresh
        </button>
      </section>
      {(index.error || resource.error || error) && (
        <p className="proof-error" role="alert">
          {error || resource.error || index.error}
        </p>
      )}
      {index.loading && !index.data && <p role="status">Loading authorized evidence…</p>}
      {!index.loading && !index.error && !index.data?.length && (
        <div className="proof-empty">
          <Layers3 size={32} />
          <h2>No closed evidence is available</h2>
          <p>
            Complete, fail or cancel an authorized sealed evaluation first. Nothing is signed
            automatically by the browser.
          </p>
        </div>
      )}
      {proof && (
        <>
          <section className="proof-overview" aria-label="Verification overview">
            <div className="proof-overview-heading">
              <div>
                <span className="proof-eyebrow">{proof.terminal_status} EVALUATION</span>
                <h2>
                  {lastTarget === "Submitted bundle"
                    ? "Submitted file check · stored record is separate"
                    : matched && trust.verified
                      ? trust.title
                      : payload
                        ? "Evidence is signed; check its integrity"
                        : "No signed record yet"}
                </h2>
              </div>
              <span
                className={`proof-state ${proof.evidence_status === "SIGNED" ? "signed" : "warning"}`}
                data-testid="proof-signing-status"
              >
                {proof.evidence_status}
              </span>
            </div>
            <p>
              {proof.evidence_status === "UNSIGNED_LEGACY"
                ? "This evaluation predates Proof Vault. A new attestation describes only the available snapshot at signing time."
                : pending
                  ? "The trusted signer has not yet returned a receipt. No verification success is implied."
                  : payload
                    ? "A signed receipt is available. Verify it to check integrity and signer trust."
                    : "Finalization captures a closed, ordered snapshot through an explicit event watermark."}
            </p>
            <p className="clarity-lead">
              {lastTarget === "Submitted bundle"
                ? `${trust.title}. This result applies to the submitted file, not the stored record.`
                : checked
                  ? trust.detail
                  : payload
                    ? "Evidence is signed, but no matching trusted verification is available for this snapshot. Choose Verify receipt."
                    : "Finalize authorized evidence to request a signed record. Signing alone is not verification."}
            </p>
            {receipt && (
              <>
                <label htmlFor="proof-snapshot">Signed snapshot</label>
                <select
                  id="proof-snapshot"
                  value={receipt.id}
                  onChange={(e) => {
                    setReceiptId(e.target.value);
                    setResult(null);
                  }}
                >
                  {proof.receipts.map((r) => (
                    <option value={r.id} key={r.id}>
                      {r.receipt.payload.signed_at} · through #{r.watermark}
                    </option>
                  ))}
                </select>
                <CopyValue label="receipt identity" value={receipt.id} />
                <div className="proof-facts">
                  <div>
                    <span>Recorded outcome</span>
                    <strong>{payload?.terminal_status}</strong>
                  </div>
                  <div>
                    <span>Cleanup observation</span>
                    <strong>{payload?.cleanup}</strong>
                  </div>
                  <div>
                    <span>Included event count</span>
                    <strong>{payload?.chain.count}</strong>
                  </div>
                </div>
                <details className="proof-scope">
                  <summary>Included evidence and coverage</summary>
                  <p>
                    Full confidential evidence completeness:{" "}
                    <strong>not independently verified by this projection.</strong>
                  </p>
                </details>
                {receipt.watermark < proof.current_watermark && (
                  <p className="proof-warning">
                    Later records exist. This receipt remains frozen through #{receipt.watermark};
                    request a linked snapshot to include newer observations.
                  </p>
                )}
              </>
            )}
            {proof.evidence_status === "UNSIGNED_LEGACY" && (
              <label className="proof-consent">
                <input
                  type="checkbox"
                  checked={retrospective}
                  onChange={(e) => setRetrospective(e.target.checked)}
                />
                I understand retrospective signing does not establish original capture-time
                integrity.
              </label>
            )}
            {proof.requests[0]?.state === "FAILED" && (
              <p className="proof-error">
                Signing failed: {proof.requests[0].reason_code}. No receipt was fabricated.
              </p>
            )}
            <div className="proof-actions">
              <button
                className={receipt ? "" : "proof-primary"}
                disabled={
                  busy || pending || (proof.evidence_status === "UNSIGNED_LEGACY" && !retrospective)
                }
                onClick={() => void act("finalize")}
              >
                {pending
                  ? "Signing request pending"
                  : receipt
                    ? "Refresh closed snapshot"
                    : "Finalize authorized evidence"}
              </button>
              {receipt && (
                <>
                  <button
                    className="proof-primary"
                    disabled={busy}
                    onClick={() => void act("verify")}
                  >
                    <ShieldCheck size={17} />
                    Verify receipt
                  </button>
                  <button onClick={() => setDrawer("receipt")}>Inspect receipt</button>
                  <a
                    className="proof-action-link"
                    href={`/api${base}/receipts/${receipt.id}/bundle`}
                    download
                  >
                    Export authorized bundle
                  </a>
                </>
              )}
            </div>
          </section>
          <section className="proof-journey" aria-label="Evidence journey">
            {[
              { name: "Evaluation", drawer: "manifest", icon: Layers3 },
              { name: "Artifacts", drawer: "manifest", icon: Fingerprint },
              { name: "Event chain", drawer: "chain", icon: FileCheck2 },
              { name: "Signature", drawer: "receipt", icon: LockKeyhole },
              { name: "Verification", drawer: "verification", icon: ShieldCheck },
            ].map((step, i) => (
              <div key={step.name}>
                <button disabled={!receipt} onClick={() => setDrawer(step.drawer as Drawer)}>
                  <step.icon size={22} />
                  <span>{step.name}</span>
                  <small>{receipt ? "Inspect" : "Awaiting receipt"}</small>
                </button>
                {i < 4 && <ArrowRight size={16} aria-hidden="true" />}
              </div>
            ))}
          </section>
          <section className="proof-verification" aria-label="Actual verification results">
            <div>
              <span className="proof-eyebrow">{lastTarget.toUpperCase()} CHECK</span>
              <h2>{trust.title}</h2>
              <p>
                {trust.detail}{" "}
                {last && !checked
                  ? "The previous check does not match this selected snapshot."
                  : ""}
              </p>
            </div>
            <span
              className={`proof-state ${valid ? "valid" : invalid ? "invalid" : "warning"}`}
              data-testid="proof-verification-result"
            >
              {checked?.status || "NOT_VERIFIED"}
            </span>
            {lastTarget === "Submitted bundle" && (
              <p>
                The result describes the submitted file. It does not alter the stored receipt or
                declare a security incident.
              </p>
            )}
          </section>
          <section className="proof-tools">
            <div>
              <h3>Check a portable bundle</h3>
              <p>
                Submit a real file to inspect integrity failures. Canonical, uncompressed Proof
                Vault JSON only; maximum 8 MiB.
              </p>
              <label className="proof-upload">
                <Upload size={17} />
                Choose evidence bundle
                <input
                  ref={file}
                  aria-label="Evidence bundle file"
                  type="file"
                  accept=".json,application/json,application/vnd.nexus.proof+json"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void upload(f);
                  }}
                />
              </label>
            </div>
            <div>
              <h3>Follow the recorded journey</h3>
              <p>Replay describes recorded activity. Verification checks signed commitments.</p>
              <Link href={`/x-ray?evaluation=${eid}`}>
                Inspect evidence timeline <ArrowRight size={15} />
              </Link>
              {initialSequence && receipt && (
                <button onClick={() => setDrawer("event")}>
                  Inspect linked event #{initialSequence}
                </button>
              )}
            </div>
          </section>
        </>
      )}
      <details className="proof-footer">
        <summary>Cryptographic format and verification scope</summary>
        Ed25519 · SHA-256 · Canonical JSON. A trusted signature does not prove event truth, host
        integrity, model safety or successful evaluation. Independent deployment qualification
        remains partial.
      </details>
      {drawer && receipt && (
        <Inspector
          title={
            drawer === "receipt"
              ? "Signed receipt"
              : drawer === "chain"
                ? "Event chain"
                : drawer === "event"
                  ? "Signed event reference"
                  : drawer === "verification"
                    ? "Verification details"
                    : "Canonical manifest"
          }
          close={() => setDrawer(null)}
        >
          {drawer === "receipt" && (
            <>
              <p>Signing key ID</p>
              <code>{payload?.key_id}</code>
              <p>Signature input: versioned domain prefix followed by canonical receipt payload.</p>
              <pre>{JSON.stringify(receipt.receipt, null, 2)}</pre>
            </>
          )}
          {drawer === "chain" && (
            <>
              <p>
                Every included record is checked in order, together with signed counts, source
                sequences, genesis and terminal hashes. Hidden source sequence gaps are explicitly
                declared by this projection.
              </p>
              <pre>{JSON.stringify(payload?.chain, null, 2)}</pre>
            </>
          )}
          {drawer === "verification" && (
            <>
              <p>
                {lastTarget}. Signer trust comes from explicit server configuration or an
                independently obtained offline trust key.
              </p>
              <pre>{JSON.stringify(last || { status: "NOT_VERIFIED" }, null, 2)}</pre>
              <p>Receipt file commitments</p>
              <pre>{JSON.stringify(payload?.files, null, 2)}</pre>
            </>
          )}
          {(drawer === "manifest" || drawer === "event") &&
            (inspectionError ? (
              <p role="alert">{inspectionError}</p>
            ) : inspection ? (
              <pre>{JSON.stringify(inspection, null, 2)}</pre>
            ) : (
              <p role="status">Loading authorized evidence reference…</p>
            ))}
        </Inspector>
      )}
    </section>
  );
}
