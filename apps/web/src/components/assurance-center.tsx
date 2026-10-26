"use client";
import Link from "next/link";
import { Cpu, ScanLine, FileCheck2 } from "lucide-react";
import type { components } from "@/lib/api.generated";
import { useAuth } from "./auth-provider";
import { useResource } from "./use-resource";
export function AssuranceCenter({ initialEvaluation = "" }: { initialEvaluation?: string }) {
  const { session } = useAuth();
  const archives = useResource<components["schemas"]["CenterView"]>("/assurance-center");
  const canInvestigate = session.user.role === "RED_OPERATOR" || session.user.role === "AUDITOR";
  const context = initialEvaluation ? `?evaluation=${encodeURIComponent(initialEvaluation)}` : "";
  return (
    <section className="assurance-workspace" aria-label="Security Assurance Center">
      <header className="assurance-heading">
        <span className="eyebrow">NEXUS / SECURITY INVESTIGATIONS</span>
        <h1>Assurance Center</h1>
        <p>Explore execution records, dedicated security studies and their original evidence.</p>
      </header>
      {initialEvaluation && (
        <div className="assurance-source">
          <div>
            <span className="eyebrow">THIS EVALUATION</span>
            <code>{initialEvaluation}</code>
          </div>
          <Link href={`/evaluations/${initialEvaluation}`}>Back to evaluation</Link>
        </div>
      )}
      <div className="assurance-info-grid">
        {canInvestigate && (
          <>
            <article>
              <ScanLine />
              <h2>LLM Assurance</h2>
              <p>
                Model execution, context separation and dedicated information-leakage
                investigations.
              </p>
              <Link href={`/llm-assurance${context}`}>Explore model evidence ↗</Link>
            </article>
            <article>
              <Cpu />
              <h2>Resource Assurance</h2>
              <p>Workload budgets, recorded measurements and interference studies.</p>
              <Link href={`/resource-assurance${context}`}>Explore resource evidence ↗</Link>
            </article>
          </>
        )}
        <article>
          <FileCheck2 />
          <h2>Proof Vault</h2>
          <p>Check signed evidence and export the record available to your role.</p>
          <Link href={`/proof-vault${context}`}>Open signed evidence ↗</Link>
        </article>
      </div>
      <section className="assurance-archives">
        <h2>Original experiment archives</h2>
        <p>Historical studies retain their original evaluation and snapshot identities.</p>
        {archives.loading && <p role="status">Loading shared archives…</p>}
        {archives.error && <p role="alert">{archives.error}</p>}
        {!archives.loading && !archives.error && !archives.data?.sources.length && (
          <p>
            No historical experiment archives are shared in this environment. Current evaluation
            records are available in the workspaces above.
          </p>
        )}
        {archives.data?.sources.map((s) => {
          const findings = (archives.data?.objectives || [])
            .flatMap((o) => o.findings)
            .filter((f) => f.source_id === s.id);
          const failed = findings.some((f) => f.outcome === "FAIL");
          const model = s.methodology === "llm-assurance-v1";
          return (
            <article className="assurance-source" key={s.id}>
              <div>
                <span className="eyebrow">{s.environment} / ORIGINAL SOURCE</span>
                <h3>
                  {model
                    ? "Model-security experiment"
                    : s.methodology === "nexus-proof-bundle-v1"
                      ? "Runtime evidence"
                      : "Resource and timing experiment"}
                </h3>
                <code>{s.evaluation_id}</code>
                <p>
                  Signed {s.signed_at ? new Date(s.signed_at).toLocaleString() : "date unavailable"}
                </p>
                {failed && (
                  <p className="form-error">Original experiment includes a FAIL finding.</p>
                )}
                <details>
                  <summary>Source identity and trust</summary>
                  <p>
                    Archive {s.id} · snapshot {s.snapshot_id} ·{" "}
                    {s.verification?.status || s.condition}
                  </p>
                  <p>{s.coverage}</p>
                </details>
              </div>
              <nav>
                {canInvestigate && s.methodology !== "nexus-proof-bundle-v1" && (
                  <Link href={`/${model ? "llm" : "resource"}-assurance?archive=${s.id}`}>
                    Inspect experiment ↗
                  </Link>
                )}
                {s.trace_url && <Link href={s.trace_url}>Original X-Ray ↗</Link>}
                {s.proof_url && <Link href={s.proof_url}>Original signed evidence ↗</Link>}
              </nav>
            </article>
          );
        })}
      </section>
    </section>
  );
}
