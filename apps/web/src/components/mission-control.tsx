"use client";
import Link from "next/link";
import { useState } from "react";
import { VerifiedExplorer } from "./guided/verified-explorer";
import { LiveEvaluation } from "./live-evaluation";
import { ArrowUpRight, Activity, FileCheck2, Plus, RefreshCw, ShieldCheck } from "lucide-react";
import type { components } from "@/lib/api.generated";
import { useAuth } from "./auth-provider";
import { useConnectivity } from "./connectivity";
import { useResource } from "./use-resource";
import { AuditTimeline } from "./operator-workspaces";
import { Badge, EmptyState, LoadingState, PageHeading, Panel } from "./ui";
type Evaluation = components["schemas"]["EvaluationResponse"];
const words = (value: string) => value.replaceAll("_", " ").toLowerCase();
export function MissionControl() {
  const { session } = useAuth();
  const connection = useConnectivity();
  const [lifecycleOpen, setLifecycleOpen] = useState(false);
  const role = session.user.role;
  const admin = role === "ADMIN";
  const evaluations = useResource<Evaluation[]>(admin ? null : "/evaluations");
  const records = evaluations.data;
  const action =
    role === "RED_OPERATOR"
      ? ["/attack-lab", "Start a security test"]
      : role === "BLUE_OPERATOR"
        ? ["/defence-vault", "Start a security test"]
        : role === "AUDITOR"
          ? ["/evidence-inspector", "Inspect authorized evidence"]
          : ["/users", "Manage operators"];
  return (
    <div className="mission-workspace">
      <PageHeading
        eyebrow="YOUR OPERATIONAL WORKSPACE"
        title="Mission Control"
        description="Run AI security tests. Follow the results and evidence."
        action={
          <Link href={action[0]} className="button button-primary">
            <Plus size={16} />
            {action[1]}
          </Link>
        }
      />
      <section className="mission-intro" aria-label="Workspace scope">
        <div>
          <span className="mission-monogram">
            <ShieldCheck size={25} />
          </span>
          <div>
            <h2>{session.user.display_name}&apos;s workspace</h2>
            <p>
              {admin
                ? "Manage identities and environment readiness. Confidential evaluation content requires its own authorization."
                : role === "BLUE_OPERATOR"
                  ? "Author private defence policies, review exact commitments and approve permitted evaluations."
                  : role === "AUDITOR"
                    ? "Inspect evidence shared with you. Integrity, trust and test outcomes stay distinct."
                    : "Create a bounded evaluation, inspect genuine execution and verify the recorded evidence."}
            </p>
          </div>
        </div>
        <Link href="/settings" className="mission-health">
          <Badge
            tone={
              connection.status === "online"
                ? "green"
                : connection.status === "error"
                  ? "red"
                  : "neutral"
            }
            dot
          >
            API {connection.status}
          </Badge>
          <span>
            Environment diagnostics <ArrowUpRight size={13} />
          </span>
        </Link>
      </section>
      {!admin && (
        <>
          <section className="guided-launchpad" aria-label="Begin or investigate">
            <div>
              <span className="eyebrow">CREATE WITH CLEAR HANDOFFS</span>
              <h2>A prompt, a defence, an explicit approval.</h2>
              <p>
                {role === "BLUE_OPERATOR"
                  ? "Open your approval inbox or publish an immutable defence policy."
                  : role === "AUDITOR"
                    ? "Your view is read-only. Explore the evaluations and evidence shared with you."
                    : "Enter a synthetic attack without JSONL. Blue approves the exact test before you start real execution."}
              </p>
              <Link className="text-link" href={action[0]}>
                {role === "BLUE_OPERATOR" ? "Open Blue approval inbox" : action[1]} →
              </Link>
            </div>
            <VerifiedExplorer records={records || null} />
          </section>
          <Panel
            title="Recent evaluations"
            subtitle="Recent tests and their recorded outcomes."
            action={
              <button
                className="icon-button"
                aria-label="Refresh evaluations"
                onClick={evaluations.reload}
              >
                <RefreshCw size={16} />
              </button>
            }
          >
            {evaluations.loading ? (
              <LoadingState text="Reading authorized evaluations…" />
            ) : evaluations.error ? (
              <div className="resource-error" role="alert">
                <strong>Evaluation history is unavailable.</strong>
                <p>{evaluations.error}</p>
                <button className="button button-secondary" onClick={evaluations.reload}>
                  Try again
                </button>
              </div>
            ) : !records?.length ? (
              <EmptyState
                icon={Activity}
                title="Your next evaluation starts here"
                description={
                  role === "RED_OPERATOR"
                    ? "Start a security test above. Enter your prompt, choose a shared defence and request Blue approval."
                    : "No evaluation has been shared with this identity yet. Access is granted by ownership or explicit membership."
                }
              />
            ) : (
              <div className="evaluation-list">
                {records.slice(0, 4).map((e) => (
                  <article className="evaluation-row" key={e.id}>
                    <span className="evaluation-icon">
                      <Activity size={18} />
                    </span>
                    <div>
                      <h3>{role === "RED_OPERATOR" ? e.name : `Evaluation ${e.id.slice(0, 8)}`}</h3>
                      <p>
                        {e.execution_mode === "isolated_docker"
                          ? "Isolated runtime"
                          : "Explicit mock application"}{" "}
                        · {e.id.slice(0, 8)}
                      </p>
                    </div>
                    <Badge
                      tone={
                        e.status === "FAILED"
                          ? "red"
                          : e.status === "COMPLETED"
                            ? "green"
                            : "neutral"
                      }
                    >
                      {words(e.status)}
                    </Badge>
                    <div className="evaluation-links">
                      <Link href={`/evaluations/${e.id}`}>
                        Open evaluation <ArrowUpRight size={12} />
                      </Link>
                      <Link href={`/x-ray?evaluation=${e.id}`}>
                        X-Ray <ArrowUpRight size={12} />
                      </Link>
                      <Link href={`/proof-vault?evaluation=${e.id}`}>
                        Evidence <ArrowUpRight size={12} />
                      </Link>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </Panel>
          <div className="mission-paths">
            <Link href="/x-ray">
              <Activity size={20} />
              <strong>Follow an execution</strong>
              <span>Replay genuine events and inspect authorization decisions.</span>
              <ArrowUpRight size={16} />
            </Link>
            <Link href="/proof-vault">
              <FileCheck2 size={20} />
              <strong>Verify the evidence</strong>
              <span>Inspect signatures, signer trust and projection scope.</span>
              <ArrowUpRight size={16} />
            </Link>
            <Link href="/assurance-center">
              <ShieldCheck size={20} />
              <strong>Review security assurance</strong>
              <span>Model and resource investigations with original evidence.</span>
              <ArrowUpRight size={16} />
            </Link>
          </div>
          <Link className="text-link" href="/assurance-center">
            Open Assurance Center <ArrowUpRight size={14} />
          </Link>
        </>
      )}
      {!admin && (
        <details
          className="mission-advanced"
          onToggle={(e) => setLifecycleOpen(e.currentTarget.open)}
        >
          <summary>Evaluation lifecycle tools</summary>
          <p>
            Manage the existing version, approval, seal and execution flow. Model and runtime modes
            stay explicit.
          </p>
          {lifecycleOpen && (
            <>
              <LiveEvaluation />
              <AuditTimeline compact />
            </>
          )}
        </details>
      )}
      {admin && <AuditTimeline compact />}
    </div>
  );
}
