"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Activity,
  ArrowLeftRight,
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  Focus,
  Layers,
  Radio,
  RefreshCw,
  ScanLine,
  ShieldCheck,
} from "lucide-react";
import type { components } from "@/lib/api.generated";
import type { Evaluation } from "@/lib/operator-api";
import {
  prepareReplay,
  stateAt,
  replayDelay,
  stepPosition,
  type Actor,
  type XEvent,
} from "@/lib/xray-state";
import { useResource } from "../use-resource";
import { useXrayFeed } from "../use-xray-feed";
import { keyMoments } from "@/lib/product-clarity";
import { terminalStates } from "@/lib/guided-evaluation";
import { InspectorDrawer } from "../ui";
import { XrayCanvas } from "./canvas";
import { XrayInspector, type Inspection } from "./inspector";
import { XrayTimeline, semanticActor } from "./timeline";
type Report = components["schemas"]["CampaignSummary"];
type Pair = components["schemas"]["ComparisonResponse"];
type PairIndex = components["schemas"]["ComparisonIndex"];
type Runtime = components["schemas"]["RuntimeResponse"];
export type XrayMode = "live" | "replay";
export function XrayWorkspace() {
  const evaluations = useResource<Evaluation[]>("/evaluations"),
    comparisons = useResource<PairIndex[]>("/comparisons");
  const query = useSearchParams(),
    router = useRouter();
  const chosen = query.get("evaluation") || "";
  const comparison = query.get("comparison") || "";
  const arm = query.get("arm") === "baseline" ? "baseline" : "defended";
  const standalone = useRef(chosen);
  const [mode, setMode] = useState<XrayMode | null>(null),
    [caseIndex, setCaseIndex] = useState("all"),
    [showCompare, setShowCompare] = useState(false);
  function setChosen(value: string) {
    standalone.current = value;
    router.replace(`/x-ray?evaluation=${encodeURIComponent(value)}`, { scroll: false });
  }
  function setComparison(value: string) {
    const next = new URLSearchParams(query);
    if (value) {
      if (!comparison) standalone.current = chosen;
      next.set("comparison", value);
      next.delete("evaluation");
    } else {
      next.delete("comparison");
      next.delete("arm");
      if (standalone.current) next.set("evaluation", standalone.current);
    }
    router.replace(`/x-ray?${next}`, { scroll: false });
  }
  function setArm(value: "baseline" | "defended") {
    const next = new URLSearchParams(query);
    next.set("arm", value);
    if (pair) next.set("evaluation", value === "baseline" ? pair.baseline_id : pair.defended_id);
    router.replace(`/x-ray?${next}`, { scroll: false });
  }
  const pairResource = useResource<Pair>(comparison ? `/comparisons/${comparison}` : null);
  const pair = comparison && pairResource.data?.id === comparison ? pairResource.data : null;
  const selectedId = comparison
    ? pair
      ? arm === "baseline"
        ? pair.baseline_id
        : pair.defended_id
      : ""
    : chosen ||
      evaluations.data?.find((e) => e.evaluation_kind === "campaign")?.id ||
      evaluations.data?.[0]?.id ||
      "";
  useEffect(() => {
    if (selectedId && query.get("evaluation") !== selectedId) {
      const next = new URLSearchParams(query);
      next.set("evaluation", selectedId);
      window.history.replaceState(null, "", `/x-ray?${next}`);
    }
  }, [selectedId, query]);
  const evaluation = evaluations.data?.find((e) => e.id === selectedId);
  const effectiveMode =
    mode ?? (evaluation && !terminalStates.includes(evaluation.status) ? "live" : "replay");
  const caseRecord =
    pair && caseIndex !== "all"
      ? {
          baseline: pair.baseline.cases.find((c) => c.case_index === Number(caseIndex)),
          defended: pair.defended.cases.find((c) => c.case_index === Number(caseIndex)),
        }
      : null;
  const changeMode = useCallback((value: XrayMode) => setMode(value), []);
  return (
    <div className="xray-workspace" data-testid="xray-workspace">
      <header className="xray-masthead">
        <div className="xray-brand">
          <span className="xray-brand-icon">
            <ScanLine size={25} />
          </span>
          <div>
            <span className="xray-eyebrow">ADVERSARIAL EXECUTION & FORENSICS</span>
            <h1>
              NEXUS <span>X-Ray</span>
            </h1>
            <p>Follow recorded security decisions and AI execution.</p>
          </div>
        </div>
        <div className="xray-masthead-right">
          <span className="xray-evidence-tag">
            <ShieldCheck size={13} />
            EVIDENCE AVAILABLE TO YOUR ROLE
          </span>
          <Link href="/attack-lab">
            Configure in Attack Lab <ArrowUpRight size={13} />
          </Link>
        </div>
      </header>
      {selectedId && (
        <nav className="evidence-journey" aria-label="Evaluation journey">
          <Link href={`/evaluations/${selectedId}`}>Back to evaluation</Link>
          <Link href={`/proof-vault?evaluation=${selectedId}`}>Verify this test’s evidence</Link>
        </nav>
      )}
      <div className="xray-toolbar">
        <label>
          Evaluation
          <select
            aria-label="X-Ray evaluation"
            value={selectedId}
            disabled={!!comparison}
            onChange={(e) => {
              setChosen(e.target.value);
              setCaseIndex("all");
            }}
          >
            <option value="">Choose an authorized evaluation</option>
            {evaluations.data?.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name} · {e.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Campaign / matched comparison
          <select
            aria-label="X-Ray comparison"
            value={comparison}
            onChange={(e) => {
              setComparison(e.target.value);
              setCaseIndex("all");
            }}
          >
            <option value="">Single evaluation</option>
            {comparisons.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Observation mode
          <select
            aria-label="X-Ray mode"
            value={effectiveMode}
            onChange={(e) => setMode(e.target.value as XrayMode)}
          >
            <option value="replay">RECORDED REPLAY</option>
            <option value="live">LIVE EXECUTION</option>
          </select>
        </label>
        <button
          className="xray-icon-button"
          aria-label="Refresh X-Ray catalogue"
          onClick={() => {
            evaluations.reload();
            comparisons.reload();
            pairResource.reload();
          }}
        >
          <RefreshCw size={16} />
        </button>
      </div>
      {(evaluations.error || comparisons.error || (comparison && pairResource.error)) && (
        <div className="xray-error" role="alert">
          {evaluations.error || comparisons.error || pairResource.error}
        </div>
      )}
      {comparison && pair && (
        <section className="xray-comparison" data-testid="xray-comparison">
          <div className="xray-comparison-title">
            <span>
              <ArrowLeftRight size={17} />
              MATCHED EXECUTION
            </span>
            <button aria-expanded={showCompare} onClick={() => setShowCompare(!showCompare)}>
              {showCompare ? <ChevronDown size={15} /> : <ChevronRight size={15} />}Recorded
              comparison inspector
            </button>
          </div>
          <div className="xray-arm-switch" role="group" aria-label="Comparison trace arm">
            {(["baseline", "defended"] as const).map((a) => (
              <button key={a} aria-pressed={arm === a} onClick={() => setArm(a)}>
                <span>{a.toUpperCase()}</span>
                <strong>
                  {pair[a].success}
                  <small> / {pair[a].total_cases} attack successes</small>
                </strong>
                <code>{pair[a].evaluation_id.slice(0, 8)}</code>
              </button>
            ))}
          </div>
          {showCompare && (
            <div className="xray-comparison-inspector">
              <p>
                Same committed corpus, model, generation and scoring. Independent execution
                identities. These are recorded final/so-far results, not a general model-safety
                benchmark.
              </p>
              <div className="xray-comparison-facts">
                <span>
                  Input blocks <strong>{pair.defended.blocked_input}</strong>
                </span>
                <span>
                  Output interventions <strong>{pair.defended.output_interventions}</strong>
                </span>
                <span>
                  Conclusion <code>{pair.conclusion}</code>
                </span>
              </div>
              {caseRecord && (
                <table aria-label="Matched case recorded results">
                  <thead>
                    <tr>
                      <th>Recorded case {Number(caseIndex) + 1}</th>
                      <th>Baseline</th>
                      <th>Defended</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      [
                        "Outcome",
                        caseRecord.baseline?.attack_outcome,
                        caseRecord.defended?.attack_outcome,
                      ],
                      [
                        "Input / output",
                        `${caseRecord.baseline?.input_action ?? "—"} / ${caseRecord.baseline?.output_action ?? "—"}`,
                        `${caseRecord.defended?.input_action ?? "—"} / ${caseRecord.defended?.output_action ?? "—"}`,
                      ],
                      [
                        "Model execution",
                        caseRecord.baseline?.model_execution,
                        caseRecord.defended?.model_execution,
                      ],
                      [
                        "Authorized final output",
                        caseRecord.baseline?.released_output ?? "Restricted or not released",
                        caseRecord.defended?.released_output ?? "Restricted or not released",
                      ],
                    ].map((row) => (
                      <tr key={row[0]}>
                        {row.map((v, i) => (
                          <td key={i}>{v ?? "Not recorded"}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <details>
                <summary>Immutable matched configuration</summary>
                <code>{pair.manifest_digest}</code>
                <pre>{JSON.stringify(pair.manifest, null, 2)}</pre>
              </details>
            </div>
          )}
        </section>
      )}
      {selectedId ? (
        <XrayTrace
          key={selectedId}
          evaluationId={selectedId}
          campaign={evaluation?.evaluation_kind === "campaign" || !!comparison}
          runtimeType={
            evaluation?.execution_mode ?? pair?.[arm].model_manifest.isolation ?? "Not recorded"
          }
          mode={
            mode ?? (evaluation && !terminalStates.includes(evaluation.status) ? "live" : "replay")
          }
          onMode={changeMode}
          caseIndex={caseIndex}
          onCaseIndex={setCaseIndex}
        />
      ) : (
        <div className="xray-empty">
          <Layers size={36} />
          <h2>
            {evaluations.loading || !!comparison
              ? "Loading authorized execution history"
              : "No authorized evaluations"}
          </h2>
          <p>
            {evaluations.loading
              ? "Verifying membership and loading recorded sources."
              : "Create, approve and run an evaluation in Attack Lab. X-Ray never seeds execution events."}
          </p>
          <Link href="/">Open Mission Control</Link>
        </div>
      )}
    </div>
  );
}
function XrayTrace({
  evaluationId,
  campaign,
  runtimeType,
  mode,
  onMode,
  caseIndex,
  onCaseIndex,
}: {
  evaluationId: string;
  campaign: boolean;
  runtimeType: string;
  mode: XrayMode;
  onMode: (m: XrayMode) => void;
  caseIndex: string;
  onCaseIndex: (value: string) => void;
}) {
  const feed = useXrayFeed(evaluationId, mode === "live");
  const reportResource = useResource<Report>(campaign ? `/campaigns/${evaluationId}` : null),
    runtimeResource = useResource<Runtime>(`/evaluations/${evaluationId}/runtime`);
  const { reload: reloadReport } = reportResource,
    { reload: reloadRuntime } = runtimeResource;
  useEffect(() => {
    if (mode !== "live") return;
    const timer = setInterval(() => {
      reloadReport();
      reloadRuntime();
    }, 2000);
    return () => clearInterval(timer);
  }, [mode, reloadReport, reloadRuntime]);
  return (
    <XrayTraceView
      evaluationId={evaluationId}
      campaign={campaign}
      runtimeType={runtimeType}
      mode={mode}
      onMode={onMode}
      caseIndex={caseIndex}
      onCaseIndex={onCaseIndex}
      feed={feed}
      report={reportResource.data}
      runtime={runtimeResource.data}
      detailError={reportResource.error || runtimeResource.error}
    />
  );
}
export function XrayTraceView({
  evaluationId,
  runtimeType,
  mode,
  onMode,
  caseIndex,
  onCaseIndex,
  feed,
  report,
  runtime,
  detailError = "",
  compact = false,
}: {
  feed: ReturnType<typeof useXrayFeed>;
  report: Report | null;
  runtime: Runtime | null;
  detailError?: string;
  compact?: boolean;
  evaluationId: string;
  campaign: boolean;
  runtimeType: string;
  mode: XrayMode;
  onMode: (m: XrayMode) => void;
  caseIndex: string;
  onCaseIndex: (value: string) => void;
}) {
  useEffect(() => {
    if (mode === "live" && report && terminalStates.includes(report.status)) onMode("replay");
  }, [mode, report, onMode]);
  const index = useMemo(() => prepareReplay(feed.events), [feed.events]);
  const [focus, setFocus] = useState(false);
  const [story, setStory] = useState(true);
  useEffect(() => {
    if (!focus) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFocus(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [focus]);
  const [cursor, setCursor] = useState<number | null>(null),
    [playing, setPlaying] = useState(false),
    [speed, setSpeed] = useState(1),
    [inspection, setInspection] = useState<Inspection>(
      caseIndex === "all" ? { kind: "node", actor: "REFERENCE_MONITOR" } : { kind: "case" },
    ),
    [inspectorOpen, setInspectorOpen] = useState(false),
    [actorFilter, setActorFilter] = useState<Actor | null>(null),
    [correlationFilter, setCorrelationFilter] = useState<string | null>(null);
  const position =
    mode === "live"
      ? feed.events.length - 1
      : Math.min(cursor ?? feed.events.length - 1, feed.events.length - 1);
  const state = useMemo(() => stateAt(index, position), [index, position]);
  const record =
    caseIndex === "all" ? undefined : report?.cases.find((c) => c.case_index === Number(caseIndex));
  const correlation =
    correlationFilter ||
    record?.correlation_id ||
    (caseIndex !== "all"
      ? feed.events.find(
          (e) =>
            e.event_type === "ATTACK_CASE_STARTED" &&
            e.permitted_metadata.case_index === Number(caseIndex),
        )?.correlation_id
      : null) ||
    null;
  const choices = useMemo(() => {
    const values = new Map<number, string>();
    for (const e of feed.events)
      if (e.permitted_metadata.case_index != null)
        values.set(e.permitted_metadata.case_index, `Case ${e.permitted_metadata.case_index + 1}`);
    for (const c of report?.cases ?? [])
      values.set(
        c.case_index,
        c.title
          ? `Case ${c.case_index + 1} · ${c.title}`
          : `Case ${c.case_index + 1} · restricted content`,
      );
    return [...values.entries()].sort((a, b) => a[0] - b[0]);
  }, [feed.events, report]);
  useEffect(() => {
    if (!playing || mode !== "replay" || !feed.events.length) return;
    const next = feed.events[position + 1];
    const timer = setTimeout(
      () => {
        if (!next) {
          setPlaying(false);
          return;
        }
        setCursor(stepPosition(position, 1, feed.events.length));
      },
      next ? replayDelay(feed.events[position], next, speed).delay : 0,
    );
    return () => clearTimeout(timer);
  }, [playing, mode, position, speed, feed.events]);
  const selectSequence = useCallback(
    (sequence: number) => {
      const event = feed.events.find((e) => e.sequence === sequence);
      if (!event) return;
      setPlaying(false);
      onMode("replay");
      setCursor(feed.events.findIndex((e) => e.sequence === sequence));
      setInspection({ kind: "event", sequence });
      setActorFilter(null);
      setInspectorOpen(true);
      const matched = report?.cases.find((c) => c.correlation_id === event.correlation_id);
      if (matched) {
        onCaseIndex(String(matched.case_index));
        setCorrelationFilter(null);
      } else {
        onCaseIndex("all");
        setCorrelationFilter(
          ["Policy", "Case", "Guard"].some((c) => c === categoryFor(event))
            ? event.correlation_id
            : null,
        );
      }
    },
    [feed.events, report, onMode, onCaseIndex],
  );
  const inspect = useCallback((actor: Actor) => {
    setInspection({ kind: "node", actor });
    setActorFilter(actor);
    setInspectorOpen(true);
  }, []);
  const selectCase = (value: string) => {
    onCaseIndex(value);
    setCorrelationFilter(null);
    setActorFilter(null);
    setInspection({ kind: "case" });
    setInspectorOpen(value !== "all");
    if (mode === "replay" && value !== "all") {
      const c = report?.cases.find((c) => c.case_index === Number(value));
      const candidates = feed.events
        .map((e, i) => ({ e, i }))
        .filter(({ e }) => e.correlation_id === c?.correlation_id);
      if (candidates.length) setCursor(candidates[candidates.length - 1].i);
    }
  };
  const provider =
    report?.provider === "local"
      ? "LOCAL MODEL · Qwen2.5"
      : report?.provider === "mock"
        ? "MOCK · deterministic fixture"
        : "Provider identity not recorded";
  const current = feed.events[position];
  return (
    <section
      className={`xray-execution ${compact ? "secure-trace" : ""} ${focus ? "xray-focus" : ""}`}
      data-testid="xray-execution"
      data-evaluation-id={evaluationId}
    >
      <div className="xray-observation-bar">
        <span className={`xray-mode-tag ${mode === "live" ? "xray-mode-live" : ""}`}>
          {mode === "live" ? <Radio size={13} /> : <Activity size={13} />}{" "}
          {mode === "live" ? "LIVE EXECUTION" : "RECORDED REPLAY"}
        </span>
        <span data-testid="xray-connection">{feed.status}</span>
        <span className="xray-runtime-type">
          {runtimeType} · {provider}
        </span>
        <strong data-testid="xray-evaluation-state">{state.evaluationState}</strong>
      </div>
      {feed.error && (
        <p className="xray-error" role="alert">
          {feed.error} <button onClick={feed.reload}>Reload history</button>
        </p>
      )}
      {feed.truncated && (
        <p className="xray-error" role="alert">
          History exceeds the 10,000-event display limit. This is an incomplete prefix; no complete
          replay or current-state claim is made.
        </p>
      )}
      {detailError && (
        <p className="xray-caution" role="status">
          Case/runtime detail unavailable: {detailError}. Authorized event history remains separate.
        </p>
      )}
      <div className="xray-case-bar">
        <label>
          Attack case
          <select
            aria-label="X-Ray attack case"
            value={caseIndex}
            onChange={(e) => selectCase(e.target.value)}
          >
            <option value="all">All recorded traces</option>
            {choices.map(([i, title]) => (
              <option key={i} value={i}>
                {title}
              </option>
            ))}
          </select>
        </label>
        <div className="xray-record-progress">
          <span>
            {report
              ? `${report.measured_cases} / ${report.total_cases} recorded case outcomes`
              : `${feed.events.length} permitted events`}
          </span>
          <small data-testid="xray-physical-state">At playhead: {state.physical}</small>
        </div>
        <button
          className="xray-inspector-toggle"
          onClick={() => setFocus(!focus)}
          aria-pressed={focus}
        >
          <Focus size={15} />
          {focus ? "Exit focus" : "Focus view"}
        </button>
        <button
          onClick={() => setInspectorOpen(!inspectorOpen)}
          aria-expanded={inspectorOpen}
          className="xray-inspector-toggle"
        >
          <Focus size={15} />
          {inspectorOpen ? "Hide inspector" : "Show inspector"}
        </button>
      </div>
      <div className={`xray-main-grid ${inspectorOpen ? "" : "xray-inspector-hidden"}`}>
        <div className="xray-canvas-surface">
          <div className="xray-canvas-heading">
            <span>
              <ScanLine size={14} />
              {compact && mode === "replay" ? "RECORDED REPLAY" : "EXECUTION TOPOLOGY"}
            </span>
            <span>
              {compact && mode === "replay" && !current
                ? "Before first recorded event"
                : `Sequence ${state.sequence || "—"}`}{" "}
              · {correlation ? `trace ${correlation.slice(0, 8)}` : "all correlations"}
            </span>
          </div>
          <XrayCanvas
            humanDomains={compact}
            state={state}
            correlation={correlation}
            selected={
              inspection.kind === "node"
                ? inspection.actor
                : current
                  ? (semanticActor(current) as Actor)
                  : null
            }
            inspect={inspect}
            eventSequence={inspection.kind === "event" ? inspection.sequence : state.sequence}
            provider={provider}
            pulseSequence={mode === "live" ? feed.realtime : playing ? (current?.sequence ?? 0) : 0}
            onRoute={selectSequence}
          />
          <div className="xray-canvas-caption">
            <span>
              <ShieldCheck size={13} /> Logical stages, not direct tenant network connections.
            </span>
            <span>Live records · verify signed snapshots in Proof Vault</span>
          </div>
        </div>
        {inspectorOpen && (
          <InspectorDrawer
            title="X-Ray forensic inspector"
            onClose={() => setInspectorOpen(false)}
            closeLabel="Close X-Ray inspector"
          >
            <XrayInspector
              inspection={inspection}
              evaluationId={evaluationId}
              state={state}
              events={feed.events}
              correlation={correlation}
              record={record}
              runtime={runtime}
              onEvent={selectSequence}
              onCase={() => setInspection({ kind: "case" })}
            />
          </InspectorDrawer>
        )}
      </div>
      <details className="xray-trace-controls" open={compact ? undefined : true}>
        <summary hidden={!compact}>Original events and replay controls</summary>
        <section className="clarity-story" aria-label="Execution story">
          <div className="guided-actions" role="group" aria-label="Timeline detail">
            <button className="button" aria-pressed={story} onClick={() => setStory(true)}>
              Key Moments
            </button>
            <button className="button" aria-pressed={!story} onClick={() => setStory(false)}>
              All Events
            </button>
          </div>
          {story && (
            <>
              <h2>What happened during this test</h2>
              <p>
                Select a recorded moment to inspect its original event, timestamp and correlation.
              </p>
              <ol className="clarity-moments">
                {keyMoments(feed.events).map(({ event, label }) => (
                  <li key={event.event_id}>
                    <button
                      onClick={() => {
                        if (typeof event.sequence === "number") selectSequence(event.sequence);
                      }}
                      aria-current={current?.event_id === event.event_id ? "step" : undefined}
                    >
                      <span>{label}</span>
                      <small>
                        #{event.sequence}
                        {event.permitted_metadata.case_index != null
                          ? ` · Case ${event.permitted_metadata.case_index + 1}`
                          : ""}{" "}
                        · {event.timestamp.slice(11, 19)} UTC
                      </small>
                    </button>
                  </li>
                ))}
              </ol>
              {!keyMoments(feed.events).length && (
                <p>No key transitions are recorded in your authorized history yet.</p>
              )}
            </>
          )}
        </section>
        {!story && (
          <XrayTimeline
            events={feed.events}
            position={position}
            live={mode === "live"}
            playing={playing}
            speed={speed}
            onSpeed={setSpeed}
            onPlay={() => {
              if (position >= feed.events.length - 1) setCursor(-1);
              setPlaying(true);
            }}
            onPause={() => setPlaying(false)}
            onSeek={(v) => {
              setCursor(v);
              setInspection({ kind: "event", sequence: feed.events[v]?.sequence ?? 0 });
            }}
            correlation={correlation}
            actorFilter={actorFilter}
            onClearActor={() => {
              setActorFilter(null);
              setCorrelationFilter(null);
            }}
            onSelect={(e) => selectSequence(e.sequence)}
          />
        )}
      </details>
    </section>
  );
}
function categoryFor(event: XEvent) {
  return event.event_type.startsWith("POLICY_")
    ? "Policy"
    : event.event_type.startsWith("ATTACK_CASE")
      ? "Case"
      : event.event_type.includes("GUARD_EVALUATED")
        ? "Guard"
        : "Other";
}
