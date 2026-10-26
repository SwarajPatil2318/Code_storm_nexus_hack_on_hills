"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { components } from "@/lib/api.generated";
import { operatorRequest } from "@/lib/operator-api";
import {
  caseJsonl,
  examples,
  type DraftCase,
  type Version,
  type Evaluation,
} from "@/lib/guided-evaluation";
import { useAuth } from "../auth-provider";
import { useResource } from "../use-resource";
import { AccessRestricted } from "../access-state";
import { Button, PageHeading, Panel, Badge } from "../ui";
import { WorkspacePage } from "../workspace-pages";
import { suiteNames, suiteCases, libraryVersion, type SuiteName } from "@/lib/synthetic-suites";
export function GuidedRed() {
  const { session } = useAuth();
  if (session.user.role !== "RED_OPERATOR") return <AccessRestricted />;
  return <RedForm />;
}
function RedForm() {
  const { session } = useAuth(),
    router = useRouter();
  const versions = useResource<Version[]>("/campaigns/versions");
  const providers = useResource<components["schemas"]["ProviderOption"][]>("/campaigns/providers");
  const [step, setStep] = useState(1),
    [name, setName] = useState("My security evaluation"),
    [cases, setCases] = useState<DraftCase[]>([
      { prompt: "", expected: "PUBLIC_TEST_MARKER", strategy: "canary_match" },
    ]);
  const [defence, setDefence] = useState(""),
    [profile, setProfile] = useState<"STANDARD" | "REDUCED_INTERFERENCE">("STANDARD");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [saved, setSaved] = useState<{ version?: string; evaluation?: string }>({});
  const [advanced, setAdvanced] = useState(false);
  const [judgeSuiteLoadToken, setJudgeSuiteLoadToken] = useState(0);
  const local = providers.data?.find((p) => p.provider === "local");
  const choices = versions.data?.filter((v) => v.kind === "defence") || [];
  const frozen = Boolean(saved.version);
  function validate() {
    if (!name.trim() || name.length > 160) throw Error("Give your test a name (1–160 characters).");
    caseJsonl(cases);
  }
  function next() {
    try {
      validate();
      setError("");
      setStep(2);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Check the test inputs.");
    }
  }
  function change(index: number, patch: Partial<DraftCase>) {
    setCases((old) => old.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  }
  async function requestApproval() {
    if (busy) return;
    setBusy(true);
    setError("");
    let version = saved.version,
      evaluation = saved.evaluation;
    try {
      validate();
      if (!defence) throw Error("Choose an explicitly shared defence version.");
      if (!local?.available)
        throw Error(
          local?.reason ||
            "Real Qwen runtime is unavailable. Refresh readiness or use the explicitly labelled advanced alternatives.",
        );
      if (!version) {
        const v = await operatorRequest<Version>("/campaigns/corpora/import", {
          method: "POST",
          csrf: session.csrf_token,
          body: { name, jsonl: caseJsonl(cases) },
        });
        version = v.version_id;
        setSaved({ version });
      }
      if (!evaluation) {
        const body: components["schemas"]["CampaignCreate"] = {
          name,
          red_version_id: version,
          blue_version_id: defence,
          provider: "local",
          mock_mode: "safe",
          execution_mode: "isolated_docker",
          security_profile: profile,
          generation: { max_output_tokens: 32, context_window: 2048, seed: 42, temperature: 0 },
          budget: {
            max_cases: cases.length,
            max_messages: 8 * cases.length,
            timeout_seconds: 180,
            concurrency: 1,
            max_bytes: 8192,
            model_timeout_ms: 30000,
            case_timeout_ms: 45000,
          },
        };
        const e = await operatorRequest<Evaluation>("/campaigns", {
          method: "POST",
          csrf: session.csrf_token,
          body,
        });
        evaluation = e.id;
        setSaved({ version, evaluation });
      }
      await operatorRequest(`/evaluations/${evaluation}/commit`, {
        method: "POST",
        csrf: session.csrf_token,
      });
      router.push(`/evaluations/${evaluation}`);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Approval request failed. Your saved records have not been deleted.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="guided-workspace">
      <PageHeading
        eyebrow="GUIDED SECURITY TEST"
        title="Attack Lab"
        description="Create an attack. Choose a defence. Follow the evidence."
        action={
          <Link className="text-link" href="/evaluations">
            Your evaluations →
          </Link>
        }
      />
      <ol className="guided-steps" aria-label="Security test steps">
        {["Create attack", "Choose defence", "Request approval", "Run and inspect"].map((s, i) => (
          <li key={s} aria-current={step === i + 1 ? "step" : undefined}>
            <span>{i + 1}</span>
            {s}
          </li>
        ))}
      </ol>
      {error && (
        <div className="resource-error" role="alert">
          {error}
          {saved.evaluation && (
            <p>
              <Link href={`/evaluations/${saved.evaluation}`}>Resume the saved evaluation</Link>
            </p>
          )}
        </div>
      )}
      {step === 1 && (
        <Panel
          title="1 · What would you like to test?"
          subtitle="Your prompts stay in your Red domain. Blue approves commitments, not your private text."
        >
          <form
            className="guided-form"
            onSubmit={(e) => {
              e.preventDefault();
              next();
            }}
          >
            <label>
              Test name
              <input
                required
                maxLength={160}
                value={name}
                disabled={frozen}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <div className="guided-actions">
              <Button
                type="button"
                disabled={frozen}
                onClick={() => {
                  setJudgeSuiteLoadToken((value) => value + 1);
                  setAdvanced(true);
                }}
              >
                Load final four-case judge suite
              </Button>
              <p>
                Loads the exact four-case corpus in Advanced Campaign Setup. Import and Blue
                approval are still required.
              </p>
            </div>
            <details>
              <summary>Curated synthetic suites · 54 cases across bounded versions</summary>
              <p>
                Loading a suite replaces this unsaved draft. {libraryVersion}. All scores require
                execution; each imported suite gets its own immutable version. The matched suite
                selects cases only; expert matched comparison still requires separate Blue approvals
                for both arms.
              </p>
              <label>
                Load curated suite
                <select
                  disabled={frozen}
                  defaultValue=""
                  onChange={(e) => {
                    if (!e.target.value) return;
                    setCases(
                      suiteCases(e.target.value as SuiteName).map((source) => ({
                        prompt: source.attack_input,
                        expected: source.scoring.expected,
                        strategy: source.scoring.strategy,
                        source,
                      })),
                    );
                    e.target.value = "";
                  }}
                >
                  <option value="">Choose a suite (replaces draft)</option>
                  {suiteNames.map((s) => (
                    <option key={s} value={s}>
                      {s} · {suiteCases(s).length} cases
                    </option>
                  ))}
                </select>
              </label>
            </details>
            {cases.map((c, i) => (
              <fieldset className="guided-case" key={i}>
                <legend>Case {i + 1}</legend>
                {
                  <div
                    className="guided-examples"
                    aria-label={`Synthetic examples for case ${i + 1}`}
                  >
                    {examples.map((ex) => (
                      <Button
                        key={ex.name}
                        disabled={frozen}
                        onClick={() =>
                          change(i, {
                            ...ex,
                            source: undefined,
                            purpose: "purpose" in ex ? ex.purpose : "attack-attempt",
                          })
                        }
                      >
                        {ex.name}
                      </Button>
                    ))}
                  </div>
                }
                <label>
                  {i === 0 ? "Attack prompt" : `Attack prompt ${i + 1}`}
                  <textarea
                    required
                    rows={6}
                    maxLength={1600}
                    disabled={frozen}
                    value={c.prompt}
                    onChange={(e) => change(i, { prompt: e.target.value })}
                    placeholder="Enter a synthetic adversarial prompt, or choose an example above."
                  />
                </label>
                <details>
                  <summary>
                    Observable success criterion ·{" "}
                    {c.strategy === "exact_output" ? "exact answer" : "contains marker"}
                  </summary>
                  <p>
                    Scoring checks the declared response criterion. It does not certify model
                    safety.
                  </p>
                  <label>
                    Scoring method for case {i + 1}
                    <select
                      disabled={frozen}
                      value={c.strategy}
                      onChange={(e) =>
                        change(i, { strategy: e.target.value as DraftCase["strategy"] })
                      }
                    >
                      <option value="canary_match">Response contains marker</option>
                      <option value="exact_output">Response equals answer</option>
                      <option value="forbidden_marker">Response contains forbidden marker</option>
                      <option value="invalid_json">Invalid JSON syntax</option>
                      <option value="invalid_json_answer">Invalid JSON answer object</option>
                    </select>
                  </label>
                  <p>
                    Committed purpose:{" "}
                    {c.source?.tags?.includes("benign-control")
                      ? "Benign control"
                      : c.source?.tags?.includes("attack-attempt")
                        ? "Attack attempt"
                        : c.purpose || "Unclassified"}
                    . Only explicitly classified completed cases enter ASR or benign intervention
                    rates.
                  </p>
                  {c.source && (
                    <p>
                      {c.source.title} · {c.source.objective} · Expected boundary:{" "}
                      {c.source.expected_boundary} · Trusted case-local context and conversation
                      history are preserved in the imported version.
                    </p>
                  )}
                  <label>
                    Expected response for case {i + 1}
                    <input
                      required
                      maxLength={96}
                      disabled={frozen}
                      value={c.expected}
                      onChange={(e) => change(i, { expected: e.target.value })}
                    />
                  </label>
                </details>
                {i > 0 && (
                  <Button
                    disabled={frozen}
                    onClick={() => setCases((old) => old.filter((_, j) => i !== j))}
                  >
                    Remove case {i + 1}
                  </Button>
                )}
              </fieldset>
            ))}
            <div className="guided-actions">
              <Button
                disabled={cases.length >= 40 || frozen}
                onClick={() =>
                  setCases((old) => [
                    ...old,
                    { prompt: "", expected: "PUBLIC_TEST_MARKER", strategy: "canary_match" },
                  ])
                }
              >
                Add another case
              </Button>
              <Button variant="primary" type="submit">
                Continue to defence
              </Button>
            </div>
          </form>
        </Panel>
      )}
      {step === 2 && (
        <Panel
          title="2 · Choose a shared defence"
          subtitle="A shared reference permits this test; the Blue policy contents remain private."
        >
          <div className="guided-form">
            {versions.loading ? (
              <p role="status">Reading authorized defence references…</p>
            ) : versions.error ? (
              <p role="alert">{versions.error}</p>
            ) : choices.length ? (
              <label>
                Approved defence reference
                <select
                  required
                  value={defence}
                  disabled={frozen}
                  onChange={(e) => setDefence(e.target.value)}
                >
                  <option value="">Choose a Blue-shared version</option>
                  {choices.map((v) => (
                    <option key={v.version_id} value={v.version_id}>
                      Shared defence · {v.version_id.slice(0, 12)} ·{" "}
                      {new Date(v.created_at).toLocaleDateString()}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <div className="guided-empty">
                <h3>A Blue operator needs to share a defence first</h3>
                <p>
                  Ask Blue to open Defence Vault, publish or choose a policy, and share its
                  reference with your assigned Red email. Return here and refresh. Nothing is
                  auto-approved.
                </p>
              </div>
            )}
            <Button onClick={versions.reload}>Refresh defence references</Button>
            <div className="guided-actions">
              <Button disabled={frozen} onClick={() => setStep(1)}>
                Back to attack
              </Button>
              <Button variant="primary" disabled={!defence} onClick={() => setStep(3)}>
                Review approval request
              </Button>
            </div>
          </div>
        </Panel>
      )}
      {step === 3 && (
        <Panel
          title="3 · Request Blue approval"
          subtitle="This saves immutable versions and commits the exact test. It does not launch the model."
        >
          <div className="guided-form">
            <dl className="guided-facts">
              <div>
                <dt>Test</dt>
                <dd>{name}</dd>
              </div>
              <div>
                <dt>Cases</dt>
                <dd>{cases.length}</dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd>Real Qwen2.5-0.5B · restricted Docker</dd>
              </div>
              <div>
                <dt>Selected profile</dt>
                <dd>{profile.replaceAll("_", " ")}</dd>
              </div>
              <div>
                <dt>Defence reference</dt>
                <dd>
                  <code>{defence.slice(0, 12)}</code> · contents private
                </dd>
              </div>
            </dl>
            {providers.loading ? (
              <p role="status">Checking real model availability…</p>
            ) : providers.error ? (
              <p role="alert">{providers.error}</p>
            ) : local?.available ? (
              <Badge tone="green">
                Real model available · enforcement checked during execution
              </Badge>
            ) : (
              <div className="resource-error" role="alert">
                <strong>Real Qwen is unavailable</strong>
                <p>
                  {local?.reason || "The provisioner has not reported an available real model."}
                </p>
                <p>
                  No mock fallback is selected. Refresh or open Advanced Campaign Setup for
                  explicitly labelled alternatives.
                </p>
              </div>
            )}
            <Button onClick={providers.reload}>Refresh runtime readiness</Button>
            <details>
              <summary>Advanced Settings</summary>
              <label>
                Guided execution security profile
                <select
                  disabled={frozen}
                  value={profile}
                  onChange={(e) => setProfile(e.target.value as typeof profile)}
                >
                  <option value="STANDARD">STANDARD · shared scheduling</option>
                  <option value="REDUCED_INTERFERENCE">
                    REDUCED INTERFERENCE · separate managed cores
                  </option>
                </select>
              </label>
              <p>
                Managed non-overlap does not eliminate shared-host timing channels. Admission and
                effective placement are verified by the existing runtime.
              </p>
              <p>
                32 output tokens per case · sequential cases · 180 second deadline. More budgets,
                model modes and comparisons remain in Advanced Campaign Setup.
              </p>
            </details>
            <p>
              Only the owning Blue operator can approve this commitment. Red then seals and
              explicitly starts it. Your prompt text is not shown in the approval inbox.
            </p>
            {frozen && (
              <p>An immutable draft was saved. Retries reuse it; editing requires a new test.</p>
            )}
            <div className="guided-actions">
              <Button disabled={frozen || busy} onClick={() => setStep(2)}>
                Back to defence
              </Button>
              <Button
                disabled={busy || !local?.available || providers.loading}
                variant="primary"
                onClick={() => void requestApproval()}
              >
                {busy ? "Saving exact test…" : "Request Blue approval"}
              </Button>
            </div>
          </div>
        </Panel>
      )}
      <details
        className="guided-advanced"
        open={advanced}
        onToggle={(e) => setAdvanced(e.currentTarget.open)}
      >
        <summary>Advanced Campaign Setup</summary>
        <p>
          Expert tools: JSONL, immutable versions, matched comparisons, explicit mock reproduction,
          budgets and artifact management. These use the same evaluation system.
        </p>
        {advanced && (
          <WorkspacePage embedded kind="attack-lab" judgeSuiteLoadToken={judgeSuiteLoadToken} />
        )}
      </details>
    </div>
  );
}
