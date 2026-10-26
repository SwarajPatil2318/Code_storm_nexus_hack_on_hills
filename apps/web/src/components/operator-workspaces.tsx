"use client";
import { resetIdentityNavigation } from "@/lib/operator-api";
import { useState } from "react";
import Link from "next/link";
import {
  Crosshair,
  Fingerprint,
  Info,
  LoaderCircle,
  LockKeyhole,
  Pencil,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Users,
} from "lucide-react";
import {
  operatorRequest,
  type Artifact,
  type Evaluation,
  type EventRecord,
  type User,
} from "@/lib/operator-api";
import { roleLabels, type Role } from "@/lib/auth-types";
import type { components } from "@/lib/api.generated";
import { useAuth } from "./auth-provider";
import { useResource } from "./use-resource";
import { AccessRestricted } from "./access-state";
import {
  Badge,
  Button,
  DataTable,
  Dialog,
  EmptyState,
  LoadingState,
  PageHeading,
  Panel,
} from "./ui";
export function ArtifactWorkspace({
  kind,
  beforeArtifacts,
  embedded = false,
}: {
  kind: "attack" | "defence";
  beforeArtifacts?: React.ReactNode;
  embedded?: boolean;
}) {
  const { session } = useAuth();
  const allowed = session.user.role === (kind === "attack" ? "RED_OPERATOR" : "BLUE_OPERATOR");
  const resource = useResource<Artifact[]>(allowed ? "/artifacts" : null);
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Artifact | null>(null);
  const [action, setAction] = useState<"read" | "rename" | "delete" | null>(null);
  const [privateContent, setPrivateContent] = useState<string | null>(null);
  if (!allowed) return <AccessRestricted />;
  const Icon = kind === "attack" ? Crosshair : ShieldCheck;
  const title = embedded
    ? kind === "attack"
      ? "Advanced attack tools"
      : "Advanced defence tools"
    : kind === "attack"
      ? "Attack Lab"
      : "Defence Vault";
  async function create(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body: components["schemas"]["ArtifactCreate"] = { name, kind, content };
      await operatorRequest<Artifact>("/artifacts", {
        method: "POST",
        csrf: session.csrf_token,
        body,
      });
      setCreateOpen(false);
      setName("");
      setContent("");
      resource.reload();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Artifact creation failed");
    } finally {
      setBusy(false);
    }
  }
  async function inspect(item: Artifact) {
    setSelected(item);
    setAction("read");
    setPrivateContent(null);
    setError("");
    setBusy(true);
    try {
      const result = await operatorRequest<{ id: string; content: string }>(
        `/artifacts/${item.id}/content`,
      );
      setPrivateContent(result.content);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Content access failed");
    } finally {
      setBusy(false);
    }
  }
  async function mutate(event?: React.SubmitEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      await operatorRequest(`/artifacts/${selected.id}`, {
        method: action === "delete" ? "DELETE" : "PATCH",
        csrf: session.csrf_token,
        body: action === "delete" ? undefined : { name },
      });
      setAction(null);
      setSelected(null);
      resource.reload();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Operation failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow={kind === "attack" ? "RED OPERATOR WORKSPACE" : "BLUE OPERATOR WORKSPACE"}
        title={title}
        description={
          kind === "attack"
            ? "Run bounded synthetic campaigns and inspect actual, authorized case outcomes."
            : "Manage your defensive artifacts with explicit ownership boundaries."
        }
        action={
          <div className="workspace-actions">
            <Link
              className="button button-primary"
              href={kind === "attack" ? "#campaign-setup" : "#blue-policy"}
            >
              {kind === "attack" ? "New evaluation" : "Author a defence policy"}
            </Link>
            <Button
              variant="secondary"
              onClick={() => {
                setName("");
                setContent("");
                setError("");
                setCreateOpen(true);
              }}
            >
              <Plus size={15} />
              Create {kind} artifact
            </Button>
          </div>
        }
      />
      <div className="feature-banner">
        <LockKeyhole size={17} />
        <span>
          Metadata and private content are scoped to your authenticated identity.{" "}
          {kind === "defence"
            ? "Sealed records restrict private content and changes, even for their owner."
            : "Blue, Auditor, and Admin roles cannot retrieve your private payloads."}{" "}
          Exact versions, Blue approval and sealing bind every evaluation. Model modes remain
          explicit.
        </span>
        <Badge tone="green">API AUTHORIZATION ACTIVE</Badge>
      </div>
      {beforeArtifacts}
      <Panel
        title={kind === "attack" ? "Your attack artifacts" : "Your defence artifacts"}
        subtitle="Real PostgreSQL records · owner-scoped private artifacts"
        action={
          <button className="icon-button" aria-label="Refresh artifacts" onClick={resource.reload}>
            <RefreshCw size={15} />
          </button>
        }
      >
        {resource.loading ? (
          <LoadingState text="Loading owned artifacts…" />
        ) : resource.error ? (
          <ResourceError message={resource.error} retry={resource.reload} />
        ) : (
          <DataTable
            columns={["Artifact", "Classification", "Created", "Access", "Actions"]}
            caption="Your authorized artifacts"
          >
            {resource.data?.length ? (
              resource.data.map((item) => (
                <tr className="artifact-row" key={item.id}>
                  <td>
                    <span className={`artifact-glyph icon-${kind === "attack" ? "red" : "green"}`}>
                      <Icon size={17} />
                    </span>
                    <span>
                      <strong>{item.name}</strong>
                      <small>{item.id.slice(0, 8)}</small>
                    </span>
                  </td>
                  <td>
                    <Badge tone={kind === "attack" ? "red" : "green"}>
                      {kind.toUpperCase()} CONFIDENTIAL
                    </Badge>
                  </td>
                  <td>{new Date(item.created_at).toLocaleDateString()}</td>
                  <td>
                    <Badge tone={item.content_restricted ? "amber" : "neutral"}>
                      {item.content_restricted ? "Content restricted" : "Owner only"}
                    </Badge>
                  </td>
                  <td>
                    <div className="row-actions">
                      <Button onClick={() => void inspect(item)}>Inspect</Button>
                      <button
                        className="icon-button"
                        aria-label={`Rename ${item.name}`}
                        onClick={() => {
                          setSelected(item);
                          setName(item.name);
                          setError("");
                          setAction("rename");
                        }}
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        className="icon-button"
                        aria-label={`Delete ${item.name}`}
                        onClick={() => {
                          setSelected(item);
                          setError("");
                          setAction("delete");
                        }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={5}>
                  <EmptyState
                    icon={Icon}
                    title={`No ${kind} artifacts yet`}
                    description="Create a private text artifact to exercise real role and ownership enforcement. This does not execute any code."
                  />
                </td>
              </tr>
            )}
          </DataTable>
        )}
      </Panel>
      <EvaluationRegistry />
      <Dialog
        open={createOpen}
        onClose={() => {
          setCreateOpen(false);
          setContent("");
        }}
        title={`Create ${kind} artifact`}
      >
        <p className="dialog-intro">
          Stored privately in the development database. Content is never added to the shared event
          timeline.
        </p>
        <form className="operator-form" onSubmit={create}>
          <label htmlFor="artifact-name">Artifact name</label>
          <input
            id="artifact-name"
            required
            maxLength={160}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <label htmlFor="artifact-content">
            Private {kind === "attack" ? "payload" : "defence content"}
          </label>
          <textarea
            id="artifact-content"
            required
            maxLength={16384}
            rows={7}
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />}Save private
            artifact
          </Button>
        </form>
      </Dialog>
      <Dialog
        open={action !== null}
        onClose={() => {
          setAction(null);
          setPrivateContent(null);
          setError("");
        }}
        title={
          action === "read"
            ? `Inspect ${selected?.name || "artifact"}`
            : action === "delete"
              ? "Delete owned artifact"
              : "Rename owned artifact"
        }
      >
        {action === "read" ? (
          <>
            {busy && <LoadingState text="Checking private-content access…" />}
            {privateContent !== null && (
              <>
                <Badge tone="amber">PRIVATE CONTENT · OWNER SESSION</Badge>
                <pre className="private-content">{privateContent}</pre>
              </>
            )}
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
          </>
        ) : action === "rename" ? (
          <form className="operator-form" onSubmit={mutate}>
            <label htmlFor="rename-artifact">Artifact name</label>
            <input
              id="rename-artifact"
              value={name}
              required
              maxLength={160}
              onChange={(e) => setName(e.target.value)}
            />
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" variant="primary" disabled={busy}>
              Save name
            </Button>
          </form>
        ) : (
          <>
            <p className="dialog-intro">
              Delete “{selected?.name}” from your artifact registry? Referenced or sealed artifacts
              cannot be deleted.
            </p>
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <Button onClick={() => void mutate()} disabled={busy}>
              <Trash2 size={15} />
              Delete artifact
            </Button>
          </>
        )}
      </Dialog>
    </>
  );
}
export function EvaluationRegistry() {
  const { session } = useAuth();
  const resource = useResource<Evaluation[]>("/evaluations");
  const [result, setResult] = useState<components["schemas"]["ResultResponse"] | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  async function view(evaluation: Evaluation) {
    setOpen(true);
    setLoading(true);
    setResult(null);
    setError("");
    try {
      setResult(await operatorRequest(`/evaluations/${evaluation.id}/result`));
    } catch (error) {
      setError(error instanceof Error ? error.message : "Results unavailable");
    } finally {
      setLoading(false);
    }
  }
  return (
    <>
      <Panel
        title="Authorized evaluations"
        subtitle="Only evaluation ownership or explicit membership grants access."
      >
        {resource.loading ? (
          <LoadingState text="Checking evaluation membership…" />
        ) : resource.error ? (
          <ResourceError message={resource.error} retry={resource.reload} />
        ) : resource.data?.length ? (
          <DataTable
            columns={["Evaluation", "Mode", "Status", "Visibility", "Result"]}
            caption="Authorized evaluation metadata"
          >
            {resource.data.map((item) => (
              <tr className="record-row" key={item.id}>
                <td>{item.name}</td>
                <td>
                  <Badge>{item.execution_mode}</Badge>
                </td>
                <td>{item.status}</td>
                <td>
                  <Badge tone={item.sealed_at ? "amber" : "neutral"}>
                    {item.sealed_at ? "Sealed record" : "Member metadata"}
                  </Badge>
                </td>
                <td>
                  {session.user.role !== "ADMIN" && (
                    <Button onClick={() => void view(item)}>View permitted result</Button>
                  )}
                </td>
              </tr>
            ))}
          </DataTable>
        ) : (
          <EmptyState
            title="No authorized evaluations"
            description="You have no evaluation memberships yet. Create and approve a versioned evaluation to begin."
          />
        )}
      </Panel>
      <Dialog open={open} onClose={() => setOpen(false)} title="Permitted result metadata">
        {loading ? (
          <LoadingState text="Checking result authorization…" />
        ) : error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : (
          result && (
            <>
              <Badge>RESULT METADATA · VERIFY SIGNED SNAPSHOTS IN PROOF VAULT</Badge>
              <pre className="code-block">{JSON.stringify(result.summary, null, 2)}</pre>
              <p className="dialog-intro">
                Only allowlisted result counters are released. Private prompts and policy rules are
                excluded.
              </p>
            </>
          )
        )}
      </Dialog>
    </>
  );
}
export function AuditTimeline({ compact = false }: { compact?: boolean }) {
  const resource = useResource<EventRecord[]>("/audit-events");
  return (
    <Panel
      title={compact ? "Application audit" : "Application audit timeline"}
      subtitle="Real authenticated API events · independent of scenario fixtures"
      action={
        <button
          className="icon-button"
          aria-label="Refresh application audit"
          onClick={resource.reload}
        >
          <RefreshCw size={15} />
        </button>
      }
    >
      {resource.loading ? (
        <LoadingState text="Loading permitted audit events…" />
      ) : resource.error ? (
        <ResourceError message={resource.error} retry={resource.reload} />
      ) : resource.data?.length ? (
        <div className="audit-timeline">
          {resource.data.slice(0, compact ? 5 : 50).map((event) => (
            <div className="audit-event" key={event.event_id}>
              <span
                className={`audit-marker ${event.event_type === "ACCESS_DENIED" ? "audit-denied" : ""}`}
              >
                <Fingerprint size={15} />
              </span>
              <div>
                <strong>{event.event_type.replaceAll("_", " ").toLowerCase()}</strong>
                <span>
                  {event.permitted_metadata.reason_code?.replaceAll("_", " ").toLowerCase()}
                </span>
                <small>
                  Correlation {event.correlation_id.slice(0, 8)} ·{" "}
                  {new Date(event.timestamp).toLocaleTimeString()}
                </small>
              </div>
              <Badge tone="green">APPLICATION</Badge>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={Fingerprint}
          title="No permitted audit events"
          description="Real authentication and application decisions will appear here. Simulated scenarios are never written to this timeline."
        />
      )}
    </Panel>
  );
}
export function AuditorWorkspace() {
  const { session } = useAuth();
  const evaluations = useResource<Evaluation[]>(
    session.user.role === "AUDITOR" ? "/evaluations" : null,
  );
  const [events, setEvents] = useState<EventRecord[] | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  if (session.user.role !== "AUDITOR") return <AccessRestricted />;
  async function inspect(id: string) {
    setLoading(true);
    setError("");
    try {
      setEvents(await operatorRequest(`/evaluations/${id}/events`));
    } catch (error) {
      setError(error instanceof Error ? error.message : "Evidence access failed");
    } finally {
      setLoading(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow="AUDITOR WORKSPACE"
        title="Evidence Inspector"
        description="Read authorized metadata. Trace application decisions."
        action={<Badge tone="blue">READ-ONLY ACCESS</Badge>}
      />
      <div className="feature-banner">
        <Info size={17} />
        <span>
          Evaluation membership is required. Only approved event metadata is released; confidential
          Red and Blue content is excluded. Signed snapshots and independent verification are
          available in Proof Vault, subject to the original evidence scope.
        </span>
      </div>
      <div className="page-stack">
        <Panel
          title="Authorized evaluation evidence"
          subtitle="Membership-scoped evidence metadata"
        >
          {evaluations.loading ? (
            <LoadingState text="Checking auditor memberships…" />
          ) : evaluations.error ? (
            <ResourceError message={evaluations.error} retry={evaluations.reload} />
          ) : evaluations.data?.length ? (
            <div className="evidence-evaluations">
              {evaluations.data.map((item) => (
                <Button key={item.id} onClick={() => void inspect(item.id)}>
                  {item.name} · inspect metadata
                </Button>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={Fingerprint}
              title="No evidence is authorized for this identity"
              description="No evaluation memberships have been assigned. No signed bundles or verification successes are fabricated."
            />
          )}
          {loading && <LoadingState text="Filtering approved evidence…" />}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          {events && <pre className="code-block">{JSON.stringify(events, null, 2)}</pre>}
        </Panel>
        <AuditTimeline />
      </div>
    </>
  );
}
export function UserManagement() {
  const { session } = useAuth();
  const allowed = session.user.role === "ADMIN";
  const resource = useResource<User[]>(allowed ? "/admin/users" : null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("RED_OPERATOR");
  if (!allowed) return <AccessRestricted />;
  async function update(user: User, body: components["schemas"]["UserUpdate"]) {
    setBusy(true);
    setError("");
    try {
      await operatorRequest(`/admin/users/${user.id}`, {
        method: "PATCH",
        csrf: session.csrf_token,
        body,
      });
      resource.reload();
      if (user.id === session.user.id) resetIdentityNavigation("/login");
    } catch (error) {
      setError(error instanceof Error ? error.message : "User update failed");
    } finally {
      setBusy(false);
    }
  }
  async function create(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body: components["schemas"]["UserCreate"] = {
        email,
        display_name: name,
        password,
        role,
      };
      await operatorRequest("/admin/users", { method: "POST", csrf: session.csrf_token, body });
      setOpen(false);
      setPassword("");
      setEmail("");
      setName("");
      resource.reload();
    } catch (error) {
      setError(error instanceof Error ? error.message : "User creation failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow="ADMINISTRATION"
        title="Operator Management"
        description="Manage application access without inheriting private evaluation payloads."
        action={
          <Button
            variant="primary"
            onClick={() => {
              setError("");
              setOpen(true);
            }}
          >
            <Plus size={15} />
            Create operator
          </Button>
        }
      />
      <div className="feature-banner">
        <ShieldCheck size={17} />
        <span>
          Changes revoke the affected user’s sessions. The final active administrator is protected.
          Administrative status never bypasses artifact ownership or confidentiality.
        </span>
      </div>
      {error && !open && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <Panel
        title="Persistent operators"
        subtitle="Passwords, session cookies, and private domain content are never returned."
      >
        {resource.loading ? (
          <LoadingState text="Checking administrator access…" />
        ) : resource.error ? (
          <ResourceError message={resource.error} retry={resource.reload} />
        ) : (
          <DataTable
            columns={["Operator", "Role", "Environment", "Account", "Action"]}
            caption="Admin operator management"
          >
            {resource.data?.map((user) => (
              <tr className="record-row" key={user.id}>
                <td>
                  <strong>{user.display_name}</strong>
                  <small>{user.email}</small>
                </td>
                <td>
                  <select
                    aria-label={`Role for ${user.email}`}
                    value={user.role}
                    disabled={busy}
                    onChange={(e) => void update(user, { role: e.target.value as Role })}
                  >
                    {(Object.keys(roleLabels) as Role[]).map((role) => (
                      <option key={role} value={role}>
                        {roleLabels[role]}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <Badge tone={user.is_demo ? "amber" : "neutral"}>
                    {user.is_demo ? "Development only" : "Standard identity"}
                  </Badge>
                </td>
                <td>
                  <Badge tone={user.is_active ? "green" : "neutral"}>
                    {user.is_active ? "Active" : "Disabled"}
                  </Badge>
                </td>
                <td>
                  <Button
                    disabled={busy}
                    onClick={() => void update(user, { is_active: !user.is_active })}
                  >
                    {user.is_active ? "Disable" : "Enable"}
                  </Button>
                </td>
              </tr>
            ))}
          </DataTable>
        )}
      </Panel>
      <div className="admin-audit">
        <AuditTimeline />
      </div>
      <Dialog
        open={open}
        onClose={() => {
          setOpen(false);
          setPassword("");
        }}
        title="Create operator"
      >
        <form className="operator-form" onSubmit={create}>
          <label htmlFor="operator-name">Display name</label>
          <input
            id="operator-name"
            required
            maxLength={120}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <label htmlFor="operator-email">Email address</label>
          <input
            id="operator-email"
            required
            type="email"
            maxLength={320}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <label htmlFor="operator-role">Operator role</label>
          <select id="operator-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(Object.keys(roleLabels) as Role[]).map((role) => (
              <option key={role} value={role}>
                {roleLabels[role]}
              </option>
            ))}
          </select>
          <label htmlFor="operator-password">Initial password (12+ characters)</label>
          <input
            id="operator-password"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            maxLength={256}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" disabled={busy}>
            <Users size={16} />
            Create authenticated identity
          </Button>
        </form>
      </Dialog>
    </>
  );
}
function ResourceError({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div className="resource-error" role="alert">
      <LockKeyhole size={21} />
      <p>{message}</p>
      <Button onClick={retry}>Try again</Button>
    </div>
  );
}
