"use client";
import { useState } from "react";
import { ArrowRight, Check, Copy, Info, RefreshCw } from "lucide-react";
import Link from "next/link";
import type { components } from "@/lib/api.generated";
import { useResource } from "./use-resource";
import { apiUrl } from "@/lib/api";
import { useConnectivity } from "./connectivity";
import { Badge, Button, DataTable, EmptyState, PageHeading, Panel, TextLink } from "./ui";
import { RuntimeObservatory } from "./runtime-observatory";
import { SecurityTopology } from "./security-topology";
import { ArtifactWorkspace, AuditorWorkspace } from "./operator-workspaces";
import { useAuth } from "./auth-provider";
import { roleLabels } from "@/lib/auth-types";
import { CampaignWorkbench, CampaignPolicyBuilder } from "./attack-campaign";
export function WorkspacePage({
  kind,
  embedded = false,
  judgeSuiteLoadToken = 0,
}: {
  kind: "attack-lab" | "defence-vault" | "evidence-inspector";
  embedded?: boolean;
  judgeSuiteLoadToken?: number;
}) {
  return kind === "evidence-inspector" ? (
    <AuditorWorkspace />
  ) : (
    <ArtifactWorkspace
      embedded={embedded}
      kind={kind === "attack-lab" ? "attack" : "defence"}
      beforeArtifacts={
        kind === "attack-lab" ? (
          <CampaignWorkbench judgeSuiteLoadToken={judgeSuiteLoadToken} />
        ) : (
          <CampaignPolicyBuilder />
        )
      }
    />
  );
}
export function ObservatoryPage() {
  const [simulation, setSimulation] = useState(false);
  return (
    <>
      <PageHeading
        eyebrow="RUNTIME SECURITY INSPECTION"
        title="Isolation Observatory"
        description="Inspect actual workload settings, scoped networks, security probes and cleanup."
        action={
          <Button onClick={() => setSimulation((value) => !value)}>
            {simulation ? "Inspect recorded runtime" : "Architecture scenarios"}
          </Button>
        }
      />
      {!simulation ? (
        <RuntimeObservatory />
      ) : (
        <>
          <div className="feature-banner">
            <Info size={17} />
            <span>
              This simulation illustrates the architecture. Mission Control Live mode shows actual
              application mediation. This illustration is separate from actual runtime observations,
              which are available in the recorded runtime view.
            </span>
          </div>
          <div className="page-stack">
            <Panel
              title="Illustrative communication topology"
              subtitle="Select a domain to inspect its milestone status. Pan and zoom to explore."
              action={<Badge tone="blue">DESIGN ONLY</Badge>}
            >
              <SecurityTopology />
            </Panel>
            <Panel
              title="Domain responsibilities"
              subtitle="Architecture reference; actual enforcement is established by recorded probes."
            >
              <div className="domain-table">
                <DataTable
                  columns={["Domain", "Allowed responsibility", "Protected state"]}
                  caption="Planned trust domain responsibilities"
                >
                  {[
                    [
                      "Red Team",
                      "Submit permitted adversarial requests",
                      "Attack strategies and hidden payloads",
                    ],
                    [
                      "Blue Team",
                      "Supply versioned defensive logic",
                      "Policy source and defence internals",
                    ],
                    [
                      "Client LLM",
                      "Perform controlled model inference",
                      "Ephemeral model context and caches",
                    ],
                    [
                      "Reference Monitor",
                      "Authorize and mediate cross-domain messages",
                      "Enforcement policy and broker credentials",
                    ],
                    [
                      "Auditor / Verifier",
                      "Inspect sanitized evaluation evidence",
                      "Signing keys and verification policy",
                    ],
                  ].map((row) => (
                    <tr key={row[0]}>
                      {row.map((cell) => (
                        <td key={cell}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </DataTable>
              </div>
              <div className="metadata-note">
                Shared-kernel containers do not eliminate every side channel. Stronger isolation
                requirements will be evaluated against the threat model before runtime
                implementation.
              </div>
            </Panel>
          </div>
        </>
      )}
    </>
  );
}
export function AnalyticsPage() {
  const { session } = useAuth();
  const resource = useResource<components["schemas"]["ComparisonIndex"][]>(
    session.user.role === "ADMIN" ? null : "/comparisons",
  );
  return (
    <>
      <PageHeading
        eyebrow="RECORDED COMPARISONS"
        title="Analytics"
        description="Compare matched evaluations using their actual recorded outcomes."
      />
      <Panel
        title="Authorized comparisons"
        subtitle="Separate execution arms. Exact committed inputs. No synthetic reporting data."
      >
        {resource.error ? (
          <div className="resource-error" role="alert">
            <p>{resource.error}</p>
            <Button onClick={resource.reload}>Try again</Button>
          </div>
        ) : resource.loading ? (
          <p className="loading-state" role="status">
            Reading authorized comparisons…
          </p>
        ) : resource.data?.length ? (
          <div className="evaluation-list">
            {resource.data.slice(0, 12).map((p) => (
              <article key={p.id} className="evaluation-row">
                <div>
                  <h3>{p.name}</h3>
                  <p>{p.id}</p>
                </div>
                <Link className="text-link" href={`/x-ray?comparison=${p.id}`}>
                  Inspect comparison <ArrowRight size={14} />
                </Link>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title={
              session.user.role === "ADMIN"
                ? "Evaluation content requires separate authorization"
                : "No authorized comparisons yet"
            }
            description="Matching two evaluation arms produces a recorded comparison. Administrative identity does not grant confidential content access."
          >
            <TextLink href="/">Return to Mission Control</TextLink>
          </EmptyState>
        )}
      </Panel>
    </>
  );
}
export function SettingsPage() {
  const connection = useConnectivity();
  const { session } = useAuth();
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const command =
    "cd apps/api\n../../.venv/bin/uvicorn nexus_api.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log";
  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setCopyError(false);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      setCopyError(true);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow="WORKSPACE CONFIGURATION"
        title="Settings"
        description="Inspect the environment. Know exactly what is connected."
        action={
          <Button onClick={connection.refresh} disabled={connection.checking}>
            <RefreshCw size={14} className={connection.checking ? "spin" : ""} />
            Refresh diagnostics
          </Button>
        }
      />
      <div className="page-stack">
        <Panel
          title="Service diagnostics"
          subtitle="Real responses from /health and /ready. Refreshed every 15 seconds."
          action={
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
          }
        >
          <div className="settings-diagnostics">
            <div className="diagnostic-summary" role="status">
              <p>{connection.message}</p>
            </div>
            <p className="diagnostic-time">
              {connection.checkedAt
                ? `Last checked ${connection.checkedAt.toLocaleTimeString()} (local time)`
                : "Waiting for the first health check…"}
            </p>
          </div>
          <div className="detail-list">
            <Detail label="API address">
              <code>{apiUrl}</code>
            </Detail>
            <Detail label="API version">
              <code>{connection.health?.version || "Unverified"}</code>
            </Detail>
            <Detail label="Application mode">
              <Badge tone="blue">LOCAL MOCK · APPLICATION MEDIATION</Badge>
            </Detail>
            <Detail label="Database readiness">
              <Badge tone={connection.readiness?.status === "ready" ? "green" : "neutral"}>
                {connection.readiness?.database.replaceAll("_", " ") || "Unverified"}
              </Badge>
            </Detail>
          </div>
          {connection.readinessError && (
            <p className="settings-explanation">{connection.readinessError}</p>
          )}
          {connection.readiness?.database === "unconfigured" && (
            <p className="settings-explanation">
              Set NEXUS_DATABASE_URL in apps/api/.env, then restart the API and run Alembic
              migrations.
            </p>
          )}
          {connection.readiness?.database === "unavailable" && (
            <p className="settings-explanation">
              PostgreSQL is unavailable. Check your database service, credentials, and API
              environment configuration.
            </p>
          )}
          {connection.readiness?.database === "migration_required" && (
            <p className="settings-explanation">
              Run ../../.venv/bin/alembic upgrade head from apps/api to apply the expected schema.
            </p>
          )}
          <div className="detail-list">
            <Detail label="Authenticated operator">
              <code>{session.user.email}</code>
            </Detail>
            <Detail label="Application role">
              <Badge tone="green">{roleLabels[session.user.role]}</Badge>
            </Detail>
            <Detail label="Session expiry">
              <code>
                {new Date(session.expires_at).toISOString().replace("T", " ").slice(0, 19) + " UTC"}
              </code>
            </Detail>
            <Detail label="Authentication">
              <Badge tone="green">SERVER SESSION · CSRF</Badge>
            </Detail>
          </div>
          <p className="settings-explanation">
            NEXT_PUBLIC_API_URL is configured at frontend startup or build time. Copy
            apps/web/.env.local.example to apps/web/.env.local to change it. Public variables must
            never contain credentials.
          </p>
        </Panel>
        <div className="content-grid">
          <Panel title="Local development" subtitle="Start the API from the repository root.">
            <div className="settings-diagnostics">
              <p className="diagnostic-time">
                After installing Python dependencies and configuring apps/api/.env:
              </p>
              <pre className="code-block">{command}</pre>
              <Button onClick={copy}>
                {copied ? <Check size={14} /> : <Copy size={14} />}
                {copied ? "Copied" : "Copy command"}
              </Button>
              {copyError && (
                <p className="diagnostic-time" role="status">
                  Clipboard unavailable. Select and copy the command above.
                </p>
              )}
            </div>
          </Panel>
          <Panel title="Security capabilities" subtitle="Runtime implementation status">
            <div className="detail-list">
              {["Reference Monitor", "Workload isolation", "Evidence signing"].map((item) => (
                <Detail key={item} label={item}>
                  <Badge tone={item === "Reference Monitor" ? "green" : "neutral"}>
                    {item === "Reference Monitor" ? "APPLICATION MEDIATION" : "NOT IMPLEMENTED"}
                  </Badge>
                </Detail>
              ))}
            </div>
            <div className="metadata-note">
              Authenticated domain endpoints enforce role, ownership, and membership checks.
            </div>
          </Panel>
        </div>
        <div className="callout">
          <Info size={18} />
          <p>
            Local development is a trusted developer environment. Production deployment requires
            HTTPS, production identity provisioning, secret management, and the controls documented
            in the security assumptions.
          </p>
        </div>
        <TextLink href="/">
          Return to Mission Control
          <ArrowRight size={13} />
        </TextLink>
      </div>
    </>
  );
}
function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="detail-row">
      <span>{label}</span>
      {children}
    </div>
  );
}
