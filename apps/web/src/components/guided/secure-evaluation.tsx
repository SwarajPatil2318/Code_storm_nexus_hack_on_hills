"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import type { components } from "@/lib/api.generated";
import { terminalStates, lifecycleLabel } from "@/lib/guided-evaluation";
import { missionMetrics } from "@/lib/live-mission";
import { scopedSecurity, recordedElapsed, type SecurityCard } from "@/lib/run-security";
import { verificationCopy, momentLabel } from "@/lib/product-clarity";
import { useAuth } from "../auth-provider";
import { useResource } from "../use-resource";
import { useXrayFeed } from "../use-xray-feed";
import { XrayTraceView, type XrayMode } from "../xray/workspace";
import { Badge, Button } from "../ui";
import { AccessRestricted } from "../access-state";
import { Layers3, Network, LockKeyhole, Route, Cpu, FileCheck2, ArrowUpRight } from "lucide-react";
import { securitySummary } from "@/lib/run-security";
import { SecurityInspector } from "./security-inspector";
type Evaluation = components["schemas"]["EvaluationResponse"];
type Manifest = components["schemas"]["ManifestResponse"];
type Report = components["schemas"]["CampaignSummary"];
type Runtime = components["schemas"]["RuntimeResponse"];
type Proof = components["schemas"]["ProofView"];
export function SecureEvaluation({ id }: { id: string }) {
  const { session } = useAuth();
  if (session.user.role === "ADMIN" || !/^([a-f0-9]{8}-)([a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id))
    return <AccessRestricted />;
  return <FocusedRun key={id} id={id} />;
}
function Elapsed({
  events,
  terminal,
}: {
  events: ReturnType<typeof useXrayFeed>["events"];
  terminal: boolean;
}) {
  const interval = recordedElapsed(events, terminal);
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (terminal) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [terminal]);
  const end = interval?.end ? Date.parse(interval.end) : terminal ? null : now;
  const seconds =
    interval && end !== null
      ? Math.max(0, Math.floor((end - Date.parse(interval.start)) / 1000))
      : null;
  return (
    <span title="From first persisted provisioning observation; wall clock is not a trusted external time source.">
      Observed interval{" "}
      <strong>
        {seconds === null ? "Not recorded" : `${Math.floor(seconds / 60)}m ${seconds % 60}s`}
      </strong>
    </span>
  );
}
function FocusedRun({ id }: { id: string }) {
  const { logout, loggingOut, session } = useAuth();
  const evaluation = useResource<Evaluation>(`/evaluations/${id}`),
    manifest = useResource<Manifest>(`/evaluations/${id}/manifest`);
  const report = useResource<Report>(
    evaluation.data?.evaluation_kind === "campaign" ? `/campaigns/${id}` : null,
  );
  const runtime = useResource<Runtime>(`/evaluations/${id}/runtime`);
  const status = report.data?.status || manifest.data?.status || evaluation.data?.status || "";
  const terminal = terminalStates.includes(status);
  const feed = useXrayFeed(id, !terminal && !!evaluation.data && !evaluation.error);
  const proof = useResource<Proof>(terminal ? `/proof/evaluations/${id}` : null);
  const [mode, setMode] = useState<XrayMode>("live"),
    [tab, setTab] = useState("execution"),
    [caseIndex, setCaseIndex] = useState("all"),
    [card, setCard] = useState<SecurityCard | null>(null),
    [logoutError, setLogoutError] = useState("");
  useEffect(() => {
    if (terminal) {
      const t = setTimeout(() => {
        setMode("replay");
        setTab("outcome");
      }, 0);
      return () => clearTimeout(t);
    }
  }, [terminal]);
  const reloadEvaluation = evaluation.reload,
    reloadManifest = manifest.reload,
    reloadReport = report.reload,
    reloadRuntime = runtime.reload;
  const canPoll = !!evaluation.data && !evaluation.error && !terminal;
  useEffect(() => {
    if (!canPoll) return;
    const t = setInterval(() => {
      reloadEvaluation();
      reloadManifest();
      reloadReport();
      reloadRuntime();
    }, 2000);
    return () => clearInterval(t);
  }, [canPoll, reloadEvaluation, reloadManifest, reloadReport, reloadRuntime]);
  const verified =
    proof.data?.evidence_status === "SIGNED" &&
    proof.data.last_verification_target === "STORED_RECEIPT" &&
    verificationCopy(proof.data.last_verification).verified &&
    proof.data.last_verification?.evaluation_id === id &&
    proof.data.receipts.some(
      (r) => r.receipt.payload.snapshot_id === proof.data?.last_verification?.snapshot_id,
    );
  const cards = scopedSecurity(
    runtime.data,
    feed.events,
    terminal,
    proof.data?.evidence_status === "SIGNED",
    !!verified,
  );
  const metrics = report.data ? missionMetrics(report.data, feed.events, terminal) : null;
  const last = feed.events.at(-1);
  const scopeId = card?.id;
  const currentCard = cards.find((c) => c.id === scopeId);
  if (evaluation.error)
    return (
      <main className="secure-page">
        <h1>Evaluation unavailable</h1>
        <p role="alert">{evaluation.error}</p>
        <p>Authenticated membership is required; this URL grants no additional access.</p>
        <Link href="/evaluations">Return to your evaluations</Link>
      </main>
    );
  if (!evaluation.data)
    return (
      <main className="secure-page">
        <p role="status">Reading authorized evaluation…</p>
      </main>
    );
  return (
    <main className="secure-page" data-testid="secure-evaluation" data-evaluation-id={id}>
      <header className="secure-header">
        <Link className="secure-brand" href="/">
          NEXUS<span> / SECURE EVALUATION</span>
        </Link>
        <nav aria-label="Focused evaluation navigation">
          <Link href={`/evaluations/${id}`}>Evaluation controls</Link>
          {session.user.role !== "BLUE_OPERATOR" && (
            <>
              <Link href={`/llm-assurance?evaluation=${id}`}>LLM Assurance</Link>
              <Link href={`/resource-assurance?evaluation=${id}`}>Resource Assurance</Link>
            </>
          )}
          <Button
            disabled={loggingOut}
            onClick={() => void logout().catch(() => setLogoutError("Sign out failed; retry."))}
          >
            Sign out
          </Button>
        </nav>
      </header>
      {logoutError && <p role="alert">{logoutError}</p>}
      <section className="secure-topline" aria-label="Evaluation identity and progress">
        <div>
          <h1>{terminal ? "Results & Security Evidence" : "Live Secure Evaluation"}</h1>
          <code>{id}</code>
          <small>
            {report.data?.provider === "local"
              ? report.data.model_manifest.model_id
              : report.data
                ? "MOCK · explicit test fixture"
                : "Reading model identity…"}
          </small>
        </div>
        <div>
          <Badge tone={status === "FAILED" ? "red" : status === "COMPLETED" ? "green" : "neutral"}>
            {lifecycleLabel(status, !!manifest.data?.blue_approved) || "Reading lifecycle"}
          </Badge>
          <Elapsed events={feed.events} terminal={terminal} />
          <span>
            {metrics?.completed ?? 0}/{report.data?.total_cases ?? "—"} case records
          </span>
        </div>
        <div className="secure-feed" role="status" data-testid="secure-connection">
          {feed.status}
          {feed.truncated ? " · INCOMPLETE PREFIX" : ""}
          <small>{feed.error || "Recorded events available to your role."}</small>
        </div>
      </section>
      {(report.error || runtime.error || manifest.error) && (
        <p role="alert">
          Some run details are unavailable: {report.error || runtime.error || manifest.error}. No
          missing observation is treated as PASS.
        </p>
      )}
      {!terminal && !["RUNNING", "PROVISIONING", "FINALIZING"].includes(status) && (
        <p className="secure-notice">
          This run has not started. Use the evaluation controls for the existing commit, Blue
          approval, seal and explicit Start actions.
        </p>
      )}
      <nav className="secure-tabs" aria-label="Secure evaluation views">
        {[
          ["execution", terminal ? "Recorded execution" : "Live execution"],
          ["security", "Security protections"],
          ["outcome", "Run outcome"],
        ].map(([key, label]) => (
          <button key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </nav>
      <div className="secure-grid" data-view={tab}>
        <section
          className="secure-execution"
          hidden={tab !== "execution"}
          aria-label="Trust-domain execution graph"
        >
          <div className="secure-boundaries">
            <span>Red human boundary · Red source stays private</span>
            <span>Blue human boundary · private Blue rules stay inside its domain</span>
          </div>
          <XrayTraceView
            evaluationId={id}
            campaign={evaluation.data.evaluation_kind === "campaign"}
            runtimeType={evaluation.data.execution_mode}
            mode={mode}
            onMode={setMode}
            caseIndex={caseIndex}
            onCaseIndex={setCaseIndex}
            feed={feed}
            report={report.data}
            runtime={runtime.data}
            compact
            detailError={report.error || runtime.error}
          />
          <p className="secure-observation" key={last?.event_id ?? "empty"}>
            {last
              ? `Latest recorded #${last.sequence}: ${momentLabel(last) || last.event_type.replaceAll("_", " ")}`
              : "No execution transition recorded yet."}
          </p>
        </section>
        <aside
          className="secure-security"
          hidden={!["execution", "security"].includes(tab)}
          aria-label="Security Behind This Run"
        >
          <h2>Security Behind This Run</h2>
          <p className="guided-meta">Recorded protections for this evaluation.</p>
          <div className="secure-cards">
            {cards.map((c) => (
              <button
                key={c.id}
                className="secure-security-card"
                data-testid={`run-${c.id}`}
                onClick={() => setCard(c)}
              >
                {(() => {
                  const Icon =
                    {
                      workloads: Layers3,
                      network: Network,
                      confidentiality: LockKeyhole,
                      gateway: Route,
                      resources: Cpu,
                      integrity: FileCheck2,
                    }[c.id] || FileCheck2;
                  return <Icon size={19} aria-hidden="true" />;
                })()}
                <strong>{c.title}</strong>
                <small>{securitySummary(c, runtime.data, feed.events)}</small>
                <span className="security-inspect">
                  Inspect <ArrowUpRight size={12} />
                </span>
              </button>
            ))}
          </div>
        </aside>
        <section
          className="secure-outcome"
          hidden={tab !== "outcome"}
          aria-label="Run outcome and next actions"
        >
          <span className="eyebrow">
            {terminal ? "NEXT · FOLLOW THE EVIDENCE" : "OBSERVATIONS SO FAR"}
          </span>
          <h2>
            {terminal
              ? "Understand the outcome, then verify the record"
              : "Execution is not finished"}
          </h2>
          <p>
            {metrics
              ? `${metrics.completed}/${report.data?.total_cases} case records · ${report.data?.runtime_errors} execution errors · ${report.data?.inconclusive} inconclusive.`
              : "No case results recorded."}{" "}
            {status === "FAILED"
              ? "This run failed; incomplete cases and cleanup uncertainty must remain visible."
              : status === "CANCELLED"
                ? "Cancelled runs do not establish successful execution."
                : ""}
          </p>
          <ol className="secure-next">
            <li>
              <Button onClick={() => setTab("execution")}>1 · Understand recorded execution</Button>
              <p>Calls, guard actions and attack criteria are separate observations.</p>
            </li>
            <li>
              <Button onClick={() => setTab("security")}>2 · Review security protections</Button>
              <p>Read actual controls, probes and their limitations.</p>
            </li>
            <li>
              <Link className="button button-primary" href={`/proof-vault?evaluation=${id}`}>
                3 · Verify signed evidence
              </Link>
              <p>
                Receipt: {proof.data?.evidence_status || "Not available yet"} ·{" "}
                {verified ? "matching trusted verification VALID" : "not verified here"}. No
                automatic signing or verification.
              </p>
            </li>
            <li>
              <Link className="button" href={`/proof-vault?evaluation=${id}`}>
                4 · Export permitted evidence
              </Link>
              <Link href={`/x-ray?evaluation=${id}`}>Open expert investigation →</Link>
            </li>
          </ol>
          <Link href={`/evaluations/${id}`}>Open case outcomes and authorized model output</Link>
        </section>
      </div>
      <footer className="secure-bottom" aria-label="Recorded evaluation measurements">
        {[
          ["Model calls started", metrics?.calls],
          ["Completed case records", metrics?.completed],
          ["Input blocks", report.data?.blocked_input],
          ["Output interventions", report.data?.output_interventions],
          [
            "Eligible attack matches",
            metrics?.eligible ? `${metrics.successes}/${metrics.eligible}` : "NOT CLASSIFIED",
          ],
          ["Inconclusive", report.data?.inconclusive],
        ].map(([label, value]) => (
          <div key={label}>
            <small>{label}</small>
            <strong>{value ?? "—"}</strong>
          </div>
        ))}
        <div>
          <small>Model sampled memory · not peak</small>
          <strong>
            {runtime.data?.snapshot?.workloads.find((w) => w.role === "model")?.memory_bytes ??
              "Not recorded"}{" "}
            bytes
          </strong>
        </div>
      </footer>
      {feed.truncated && (
        <p role="alert">
          Event-derived counters describe an incomplete prefix; no complete-state claim follows.
        </p>
      )}
      {currentCard && (
        <SecurityInspector
          key={currentCard.id}
          card={currentCard}
          evaluationId={id}
          runtime={runtime.data}
          events={feed.events}
          proof={proof.data}
          verified={!!verified}
          onClose={() => setCard(null)}
          errors={[runtime.error, ...(currentCard.id === "integrity" ? [proof.error] : [])]}
        />
      )}
    </main>
  );
}
