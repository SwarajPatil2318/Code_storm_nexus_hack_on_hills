"use client";
import { useEffect, useRef, useState } from "react";
import type { components } from "@/lib/api.generated";
import { defenceExamples } from "@/lib/defence-examples";
import { operatorRequest } from "@/lib/operator-api";
import { useAuth } from "../auth-provider";
import { Button, Badge } from "../ui";
type Policy = components["schemas"]["BluePolicy"];
type Version = components["schemas"]["VersionResponse"];
const terms = (s: string) =>
  s
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
export function BluePolicyWizard({
  open,
  onClose,
  onAdvanced,
  onPublished,
}: {
  open: boolean;
  onClose: () => void;
  onAdvanced: () => void;
  onPublished: (version: Version) => void;
}) {
  const { session } = useAuth();
  const [step, setStep] = useState(1),
    [name, setName] = useState("My defence policy"),
    [purpose, setPurpose] = useState("Protect the declared synthetic instruction boundary.");
  const [input, setInput] = useState("PUBLIC_DEMO_BLOCK"),
    [output, setOutput] = useState("NEXUS_SYNTH_CANARY\nNEXUS_SYNTH_CREDENTIAL"),
    [inputAction, setInputAction] = useState<Policy["input_action"]>("BLOCK"),
    [outputAction, setOutputAction] = useState<Policy["output_action"]>("BLOCK"),
    [strip, setStrip] = useState(true),
    [requireJson, setRequireJson] = useState(false);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [artifact, setArtifact] = useState(""),
    [published, setPublished] = useState<Version | null>(null);
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (open) title.current?.focus();
  }, [step, open]);
  const policy: Policy = {
    schema_version: "blue-policy-v1",
    input_terms: terms(input),
    input_action: inputAction,
    output_terms: terms(output),
    output_action: outputAction,
    require_json: requireJson,
    strip_role_tokens: strip,
  };
  function validate() {
    if (!name.trim() || name.length > 160) throw Error("Name your policy using 1–160 characters.");
    if (!purpose.trim() || purpose.length > 640)
      throw Error("Describe its purpose using 1–640 characters.");
    for (const [label, rows] of [
      ["Input", terms(input)],
      ["Output", terms(output)],
    ] as const)
      if (rows.length > 20 || rows.some((t) => t.length > 96))
        throw Error(`${label} rules support at most 20 literal patterns, each 1–96 characters.`);
  }
  function next() {
    try {
      validate();
      setError("");
      setStep((s) => Math.min(5, s + 1));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Check your draft.");
    }
  }
  async function publish() {
    if (busy || published) return;
    setBusy(true);
    setError("");
    try {
      validate();
      let id = artifact;
      if (!id) {
        const a = await operatorRequest<components["schemas"]["ArtifactResponse"]>("/artifacts", {
          method: "POST",
          csrf: session.csrf_token,
          body: { name: name.trim(), kind: "defence", content: purpose.trim() },
        });
        id = a.id;
        setArtifact(id);
      }
      const v = await operatorRequest<Version>(`/artifacts/${id}/versions`, {
        method: "POST",
        csrf: session.csrf_token,
        body: { content: policy },
      });
      setPublished(v);
      onPublished(v);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Publication failed. Existing saved records remain. Check your owned versions before retrying after a connection interruption.",
      );
    } finally {
      setBusy(false);
    }
  }
  if (!open) return null;
  return (
    <section
      className="blue-wizard"
      aria-label="Guided Blue policy creation"
      data-testid="blue-policy-wizard"
    >
      <header>
        <div>
          <span className="eyebrow">BLUE · PRIVATE POLICY AUTHORING</span>
          <h2 ref={title} tabIndex={-1}>
            {published
              ? "Policy version published"
              : `Step ${step} · ${["Name and purpose", "Incoming input rules", "Outgoing response rules", "Review your protection", "Publish immutable version"][step - 1]}`}
          </h2>
        </div>
        <Button disabled={busy} onClick={onClose}>
          {published ? "Return to sharing" : "Keep draft on this page"}
        </Button>
      </header>
      <p>
        Build a literal-rule policy, publish its immutable version, then separately share a
        reference and approve the exact evaluation.
      </p>
      <nav aria-label="Blue policy steps">
        {["Name", "Input", "Output", "Review", "Publish"].map((s, i) => (
          <span key={s} aria-current={step === i + 1 ? "step" : undefined}>
            {i + 1} · {s}
          </span>
        ))}
      </nav>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {published ? (
        <div className="guided-form">
          <Badge tone="blue">PUBLISHED · NOT GRANTED OR APPROVED</Badge>
          <p>
            Version <code>{published.version_id}</code>
          </p>
          <p>
            SHA-256 <code>{published.sha256}</code>
          </p>
          <ol>
            <li>
              Return to sharing and explicitly grant this version’s reference to the assigned Red
              email.
            </li>
            <li>Wait for Red to commit an evaluation.</li>
            <li>
              Review that exact commitment in the approval inbox. Publication and sharing never
              approve it.
            </li>
          </ol>
          <Button onClick={onClose} variant="primary">
            Continue to reference sharing
          </Button>
          <Button
            onClick={() => {
              setPublished(null);
              setArtifact("");
              setStep(1);
              setName("My defence policy");
              setPurpose("Protect the declared synthetic instruction boundary.");
              setInput("PUBLIC_DEMO_BLOCK");
              setOutput("NEXUS_SYNTH_CANARY\nNEXUS_SYNTH_CREDENTIAL");
              setInputAction("BLOCK");
              setOutputAction("BLOCK");
              setStrip(true);
              setRequireJson(false);
              setError("");
              setNotice("");
            }}
          >
            Create another policy
          </Button>
        </div>
      ) : (
        <form
          className="guided-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (step < 5) next();
            else void publish();
          }}
        >
          {step === 1 && (
            <>
              <label>
                Blue policy name
                <input
                  required
                  maxLength={160}
                  disabled={!!artifact}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <label>
                Protection purpose
                <textarea
                  aria-label="Protection purpose"
                  required
                  maxLength={640}
                  disabled={!!artifact}
                  value={purpose}
                  onChange={(e) => setPurpose(e.target.value)}
                />
              </label>
              <div className="guided-examples" aria-label="Supported example configurations">
                {defenceExamples.map((ex) => (
                  <Button
                    key={ex.name}
                    onClick={() => {
                      setName(ex.name);
                      setInput((ex.policy.input_terms ?? []).join("\n"));
                      setOutput((ex.policy.output_terms ?? []).join("\n"));
                      setInputAction(ex.policy.input_action);
                      setOutputAction(ex.policy.output_action);
                      setStrip(!!ex.policy.strip_role_tokens);
                      setRequireJson(!!ex.policy.require_json);
                      setNotice(ex.detail);
                    }}
                  >
                    {ex.name}
                  </Button>
                ))}
              </div>
            </>
          )}
          {step === 2 && (
            <>
              <p>
                Match case-insensitive literal substrings in untrusted user/assistant messages.
                These rules do not detect semantic injection; obfuscation or paraphrase may evade
                them.
              </p>
              <label>
                Private input literal patterns
                <textarea
                  aria-label="Private input literal patterns"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  rows={5}
                />
              </label>
              <label>
                Input rule action
                <select
                  aria-label="Input rule action"
                  value={inputAction}
                  onChange={(e) => setInputAction(e.target.value as Policy["input_action"])}
                >
                  <option value="BLOCK">BLOCK · withhold and skip inference</option>
                  <option value="TRANSFORM">TRANSFORM · replace matched text</option>
                  <option value="ALLOW">ALLOW · do not intervene on a literal match</option>
                </select>
              </label>
              <label className="campaign-check">
                <input
                  type="checkbox"
                  checked={strip}
                  onChange={(e) => setStrip(e.target.checked)}
                />
                Transform fixed untrusted role delimiter tokens
              </label>
            </>
          )}
          {step === 3 && (
            <>
              <p>
                Inspect actual model output before release. Literal matches can withhold or
                transform it; a model error is not a successful defence.
              </p>
              <label>
                Private output literal patterns
                <textarea
                  aria-label="Private output literal patterns"
                  value={output}
                  onChange={(e) => setOutput(e.target.value)}
                  rows={5}
                />
              </label>
              <label>
                Output rule action
                <select
                  aria-label="Output rule action"
                  value={outputAction}
                  onChange={(e) => setOutputAction(e.target.value as Policy["output_action"])}
                >
                  <option value="BLOCK">BLOCK · withhold matched output</option>
                  <option value="TRANSFORM">TRANSFORM · replace matched text</option>
                </select>
              </label>
              <label className="campaign-check">
                <input
                  type="checkbox"
                  checked={requireJson}
                  onChange={(e) => setRequireJson(e.target.checked)}
                />
                Require valid JSON output
              </label>
            </>
          )}
          {step === 4 && (
            <>
              <h3>{name}</h3>
              <p>{purpose}</p>
              <p>
                {terms(input).length} input patterns · {inputAction}; {terms(output).length} output
                patterns · {outputAction}. Fixed role-token transformation {strip ? "on" : "off"};
                JSON requirement {requireJson ? "on" : "off"}.
              </p>
              <details>
                <summary>Review private literal configuration</summary>
                <pre className="guided-output">{JSON.stringify(policy, null, 2)}</pre>
              </details>
              <p>
                Optional testing follows publication through the normal synthetic evaluation and
                exact Blue approval. This page performs no inference, dry-run simulation or
                automatic approval.
              </p>
            </>
          )}
          {step === 5 && (
            <>
              <p>
                Publishing creates a new immutable version. Changing it later requires a new
                version. Existing sealed policies and receipts remain untouched.
              </p>
              <p>
                Your reference is not shared until you explicitly grant it. No evaluation is
                approved by this operation.
              </p>
            </>
          )}
          <div className="guided-actions">
            {step > 1 && (
              <Button
                disabled={busy}
                onClick={() => {
                  setError("");
                  setStep((s) => s - 1);
                }}
              >
                Back
              </Button>
            )}
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? "Publishing…" : step === 5 ? "Publish immutable policy" : "Continue"}
            </Button>
            <Button
              disabled={busy}
              onClick={() =>
                setNotice(
                  "Draft kept in this page’s memory. Closing and reopening this wizard retains it; navigating away or reloading discards unsaved changes.",
                )
              }
            >
              Save draft on this page
            </Button>
            <Button disabled={busy} onClick={onAdvanced}>
              Open advanced policy editor
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}
