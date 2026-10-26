"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import type { components } from "@/lib/api.generated";
import { operatorRequest } from "@/lib/operator-api";
import {
  boundVersion,
  ownsBinding,
  lifecycleLabel,
  record,
  type Evaluation,
  type Manifest,
  type Version,
} from "@/lib/guided-evaluation";
import { useAuth } from "../auth-provider";
import { useResource } from "../use-resource";
import { AccessRestricted } from "../access-state";
import { Badge, Button, Dialog, PageHeading, Panel } from "../ui";
import { BluePolicyWizard } from "./blue-policy-wizard";
import { WorkspacePage } from "../workspace-pages";
export function GuidedBlue() {
  const { session } = useAuth();
  return session.user.role === "BLUE_OPERATOR" ? <BlueHome /> : <AccessRestricted />;
}
function ApprovalRequest({
  evaluation,
  versions,
  onChange,
}: {
  evaluation: Evaluation;
  versions: Version[] | null;
  onChange: () => void;
}) {
  const { session } = useAuth();
  const manifest = useResource<Manifest>(`/evaluations/${evaluation.id}/manifest`);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [reject, setReject] = useState(false);
  useEffect(() => {
    if (!["CREATED", "COMMITTED"].includes(evaluation.status)) return;
    const t = setInterval(manifest.reload, 3000);
    return () => clearInterval(t);
  }, [evaluation.status, manifest.reload]);
  const data = manifest.data,
    own = ownsBinding(data, versions, "defence", session.user.id);
  const state = data?.status || evaluation.status;
  const budget = record(data?.manifest.budget),
    model = record(data?.manifest.model);
  async function act(action: "approve" | "cancel") {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await operatorRequest(`/evaluations/${evaluation.id}/${action}`, {
        method: "POST",
        csrf: session.csrf_token,
      });
      setReject(false);
      manifest.reload();
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request could not be updated.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="guided-request" data-testid="approval-request">
      <div className="guided-request-heading">
        <h3>Request {evaluation.id.slice(0, 8)}</h3>
        <Badge>{lifecycleLabel(state, Boolean(data?.blue_approved))}</Badge>
      </div>
      {manifest.loading ? (
        <p role="status">Checking exact commitments…</p>
      ) : manifest.error ? (
        <p role="alert">{manifest.error}</p>
      ) : (
        <>
          <p>
            Defence version <code>{boundVersion(data, "defence").slice(0, 12)}</code> ·{" "}
            {typeof budget.max_cases === "number"
              ? `up to ${budget.max_cases} cases`
              : "Declared size unavailable"}{" "}
            ·{" "}
            {typeof model.provider === "string" && model.provider === "local"
              ? "Real Qwen / Docker"
              : "Explicit mock configuration"}
          </p>
          <details>
            <summary>Exact version and approval scope</summary>
            <p>Sealed Red prompt text is not included in this inbox.</p>
            <p>
              Evaluation: <code>{evaluation.id}</code>
            </p>
            <p>
              Defence: <code>{boundVersion(data, "defence")}</code>
            </p>
            <p>
              Commitment: <code>{data?.manifest_digest || "Not committed yet"}</code>
            </p>
          </details>
          {state === "COMMITTED" && !data?.blue_approved && own ? (
            <div className="guided-actions">
              <Button disabled={busy} variant="primary" onClick={() => void act("approve")}>
                Approve committed test
              </Button>
              <Button disabled={busy} onClick={() => setReject(true)}>
                Reject request
              </Button>
            </div>
          ) : (
            <p>
              {state === "CREATED"
                ? "Waiting for Red to lock this test. You can review it after the attack version is committed."
                : data?.blue_approved
                  ? "Approval recorded. Red must seal and start the test."
                  : !own
                    ? "This policy belongs to another operator; only its exact owner may approve."
                    : "No approval action is currently available."}
            </p>
          )}
          <Link className="text-link" href={`/evaluations/${evaluation.id}`}>
            Inspect authorized request →
          </Link>
        </>
      )}
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      <Dialog
        open={reject}
        title="Reject and cancel this request?"
        onClose={() => setReject(false)}
      >
        <p>
          This uses the existing cancellation action. The evaluation becomes CANCELLED and cannot be
          launched. Immutable versions and history remain.
        </p>
        <Button disabled={busy} onClick={() => setReject(false)}>
          Keep request
        </Button>
        <Button disabled={busy} onClick={() => void act("cancel")}>
          Confirm rejection and cancellation
        </Button>
      </Dialog>
    </article>
  );
}
function BlueHome() {
  const { session } = useAuth();
  const evaluations = useResource<Evaluation[]>("/evaluations"),
    versions = useResource<Version[]>("/campaigns/versions"),
    artifacts = useResource<components["schemas"]["ArtifactResponse"][]>("/artifacts");
  const [commitments, setCommitments] = useState<Record<string, Manifest>>({});
  const [wizard, setWizard] = useState(false);
  const [editor, setEditor] = useState(false),
    [selected, setSelected] = useState(""),
    [email, setEmail] = useState(""),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(""),
    [error, setError] = useState("");
  const owned =
    versions.data?.filter((v) => v.kind === "defence" && v.owner_id === session.user.id) || [];
  const requests =
    evaluations.data?.filter(
      (e) => e.evaluation_kind === "campaign" && ["CREATED", "COMMITTED"].includes(e.status),
    ) || [];
  const requestKey = requests
    .slice(0, 12)
    .map((e) => `${e.id}:${e.status}`)
    .join(",");
  useEffect(() => {
    const controller = new AbortController();
    const ids = requestKey
      .split(",")
      .filter(Boolean)
      .map((v) => v.split(":")[0]);
    void Promise.all(
      ids.map(async (id) => {
        try {
          return [
            id,
            await operatorRequest<Manifest>(`/evaluations/${id}/manifest`, {
              signal: controller.signal,
            }),
          ] as const;
        } catch {
          return null;
        }
      }),
    ).then((values) => {
      if (!controller.signal.aborted)
        setCommitments(Object.fromEntries(values.filter((v) => v !== null)));
    });
    return () => controller.abort();
  }, [requestKey, evaluations.data]);
  const actionable = requests.filter(
    (e) =>
      commitments[e.id]?.status === "COMMITTED" &&
      !commitments[e.id]?.blue_approved &&
      ownsBinding(commitments[e.id], versions.data, "defence", session.user.id),
  );
  const waiting = requests.filter((e) => !actionable.includes(e));
  const policyName = (v: Version) =>
    artifacts.data?.find((a) => a.id === v.artifact_id && a.owner_id === session.user.id)?.name ||
    "Defence policy";
  useEffect(() => {
    const t = setInterval(evaluations.reload, 3000);
    return () => clearInterval(t);
  }, [evaluations.reload]);
  async function grant(e: React.SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (!owned.some((v) => v.version_id === selected))
        throw Error("Choose your owned policy version.");
      await operatorRequest(`/versions/${selected}/grants`, {
        method: "POST",
        csrf: session.csrf_token,
        body: { red_email: email },
      });
      setNotice(
        "Defence reference shared. Red may now select this exact version and request your approval.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reference sharing failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="guided-workspace">
      <PageHeading
        eyebrow="BLUE TEAM WORKSPACE"
        title="Defence Vault"
        description="Review committed tests. Keep your defence private."
        action={
          <Button
            variant="primary"
            onClick={() => {
              setWizard(true);
              setTimeout(() => {
                const section = document.getElementById("guided-blue-policy");
                section?.querySelector<HTMLElement>("h2")?.focus();
                section?.scrollIntoView({ block: "start" });
              }, 0);
            }}
          >
            Create Defence Policy
          </Button>
        }
      />
      <div id="guided-blue-policy">
        <BluePolicyWizard
          open={wizard}
          onClose={() => {
            setWizard(false);
            versions.reload();
            artifacts.reload();
          }}
          onAdvanced={() => {
            setWizard(false);
            setEditor(true);
            setTimeout(() => {
              const section = document.getElementById("defence-policy-editor");
              section?.querySelector<HTMLElement>("summary")?.focus();
              section?.scrollIntoView({ block: "start" });
            }, 0);
          }}
          onPublished={(version) => {
            versions.reload();
            artifacts.reload();
            setSelected(version.version_id);
          }}
        />
      </div>
      <Panel
        title="Evaluation approval requests"
        subtitle="Review the exact test commitment. Your approval never reveals Red's prompts."
        action={
          <Button
            onClick={() => {
              evaluations.reload();
              versions.reload();
            }}
          >
            Refresh approval inbox
          </Button>
        }
      >
        <div className="guided-form">
          <h3>Requests needing action</h3>
          {evaluations.loading ? (
            <p role="status">Reading authorized requests…</p>
          ) : evaluations.error ? (
            <p role="alert">{evaluations.error}</p>
          ) : !requests.length ? (
            <div className="guided-empty">
              <h3>No tests waiting for review</h3>
              <p>
                Share an owned defence version below. Red can then select it and request your
                approval. Requests appear here after they are created; approval requires a
                commitment.
              </p>
            </div>
          ) : (
            actionable
              .slice(0, 12)
              .map((e) => (
                <ApprovalRequest
                  key={e.id}
                  evaluation={e}
                  versions={versions.data}
                  onChange={evaluations.reload}
                />
              ))
          )}
          {!evaluations.loading && requests.length > 0 && actionable.length === 0 && (
            <p>No committed tests need your approval right now.</p>
          )}
          {requests.length > 12 && <Link href="/evaluations">View all authorized evaluations</Link>}
        </div>
      </Panel>
      {waiting.length > 0 && (
        <details className="guided-advanced">
          <summary>Waiting on Red or another owner · {waiting.length}</summary>
          <p>
            Drafts need Red to lock the attack version. Approved requests need Red to lock the
            configuration and start. A reference grant alone never approves a test.
          </p>
          {waiting.slice(0, 12).map((e) => (
            <ApprovalRequest
              key={e.id}
              evaluation={e}
              versions={versions.data}
              onChange={evaluations.reload}
            />
          ))}
        </details>
      )}
      <Panel
        title="Your defence policy versions"
        subtitle="Published versions are immutable. A reference grant and approval of a particular test are separate actions."
      >
        <div className="guided-form">
          {versions.loading ? (
            <p role="status">Reading owned policy versions…</p>
          ) : versions.error ? (
            <p role="alert">{versions.error}</p>
          ) : !owned.length ? (
            <p>
              No policy has been published by this identity. Choose Create Defence Policy to publish
              one through the existing editor.
            </p>
          ) : (
            <>
              <ul className="guided-policy-list">
                {owned.slice(0, 4).map((v) => (
                  <li key={v.version_id}>
                    <strong>
                      {policyName(v)} · {v.version_id.slice(0, 8)}
                    </strong>
                    <span>Published {new Date(v.created_at).toLocaleDateString()} · immutable</span>
                    <code>{v.sha256.slice(0, 16)}</code>
                  </li>
                ))}
              </ul>
              <form className="guided-share" onSubmit={(e) => void grant(e)}>
                <h3>Share a defence reference</h3>
                <label>
                  Defence version to share
                  <select required value={selected} onChange={(e) => setSelected(e.target.value)}>
                    <option value="">Choose your policy version</option>
                    {owned.map((v) => (
                      <option key={v.version_id} value={v.version_id}>
                        {policyName(v)} · {v.version_id.slice(0, 12)} ·{" "}
                        {new Date(v.created_at).toLocaleDateString()}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Red operator email
                  <input
                    required
                    type="email"
                    maxLength={320}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="Assigned Red identity"
                  />
                </label>
                <Button type="submit" disabled={busy}>
                  Share selected defence reference
                </Button>
              </form>
            </>
          )}
          <Button onClick={versions.reload}>Refresh owned policy versions</Button>
          {notice && <p role="status">{notice}</p>}
          {error && <p role="alert">{error}</p>}
        </div>
      </Panel>
      <details
        className="guided-advanced"
        id="defence-policy-editor"
        open={editor}
        onToggle={(e) => setEditor(e.currentTarget.open)}
      >
        <summary>Defence Policy Editor</summary>
        <p>
          Advanced private input/output rules, immutable versions, exact grants and artifact
          management. Publishing never approves a test automatically.
        </p>
        {editor && <WorkspacePage embedded kind="defence-vault" />}
      </details>
    </div>
  );
}
