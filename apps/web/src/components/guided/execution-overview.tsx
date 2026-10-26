"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import type { components } from "@/lib/api.generated";
import { actors, nodeViews, prepareReplay, stateAt, type Actor } from "@/lib/xray-state";
import { semanticActor } from "../xray/timeline";
import type { useXrayFeed } from "../use-xray-feed";
import { Badge, InspectorDrawer, Panel } from "../ui";
const labels: Record<Actor, string> = {
  RED_RUNNER: "Red workload",
  REFERENCE_MONITOR: "Security gateway (Reference Monitor)",
  BLUE_INPUT_GUARD: "Blue input defence",
  MODEL_WORKER: "Qwen inference",
  BLUE_OUTPUT_GUARD: "Blue output defence",
  EVIDENCE_COLLECTOR: "Result",
};
export function ExecutionOverview({
  id,
  live,
  profile,
  runtime,
  real,
  feed,
}: {
  id: string;
  live: boolean;
  profile: string;
  real: boolean | null;
  feed: ReturnType<typeof useXrayFeed>;
  runtime: components["schemas"]["RuntimeResponse"] | null;
}) {
  const replay = useMemo(() => prepareReplay(feed.events), [feed.events]);
  const state = stateAt(replay, feed.events.length - 1);
  const views = nodeViews(state, null);
  const [selected, setSelected] = useState<Actor | null>(null);
  const eventFor = (actor: Actor) =>
    feed.events.findLast((e) =>
      actor === "EVIDENCE_COLLECTOR"
        ? ["RESULT_RELEASED", "EVALUATION_COMPLETED", "EVALUATION_FAILED"].includes(e.event_type)
        : semanticActor(e) === actor || e.source === actor || e.destination === actor,
    );
  const labelFor = (actor: Actor) =>
    actor === "MODEL_WORKER" && real !== true
      ? real === null
        ? "Model identity loading"
        : "Mock model · no real inference"
      : labels[actor];
  const selectedEvent = selected ? eventFor(selected) : undefined;
  const workloadRole =
    selected === "RED_RUNNER"
      ? "red"
      : selected === "MODEL_WORKER"
        ? "model"
        : selected === "BLUE_INPUT_GUARD" || selected === "BLUE_OUTPUT_GUARD"
          ? "blue"
          : null;
  const workload = runtime?.snapshot?.workloads.find((w) => w.role === workloadRole);
  const decision =
    selectedEvent &&
    feed.events.findLast(
      (e) => e.correlation_id === selectedEvent.correlation_id && e.permitted_metadata.decision,
    );
  return (
    <Panel
      title="Technical execution overview"
      subtitle="Follow this evaluation’s recorded execution stages."
    >
      <div className="guided-form">
        <p className="guided-feed" role="status">
          {live ? feed.status : "Reviewing a recorded test"} · {feed.events.length} recorded
          security events
          {feed.truncated ? " · INCOMPLETE HISTORY" : ""}
        </p>
        {feed.error && <p role="alert">{feed.error}</p>}
        <div className="guided-pipeline" aria-label="Observed execution stages">
          {actors.map((actor) => {
            const event = eventFor(actor);
            return (
              <button key={actor} className="guided-node" onClick={() => setSelected(actor)}>
                <span>
                  {actor === "MODEL_WORKER" && real === null
                    ? "Model identity loading"
                    : actor === "MODEL_WORKER" && real === false
                      ? "Mock model · no real inference"
                      : labels[actor]}
                </span>
                <Badge>
                  {event
                    ? views[actor].status === "Destroyed" &&
                      runtime?.snapshot?.cleanup === "VERIFIED"
                      ? "Safely cleaned up"
                      : views[actor].status
                    : "No event recorded"}
                </Badge>
                <small>
                  {event ? `Recorded #${event.sequence}` : "Inspect configuration and scope"}
                </small>
              </button>
            );
          })}
        </div>
        <p>
          Profile configured: <strong>{profile}</strong> · Cleanup observed:{" "}
          <strong>{runtime?.snapshot?.cleanup || "Not yet recorded"}</strong>. Open a stage to
          inspect its evidence.
        </p>
        <Link href={`/x-ray?evaluation=${id}`} className="text-link">
          Explore in X-Ray →
        </Link>
      </div>
      {selected && (
        <InspectorDrawer
          title={labelFor(selected)}
          onClose={() => setSelected(null)}
          closeLabel="Close execution inspector"
        >
          <div className="guided-form">
            <p>
              Role-filtered observations from this evaluation. No private policy or raw tenant
              internals are loaded.
            </p>
            <dl className="guided-facts">
              <div>
                <dt>Stage</dt>
                <dd>{labelFor(selected)}</dd>
              </div>
              <div>
                <dt>Observed state</dt>
                <dd>{selectedEvent ? views[selected].status : "No event recorded"}</dd>
              </div>
              <div>
                <dt>Security profile (configured)</dt>
                <dd>{profile}</dd>
              </div>
              <div>
                <dt>Workload identity</dt>
                <dd>
                  {selectedEvent
                    ? `${selectedEvent.source} → ${selectedEvent.destination}`
                    : "No authorized identity recorded"}
                </dd>
              </div>
              <div>
                <dt>Container identity</dt>
                <dd>
                  <code>{workload?.container_id || "Not exposed by this role projection"}</code>
                </dd>
              </div>
              <div>
                <dt>Latest relevant event</dt>
                <dd>{selectedEvent?.event_type || "Not recorded"}</dd>
              </div>
              <div>
                <dt>Timestamp</dt>
                <dd>{selectedEvent?.timestamp || "Not recorded"}</dd>
              </div>
              <div>
                <dt>Correlation ID</dt>
                <dd>
                  <code>{selectedEvent?.correlation_id || "Not recorded"}</code>
                </dd>
              </div>
              <div>
                <dt>Policy decision</dt>
                <dd>
                  {decision?.permitted_metadata.decision ||
                    "No recorded policy decision for this correlation"}
                </dd>
              </div>
              <div>
                <dt>Cleanup</dt>
                <dd>{runtime?.snapshot?.cleanup || "Not recorded"}</dd>
              </div>
            </dl>
            {workload && (
              <details>
                <summary>Recorded workload controls</summary>
                <pre className="guided-output">
                  {JSON.stringify(
                    {
                      image: workload.image_digest,
                      health: workload.health,
                      controls: workload.controls,
                      memory_limit: workload.memory_limit,
                      pids_limit: workload.pids_limit,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            )}
            <Link className="text-link" href={`/x-ray?evaluation=${id}`}>
              Inspect complete authorized trace
            </Link>
            <Link
              className="text-link"
              href={`/proof-vault?evaluation=${id}${selectedEvent ? `&sequence=${selectedEvent.sequence}` : ""}`}
            >
              Inspect corresponding evidence reference
            </Link>
            <p>
              A link does not imply the event is signed. Proof Vault reports actual signature, trust
              and snapshot coverage.
            </p>
          </div>
        </InspectorDrawer>
      )}
    </Panel>
  );
}
