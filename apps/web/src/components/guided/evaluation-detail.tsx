"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { components } from "@/lib/api.generated";
import { operatorRequest } from "@/lib/operator-api";
import {
  boundVersion,
  lifecycleLabel,
  ownsBinding,
  record,
  terminalStates,
  type Evaluation,
  type Manifest,
  type Report,
  type Version,
} from "@/lib/guided-evaluation";
import { useAuth } from "../auth-provider";
import { useResource } from "../use-resource";
import { AccessRestricted } from "../access-state";
import { Badge, Button, Dialog, PageHeading, Panel } from "../ui";
import { CampaignMonitor } from "../attack-campaign";
import { verificationCopy } from "@/lib/product-clarity";
import { ExecutionOverview } from "./execution-overview";
import { LiveMission } from "./live-mission";
import { useXrayFeed } from "../use-xray-feed";
type Proof = components["schemas"]["ProofView"];
type Runtime = components["schemas"]["RuntimeResponse"];
export function EvaluationDetail({ id }: { id: string }) {
  const { session } = useAuth();
  if (
    session.user.role === "ADMIN" ||
    !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(id)
  )
    return <AccessRestricted />;
  return <Detail key={id} id={id} />;
}
function Detail({ id }: { id: string }) {
  const router = useRouter();
  const { session } = useAuth();
  const role = session.user.role;
  const evaluation = useResource<Evaluation>(`/evaluations/${id}`),
    manifest = useResource<Manifest>(`/evaluations/${id}/manifest`);
  const isCampaign = evaluation.data?.evaluation_kind === "campaign";
  const report = useResource<Report>(isCampaign ? `/campaigns/${id}` : null);
  const versions = useResource<Version[]>(
    role === "RED_OPERATOR" || role === "BLUE_OPERATOR" ? "/campaigns/versions" : null,
  );
  const runtime = useResource<Runtime>(isCampaign ? `/evaluations/${id}/runtime` : null);
  const status = manifest.data?.status || evaluation.data?.status || "";
  const terminal = terminalStates.includes(status);
  const feed = useXrayFeed(id, !terminal);
  const proof = useResource<Proof>(terminal ? `/proof/evaluations/${id}` : null);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [cancel, setCancel] = useState(false),
    [technical, setTechnical] = useState(false);
  const reloadEvaluation = evaluation.reload,
    reloadManifest = manifest.reload,
    reloadReport = report.reload,
    reloadRuntime = runtime.reload,
    reloadProof = proof.reload;
  const refresh = useCallback(() => {
    reloadEvaluation();
    reloadManifest();
    reloadReport();
    reloadRuntime();
    reloadProof();
  }, [reloadEvaluation, reloadManifest, reloadReport, reloadRuntime, reloadProof]);
  useEffect(() => {
    if (terminal) return;
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [terminal, refresh]);
  const red =
    role === "RED_OPERATOR" && ownsBinding(manifest.data, versions.data, "attack", session.user.id);
  const blue =
    role === "BLUE_OPERATOR" &&
    ownsBinding(manifest.data, versions.data, "defence", session.user.id);
  const approved = Boolean(manifest.data?.blue_approved),
    real = report.data?.provider === "local";
  async function mutate(action: "commit" | "approve" | "seal" | "start" | "cancel") {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await operatorRequest(`/evaluations/${id}/${action}`, {
        method: "POST",
        csrf: session.csrf_token,
      });
      setCancel(false);
      refresh();
      if (action === "start") router.push(`/evaluations/${id}/live`);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "This operation failed. Refresh the recorded state before retrying.",
      );
    } finally {
      setBusy(false);
    }
  }
  if (evaluation.error)
    return (
      <div className="resource-error" role="alert">
        <h1>Evaluation unavailable</h1>
        <p>{evaluation.error}</p>
        <p>Identity and membership are required. No private test details are shown.</p>
        <Button onClick={refresh}>Try again</Button>
        <Link href="/evaluations">Return to evaluations</Link>
      </div>
    );
  if (!evaluation.data)
    return (
      <p className="loading-state" role="status">
        Reading your authorized evaluation…
      </p>
    );
  const profile =
    typeof manifest.data?.manifest.security_profile === "string"
      ? manifest.data.manifest.security_profile
      : "Not recorded";
  const next =
    status === "CREATED"
      ? "Red must commit the exact versions to request Blue approval."
      : status === "COMMITTED" && !approved
        ? "Blue approval required. The test versions are committed; only the owning Blue operator can approve them. Red can inspect the commitment or cancel while waiting."
        : status === "COMMITTED"
          ? "Blue approval is recorded. Red must seal the approved test before launch."
          : status === "SEALED"
            ? "Ready. Only the owning Red operator can explicitly start this sealed evaluation."
            : status === "PROVISIONING"
              ? "The runtime is preparing workloads or awaiting bounded admission. No completed inference is implied by model readiness."
              : status === "RUNNING"
                ? "The existing runtime is executing the committed test. Results and recorded events update as they arrive."
                : status === "FINALIZING"
                  ? "Execution is finalizing. Wait for the recorded outcome and cleanup checks."
                  : terminal
                    ? "Inspect the recorded results and cleanup, then verify the corresponding evidence."
                    : "Recorded state is unavailable. Refresh before attempting any action.";
  const action =
    red && status === "CREATED"
      ? { label: "Request Blue approval", value: "commit" as const }
      : blue && status === "COMMITTED" && !approved
        ? { label: "Approve committed test", value: "approve" as const }
        : red && status === "COMMITTED" && approved
          ? { label: "Seal approved test", value: "seal" as const }
          : red && status === "SEALED"
            ? {
                label: real ? "Start real evaluation" : "Start explicitly mocked evaluation",
                value: "start" as const,
              }
            : null;
  const verified =
    proof.data?.evidence_status === "SIGNED" &&
    proof.data.last_verification_target === "STORED_RECEIPT" &&
    verificationCopy(proof.data.last_verification).verified &&
    proof.data.last_verification?.evaluation_id === id &&
    proof.data.receipts.some(
      (r) => r.receipt.payload.snapshot_id === proof.data?.last_verification?.snapshot_id,
    );
  return (
    <div className="guided-workspace" data-testid="evaluation-detail" data-evaluation-id={id}>
      <PageHeading
        eyebrow={`EVALUATION · ${id.slice(0, 8)}`}
        title={role === "RED_OPERATOR" ? evaluation.data.name : `Evaluation ${id.slice(0, 8)}`}
        description="See the outcome, follow the next action, then inspect the evidence."
        action={
          <Badge tone={status === "FAILED" ? "red" : status === "COMPLETED" ? "green" : "neutral"}>
            {lifecycleLabel(status, approved)}
          </Badge>
        }
      />
      <Panel
        title={
          status === "COMMITTED" && !approved
            ? "Waiting for Blue Team approval"
            : lifecycleLabel(status, approved) || "Reading lifecycle"
        }
        subtitle={next}
      >
        <div className="guided-form">
          <p className="guided-identity">
            {report.data
              ? real
                ? "Real Qwen inference · restricted Docker"
                : "MOCK · explicit deterministic reproduction"
              : "Reading committed model identity…"}{" "}
            · Profile: {profile.replaceAll("_", " ")}
          </p>
          {manifest.error && <p role="alert">{manifest.error}</p>}
          {report.error && <p role="alert">{report.error}</p>}
          {error && (
            <p role="alert" className="form-error">
              {error}
            </p>
          )}
          <div className="guided-actions">
            {action && isCampaign && (
              <Button
                disabled={busy || !manifest.data || !report.data}
                variant="primary"
                onClick={() => void mutate(action.value)}
              >
                {busy ? "Updating recorded state…" : action.label}
              </Button>
            )}
            <Button onClick={refresh}>Refresh evaluation</Button>
            {!terminal && (red || blue) && (
              <Button disabled={busy} onClick={() => setCancel(true)}>
                {blue && status === "COMMITTED" && !approved
                  ? "Reject request"
                  : "Cancel evaluation"}
              </Button>
            )}
          </div>
          {!action && !terminal && (
            <p>
              {role === "AUDITOR"
                ? "Auditor access is read-only."
                : status === "COMMITTED" && !approved && red
                  ? "Keep your Red session open. Ask Blue to open Defence Vault → Evaluation approval requests in a separate session."
                  : "The next action belongs to the authorized owner or the running system."}
            </p>
          )}
          {!isCampaign && (
            <p>
              This is a legacy evaluation. Its authorized trace and evidence remain available
              through the links below; the guided campaign controls do not apply.
            </p>
          )}
        </div>
      </Panel>
      {isCampaign && report.data && (
        <LiveMission
          id={id}
          report={report.data}
          events={feed.events}
          terminal={terminal}
          feedStatus={feed.status}
          incomplete={feed.truncated}
          runtime={runtime.data}
          approved={approved}
          evidenceStatus={
            proof.data?.evidence_status ||
            (terminal
              ? "PENDING · reading authorized receipt status"
              : "Not finalized while evaluation is active")
          }
          trustedVerification={verified}
        />
      )}
      {isCampaign && (
        <Panel
          title="What happened?"
          subtitle={
            terminal
              ? "Recorded results from this test. Each outcome has a separate meaning."
              : "Results appear only after actual execution."
          }
        >
          <div className="guided-form">
            <p className="clarity-lead">
              {report.data?.measured_cases
                ? `${report.data.measured_cases} of ${report.data.total_cases} cases have outcomes. ${report.data.success} met their declared response criterion; ${report.data.failure} did not.${report.data.inconclusive ? ` ${report.data.inconclusive} INCONCLUSIVE.` : ""}${report.data.not_evaluated ? ` ${report.data.not_evaluated} not evaluated.` : ""}`
                : "No attack outcome is recorded yet. Follow the next action above."}
            </p>
            <dl className="guided-facts clarity-outcomes">
              <div>
                <dt>AI attack outcome</dt>
                <dd>
                  {report.data?.measured_cases
                    ? `${report.data.success} criterion matches · ${report.data.failure} failures · ${report.data.inconclusive} INCONCLUSIVE`
                    : "Not evaluated"}
                </dd>
              </div>
              <div>
                <dt>Blue defence action</dt>
                <dd>
                  {report.data?.measured_cases
                    ? `${report.data.blocked_input} inputs blocked · ${report.data.output_interventions} output interventions`
                    : "Not recorded"}
                </dd>
              </div>
              <div>
                <dt>Infrastructure execution</dt>
                <dd>
                  {lifecycleLabel(status, approved)}
                  {report.data ? ` · ${report.data.runtime_errors} case errors` : ""}
                </dd>
              </div>
              <div>
                <dt>Cleanup result</dt>
                <dd>
                  {runtime.data?.snapshot?.cleanup === "VERIFIED"
                    ? "Safely cleaned up · verified teardown"
                    : runtime.data?.snapshot?.cleanup || "Not recorded"}
                </dd>
              </div>
              <div>
                <dt>Signed record</dt>
                <dd>
                  {proof.data?.evidence_status ||
                    (terminal ? "Not available yet" : "Available after the test closes")}
                </dd>
              </div>
              <div>
                <dt>Evidence verification</dt>
                <dd>
                  {verified
                    ? "Stored evidence integrity verified"
                    : "Stored evidence not verified here"}
                </dd>
              </div>
            </dl>
            <p className="guided-meta">
              Task results, defence actions and infrastructure outcomes are shown separately.
            </p>
            <details>
              <summary>How to interpret outcomes</summary>
              <p>
                Criterion matches include ordinary controls such as arithmetic; they do not by
                themselves establish a security compromise. Completion, defence actions, cleanup and
                signature checks are separate.
              </p>
            </details>
          </div>
        </Panel>
      )}
      <nav className="guided-destinations" aria-label="Investigate this evaluation">
        <Link href={`/x-ray?evaluation=${id}`}>Explore in X-Ray →</Link>
        <Link href={`/proof-vault?evaluation=${id}`}>Inspect Proof Vault →</Link>
        {(red || role === "AUDITOR") && (
          <>
            <Link href={`/llm-assurance?evaluation=${id}`}>LLM Assurance →</Link>
            <Link href={`/resource-assurance?evaluation=${id}`}>Resource Assurance →</Link>
          </>
        )}
      </nav>
      <details className="guided-advanced">
        <summary>Case results and authorized model output</summary>
        {isCampaign && (
          <Panel
            title={terminal ? "Recorded results" : "Results as they arrive"}
            subtitle="Model execution, defence decisions, scoring, infrastructure and signature verification are separate observations."
          >
            <div className="guided-form">
              {!report.data?.cases.length ? (
                <p>No case outcomes have been recorded yet.</p>
              ) : (
                <div className="guided-results">
                  {report.data.cases.map((c) => (
                    <article key={c.correlation_id} className="guided-case-result">
                      <h3>
                        {red ? c.title || `Case ${c.case_index + 1}` : `Case ${c.case_index + 1}`}
                      </h3>
                      <dl className="guided-facts">
                        <div>
                          <dt>Did the AI execute this case?</dt>
                          <dd>
                            {c.model_execution === "EXECUTED"
                              ? real
                                ? "Yes · real model EXECUTED"
                                : "MOCK executed · not real inference"
                              : c.model_execution === "SKIPPED"
                                ? "No · model SKIPPED"
                                : c.model_execution}
                          </dd>
                        </div>
                        <div>
                          <dt>Blue input / output defence</dt>
                          <dd>
                            {c.input_action || "Not recorded"} / {c.output_action || "Not recorded"}
                          </dd>
                        </div>
                        <div>
                          <dt>Attack criterion outcome</dt>
                          <dd>{c.attack_outcome}</dd>
                        </div>
                        <div>
                          <dt>Infrastructure case error</dt>
                          <dd>{c.error_code || "No case error recorded"}</dd>
                        </div>
                      </dl>
                      {red && (
                        <>
                          <h4>Authorized observable output</h4>
                          <pre className="guided-output">
                            {c.released_output ?? "No output was released."}
                          </pre>
                          <p>{c.scoring_explanation}</p>
                        </>
                      )}
                      <p className="guided-meta">
                        Prompt tokens: {c.prompt_tokens ?? "Not recorded"} · Generated tokens:{" "}
                        {c.completion_tokens ?? "Not recorded"} ·{" "}
                        {c.inference_ms === null
                          ? "Inference duration not recorded"
                          : `${c.inference_ms} ms recorded inference`}
                      </p>
                    </article>
                  ))}
                </div>
              )}
              <div className="guided-result-foot">
                <p>
                  <strong>Infrastructure:</strong> {lifecycleLabel(status, approved)} · Cleanup{" "}
                  {runtime.data?.snapshot?.cleanup || "Not recorded"}
                  {runtime.error ? " · runtime observations unavailable" : ""}
                </p>
                <p>
                  <strong>Evidence:</strong>{" "}
                  {proof.error
                    ? "Evidence unavailable for this identity"
                    : !terminal
                      ? "Not finalized while evaluation is active"
                      : proof.loading
                        ? "Reading receipt status…"
                        : proof.data?.evidence_status || "Not available"}{" "}
                  ·{" "}
                  {verified
                    ? "Last stored receipt check VALID"
                    : proof.data?.last_verification
                      ? `${proof.data.last_verification_target === "SUBMITTED_BUNDLE" ? "Submitted bundle" : "Unmatched receipt"} check ${proof.data.last_verification.status} · stored snapshot not verified here`
                      : "Not independently verified here"}
                </p>
                <p>
                  Criterion SUCCESS is not a universal safety score. A skipped case, execution
                  failure or valid signature must not be interpreted as the same outcome. Hidden
                  confidential completeness and host integrity remain unproven.
                </p>
              </div>
            </div>
          </Panel>
        )}
      </details>
      {isCampaign && (
        <ExecutionOverview
          id={id}
          live={!terminal}
          profile={profile}
          runtime={runtime.data}
          real={report.data ? real : null}
          feed={feed}
        />
      )}
      <details
        className="guided-advanced"
        open={technical}
        onToggle={(e) => setTechnical(e.currentTarget.open)}
      >
        <summary>Technical commitments and expert controls</summary>
        <div className="guided-form">
          <dl className="guided-facts">
            <div>
              <dt>Backend lifecycle state</dt>
              <dd>{status}</dd>
            </div>
            <div>
              <dt>Evaluation ID</dt>
              <dd>
                <code>{id}</code>
              </dd>
            </div>
            <div>
              <dt>Defence version</dt>
              <dd>
                <code>{boundVersion(manifest.data, "defence") || "Not recorded"}</code>
              </dd>
            </div>
            <div>
              <dt>Manifest commitment</dt>
              <dd>
                <code>{manifest.data?.manifest_digest || "Not committed"}</code>
              </dd>
            </div>
          </dl>
          <p>Shared model/resource requirements:</p>
          <pre className="guided-output">
            {JSON.stringify(
              {
                model: record(manifest.data?.manifest.model),
                budget: record(manifest.data?.manifest.budget),
              },
              null,
              2,
            )}
          </pre>
        </div>
        {technical && isCampaign && <CampaignMonitor evaluationId={id} />}
      </details>
      <Dialog open={cancel} onClose={() => setCancel(false)} title="Cancel this evaluation?">
        <p>
          This records CANCELLED through the existing authorized lifecycle. It does not delete
          immutable artifacts or signed history. Interrupted cleanup can remain uncertain; inspect
          the actual runtime outcome.
        </p>
        <Button onClick={() => setCancel(false)}>Keep evaluation</Button>
        <Button disabled={busy} onClick={() => void mutate("cancel")}>
          Confirm cancellation
        </Button>
      </Dialog>
    </div>
  );
}
