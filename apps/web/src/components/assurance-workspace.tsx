"use client";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect } from "react";
import { Cpu, Layers3, Fingerprint, ScanLine } from "lucide-react";
import type { components } from "@/lib/api.generated";
import { useResource } from "./use-resource";
import { LLMExperiment } from "./llm-assurance";
import { ResourceExperiment } from "./resource-assurance";
import { Button } from "./ui";
type RecordView = components["schemas"]["AssuranceRecord"];
type Archived = components["schemas"]["ArchivedExperiment"];
type Runtime = components["schemas"]["RuntimeResponse"];
type Model = components["schemas"]["ModelManifest"];
type View = components["schemas"]["AssuranceView"] | components["schemas"]["ResourceView"];
const date = (value?: string | null) =>
  value ? new Date(value).toLocaleString() : "Date not recorded";
const words = (value?: string | null) => value?.replaceAll("_", " ") || "Not recorded";
export function AssuranceWorkspace({ kind }: { kind: "model" | "resource" }) {
  const query = useSearchParams(),
    router = useRouter();
  const path = kind === "model" ? "/llm-assurance" : "/resource-assurance";
  const endpoint = kind === "model" ? "/assurance" : "/resource-assurance";
  const index = useResource<RecordView[]>(`${endpoint}/evaluations`);
  const archives = useResource<components["schemas"]["CenterView"]>("/assurance-center");
  const experimentsOnly = query.get("context") === "experiments";
  const local = (index.data || []).filter(
    (r) => !experimentsOnly || r.record_kind === "EXPERIMENT",
  );
  const historical = (archives.data?.sources || []).filter((s) =>
    kind === "model"
      ? s.methodology === "llm-assurance-v1"
      : ["resource-assurance-v1", "m101-randomized-heldout-v1", "timing-mitigation-v1"].includes(
          s.methodology || "",
        ),
  );
  const options = [
    ...local.map((r) => ({
      key: `evaluation:${r.evaluation_id}`,
      label: `${r.name} · ${r.model_id} · ${date(r.created_at)} · ${r.record_kind === "EXPERIMENT" ? "Dedicated experiment" : "Evaluation runtime evidence"}`,
      date: r.created_at,
    })),
    ...historical.map((s) => ({
      key: `archive:${s.id}`,
      label: `${s.environment} experiment · Qwen2.5-0.5B · signed ${date(s.signed_at)} · ${s.condition === "AVAILABLE" ? "Verified archive" : words(s.condition)} · ${s.evaluation_id.slice(0, 8)}`,
      date: s.signed_at || "",
    })),
  ].sort((a, b) => Date.parse(b.date || "1970-01-01") - Date.parse(a.date || "1970-01-01"));
  const target = query.get("archive")
    ? `archive:${query.get("archive")}`
    : query.get("evaluation")
      ? `evaluation:${query.get("evaluation")}`
      : index.loading || archives.loading
        ? ""
        : options[0]?.key || "";
  const [scope, id = ""] = target.split(":");
  useEffect(() => {
    if (
      !target ||
      query.get("evaluation") ||
      query.get("archive") ||
      index.loading ||
      archives.loading
    )
      return;
    const params = new URLSearchParams();
    if (experimentsOnly) params.set("context", "experiments");
    params.set(scope, id);
    router.replace(`${path}?${params}`, { scroll: false });
  }, [target, query, index.loading, archives.loading, experimentsOnly, scope, id, router, path]);

  const selected = (index.data || []).find((r) => r.evaluation_id === id);
  const detail = useResource<View>(
    scope === "evaluation" && id ? `${endpoint}/evaluations/${encodeURIComponent(id)}` : null,
  );
  const archive = useResource<Archived>(
    scope === "archive" && id ? `/assurance-center/experiments/${encodeURIComponent(id)}` : null,
  );
  const current = detail.data?.evaluation_id === id ? detail.data : null;
  const original = archive.data?.source.id === id ? archive.data : null;
  const report =
    original?.assurance_report ||
    (current && "report" in current && current.report && "metrics" in current.report
      ? current.report
      : null);
  const resource =
    original?.resource_report ||
    (current && "report" in current && current.report && "baseline" in current.report
      ? current.report
      : null);
  const timing =
    original?.timing_report ||
    (current && "timing_report" in current ? current.timing_report : null);
  const source = original?.source;
  const trace = source?.trace_url || `/x-ray?evaluation=${id}`;
  const proof = source?.proof_url || `/proof-vault?evaluation=${id}`;
  const related = (eid: string) =>
    source
      ? original?.related_sources?.find((s) => s.evaluation_id === eid)?.trace_url || null
      : `/x-ray?evaluation=${eid}`;
  function navigate(key: string, experiments = experimentsOnly) {
    const [type, value] = key.split(":");
    const params = new URLSearchParams();
    if (experiments) params.set("context", "experiments");
    if (value) params.set(type, value);
    router.replace(`${path}${params.size ? `?${params}` : ""}`, { scroll: false });
  }
  const loading = index.loading || archives.loading || detail.loading || archive.loading;
  const error = detail.error || archive.error;
  return (
    <section
      className="assurance-workspace"
      data-testid={`${kind}-assurance-workspace`}
      data-evaluation-id={scope === "evaluation" ? id : source?.evaluation_id || ""}
    >
      <header className="assurance-heading">
        <span className="eyebrow">
          NEXUS / {kind === "model" ? "MODEL SECURITY" : "COMPUTE INTELLIGENCE"}
        </span>
        <h1>{kind === "model" ? "LLM Assurance" : "Resource Assurance"}</h1>
        <p>
          {kind === "model"
            ? "Explore how NEXUS protects model execution and investigates context leakage."
            : "Understand how NEXUS manages compute resources and measures interference during secure evaluations."}
        </p>
      </header>
      <nav className="assurance-tabs" aria-label="Assurance evidence scope">
        <Button
          variant={!experimentsOnly ? "primary" : "secondary"}
          onClick={() => navigate("", false)}
        >
          Evaluation records
        </Button>
        <Button
          variant={experimentsOnly ? "primary" : "secondary"}
          onClick={() => navigate("", true)}
        >
          {kind === "model" ? "Model Security Experiments" : "Resource Experiments"}
        </Button>
      </nav>
      <div className="assurance-selector">
        <label>
          {kind === "model" ? "Model evidence" : "Resource evidence"}
          <select
            aria-label={kind === "model" ? "Assurance evaluation" : "Resource assurance evaluation"}
            value={target}
            onChange={(e) => navigate(e.target.value)}
          >
            <option value="">Choose authorized evidence</option>
            {target && !options.some((o) => o.key === target) && (
              <option value={target}>Requested record · {id.slice(0, 8)}</option>
            )}
            {options.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <Button
          onClick={() => {
            index.reload();
            archives.reload();
            detail.reload();
            archive.reload();
          }}
        >
          Refresh evidence
        </Button>
      </div>
      {(index.error || archives.error) && (
        <p role="alert">
          {index.error || archives.error}{" "}
          <Button
            onClick={() => {
              index.reload();
              archives.reload();
            }}
          >
            Retry discovery
          </Button>
        </p>
      )}
      {loading && <p role="status">Loading authorized evidence…</p>}
      {error && (
        <div className="assurance-empty" role="alert">
          <h2>Evidence unavailable</h2>
          <p>{error}</p>
          <p>Select another authorized record or refresh to try again.</p>
          <Button onClick={() => navigate("")}>Choose another record</Button>
        </div>
      )}
      {!loading && !target && (
        <div className="assurance-empty">
          <Layers3 />
          <h2>
            {experimentsOnly
              ? "No dedicated experiments shared here"
              : "No compatible records available"}
          </h2>
          <p>
            {experimentsOnly
              ? "Dedicated studies keep their original identities and access grants. Evaluation runtime records remain available in Evaluation records."
              : "Complete an authorized Qwen evaluation to inspect its model and resource records."}
          </p>
          <Link href={experimentsOnly ? path : "/evaluations"}>
            {experimentsOnly ? "View evaluation records" : "Open evaluations"}
          </Link>
        </div>
      )}
      {(current || original) && (
        <>
          <div className="assurance-source" aria-label="Selected evidence identity">
            <div>
              <span className="eyebrow">
                {source
                  ? `ORIGINAL SECURITY EXPERIMENT · ${source.environment}`
                  : selected?.record_kind === "EXPERIMENT"
                    ? "DEDICATED EXPERIMENT"
                    : "THIS EVALUATION"}
              </span>
              <h2>
                {source
                  ? `${source.environment} · original experiment`
                  : selected?.name || "Authorized evaluation"}
              </h2>
              <code>{source?.evaluation_id || id}</code>
              <p>
                {source
                  ? `Signed ${date(source.signed_at)} · original snapshot ${source.snapshot_id}`
                  : `Created ${date(selected?.created_at)} · ${words(current?.state)}`}
              </p>
            </div>
            <nav>
              <Link href={trace}>Open X-Ray ↗</Link>
              <Link href={proof}>Open Proof Vault ↗</Link>
              {!source && (
                <>
                  <Link href={`/evaluations/${id}`}>Evaluation details ↗</Link>
                  <Link href={`/isolation-observatory?evaluation=${id}`}>
                    Isolation Observatory ↗
                  </Link>
                </>
              )}
            </nav>
          </div>
          {current?.runtime?.snapshot && (
            <RuntimeEvidence kind={kind} runtime={current.runtime} model={current.model || null} />
          )}
          {source && (
            <details className="assurance-details">
              <summary>Original source and verification</summary>
              <p>
                Archive {source.id} · {source.verification?.status} · {source.coverage}
              </p>
              <p>
                Methodology {source.methodology}. Operator attestation; original findings and trust
                scope are retained.
              </p>
            </details>
          )}
          {kind === "model" && report && (
            <LLMExperiment
              report={report}
              evaluationId={source?.evaluation_id || id}
              links={{ trace, proof }}
              related={related}
            />
          )}
          {kind === "resource" && (resource || timing) && (
            <ResourceExperiment
              key={target}
              report={resource}
              timingReport={timing}
              isolation={
                original?.isolation ||
                (current && "isolation" in current ? current.isolation : null)
              }
              evaluationId={source?.evaluation_id || id}
              links={{ trace, proof }}
              related={related}
            />
          )}
          {source &&
            ((kind === "model" && !report) || (kind === "resource" && !resource && !timing)) && (
              <div className="assurance-empty">
                <h2>No compatible experiment in this workspace</h2>
                <p>This original archive belongs to a different investigation type.</p>
                <Link href={`/${kind === "model" ? "resource" : "llm"}-assurance?archive=${id}`}>
                  Open the matching investigation workspace
                </Link>
              </div>
            )}
          {!source &&
            ((kind === "model" && !report) || (kind === "resource" && !resource && !timing)) && (
              <div className="assurance-next">
                <Fingerprint />
                <div>
                  <h2>
                    {kind === "model"
                      ? "Investigate model-security experiments"
                      : "Explore resource experiments"}
                  </h2>
                  <p>
                    {kind === "model"
                      ? "This evaluation has model-execution records. Open Model Security Experiments to inspect dedicated context-leakage testing."
                      : "These are this evaluation’s resource observations. Dedicated interference and timing studies are available separately when shared."}
                  </p>
                  <Button onClick={() => navigate("", true)}>
                    {kind === "model"
                      ? "Open Model Security Experiments"
                      : "Open Resource Experiments"}
                  </Button>
                </div>
              </div>
            )}
        </>
      )}
    </section>
  );
}
function RuntimeEvidence({
  kind,
  runtime,
  model,
}: {
  kind: "model" | "resource";
  runtime: Runtime;
  model: Model | null;
}) {
  const snapshot = runtime.snapshot!;
  const worker = snapshot.workloads.find((w) => w.role === "model");
  const context = snapshot.probes.find((p) => p.probe_id === "FRESH_CASE_CONTEXT");
  return (
    <section className="assurance-runtime" aria-label="This evaluation runtime evidence">
      <div className="assurance-metrics">
        {(kind === "model"
          ? [
              ["Model", model?.model_id || "Not recorded", Cpu],
              ["Model worker", worker?.container_id || "Not recorded", Layers3],
              [
                "Read-only model artifact",
                worker?.controls.approved_read_only_model_mount === true
                  ? "Inspected read-only mount"
                  : "No mount check recorded",
                Fingerprint,
              ],
              [
                "Context check",
                context ? "1 recorded context check" : "No check recorded",
                ScanLine,
              ],
            ]
          : [
              ["Workloads", `${snapshot.workloads.length} inspected`, Layers3],
              ["Execution profile", words(snapshot.isolation?.security_profile), Cpu],
              [
                "Admission wait",
                snapshot.isolation ? `${snapshot.isolation.queue_wait_ms} ms` : "Not recorded",
                ScanLine,
              ],
              ["Cleanup", words(runtime.cleanup_status || snapshot.cleanup), Fingerprint],
            ]
        ).map(([label, value, Icon]) => {
          const Symbol = Icon as typeof Cpu;
          return (
            <article key={String(label)}>
              <Symbol size={19} />
              <span>{String(label)}</span>
              <strong>{String(value)}</strong>
            </article>
          );
        })}
      </div>
      {kind === "model" ? (
        <div className="assurance-info-grid">
          <article>
            <h3>Model execution isolation</h3>
            <dl>
              <div>
                <dt>Backend</dt>
                <dd>{model?.backend || "Not recorded"}</dd>
              </div>
              <div>
                <dt>Context handling</dt>
                <dd>
                  {context ? "Fresh-context check recorded" : "No context-handling check recorded"}
                </dd>
              </div>
              <div>
                <dt>Cache configuration</dt>
                <dd>
                  {context?.status === "PASS" && context.observed.includes("prompt_cache=False")
                    ? "Prompt caching disabled in the recorded runtime check"
                    : "No cache-configuration check recorded"}
                </dd>
              </div>
              <div>
                <dt>Context window</dt>
                <dd>{model?.generation.context_window ?? "Not recorded"} tokens</dd>
              </div>
            </dl>
          </article>
          <article>
            <h3>Context separation</h3>
            <p>
              {context
                ? context.status === "PASS"
                  ? "The runtime’s fresh-context check completed successfully."
                  : context.status === "FAIL"
                    ? "A context check failed. Inspect the original finding below."
                    : "The recorded context check needs further investigation."
                : "No dedicated cross-session recall experiment is attached to this evaluation."}
            </p>
            <p>
              Worker {worker?.container_id || "not recorded"} · observed {date(runtime.updated_at)}
            </p>
          </article>
        </div>
      ) : (
        <div className="resource-table-scroll">
          <table>
            <caption>Inspected workload budgets and last available samples</caption>
            <thead>
              <tr>
                <th>Workload</th>
                <th>Profile</th>
                <th>CPU limit</th>
                <th>Memory limit</th>
                <th>PID limit</th>
                <th>Last memory sample</th>
                <th>Last CPU sample</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.workloads.map((w) => (
                <tr key={w.role}>
                  <th>{w.role}</th>
                  <td>{w.resource_profile}</td>
                  <td>{w.cpu_limit} CPU</td>
                  <td>{w.memory_limit / 1048576} MiB</td>
                  <td>{w.pids_limit}</td>
                  <td>
                    {w.memory_bytes == null
                      ? "Not recorded"
                      : `${(w.memory_bytes / 1048576).toFixed(1)} MiB`}
                  </td>
                  <td>{w.cpu_percent == null ? "Not recorded" : `${w.cpu_percent.toFixed(1)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>Last available samples · {date(runtime.updated_at)}. Samples are not peak usage.</p>
          <p>
            Runtime {words(snapshot.state)} · recovery {words(runtime.recovery_state)} · credential
            revocation {runtime.credentials_revoked === true ? "recorded" : "not recorded"}.
          </p>
        </div>
      )}
      <details className="assurance-details">
        <summary>Inspect runtime checks and technical scope</summary>
        <p>
          Recorded controls describe this evaluation. Dedicated leakage and timing conclusions
          require their own experiments. Shared-host timing confidentiality and physical erasure
          remain unproven.
        </p>
        <p>
          Model revision: <code>{model?.revision || "Not recorded"}</code>. Artifact:{" "}
          <code>{model?.artifact_sha256 || "Not recorded"}</code>.
        </p>
        {snapshot.probes.map((p) => (
          <p key={p.probe_id}>
            <strong>
              {words(p.probe_id)} · {p.status}
            </strong>{" "}
            — {p.observed}
          </p>
        ))}
      </details>
    </section>
  );
}
