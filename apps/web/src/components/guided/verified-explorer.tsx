"use client";
import { useState } from "react";
import Link from "next/link";
import type { components } from "@/lib/api.generated";
import { operatorRequest } from "@/lib/operator-api";
import type { Evaluation } from "@/lib/guided-evaluation";
import { Button } from "../ui";
export function VerifiedExplorer({ records }: { records: Evaluation[] | null }) {
  const [busy, setBusy] = useState(false),
    [chosen, setChosen] = useState<string | null>(null),
    [message, setMessage] = useState("");
  async function find() {
    if (busy) return;
    setBusy(true);
    setMessage("");
    setChosen(null);
    try {
      const candidates = (records || []).filter((e) => e.status === "COMPLETED").slice(0, 12);
      const proofs = await Promise.allSettled(
        candidates.map((e) =>
          operatorRequest<components["schemas"]["ProofView"]>(`/proof/evaluations/${e.id}`),
        ),
      );
      const found = proofs.findIndex(
        (r, i) =>
          r.status === "fulfilled" &&
          r.value.evidence_status === "SIGNED" &&
          r.value.last_verification_target === "STORED_RECEIPT" &&
          r.value.last_verification?.status === "VALID" &&
          r.value.last_verification.evaluation_id === candidates[i].id &&
          r.value.receipts.some(
            (v) => v.receipt.payload.snapshot_id === r.value.last_verification?.snapshot_id,
          ),
      );
      if (found >= 0) setChosen(candidates[found].id);
      else
        setMessage(
          "No matching stored VALID receipt was found among your 12 most recent completed evaluations. Inspect Proof Vault or the authorized historical Assurance Center.",
        );
    } catch {
      setMessage("Evidence checks are unavailable. No verification success is assumed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="guided-explore">
      <Button disabled={busy || !records} onClick={() => void find()}>
        {busy ? "Checking real stored receipts…" : "Explore a verified evaluation"}
      </Button>
      <p>Find a genuine persisted run with a recorded VALID receipt check.</p>
      {chosen && (
        <>
          <Link className="text-link" href={`/evaluations/${chosen}`}>
            Open verified evaluation {chosen.slice(0, 8)} →
          </Link>
          <small>
            The stored scoped receipt check is VALID. This is recorded evidence, not current host
            attestation.
          </small>
        </>
      )}
      {message && <p role="status">{message}</p>}
    </div>
  );
}
