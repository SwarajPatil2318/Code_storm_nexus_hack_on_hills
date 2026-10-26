"use client";
import { useCallback, useMemo, useState } from "react";
import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  getBezierPath,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
  type NodeChange,
} from "@xyflow/react";
import {
  Cpu,
  Crosshair,
  Database,
  ShieldCheck,
  Workflow,
  LockKeyhole,
  ArrowUpRight,
} from "lucide-react";
import { useReducedMotion } from "motion/react";
import {
  actors,
  nodeViews,
  routesFor,
  type Actor,
  type Engine,
  type NodeState,
} from "@/lib/xray-state";
import "@xyflow/react/dist/style.css";
import { RecordedGraphFit } from "../recorded-graph-fit";
export const descriptions: Record<
  Actor,
  { title: string; subtitle: string; domain: string; icon: typeof Cpu }
> = {
  RED_RUNNER: {
    title: "Red runner",
    subtitle: "Scoped case submission",
    domain: "red",
    icon: Crosshair,
  },
  REFERENCE_MONITOR: {
    title: "Reference Monitor",
    subtitle: "Default-deny mediator",
    domain: "trusted",
    icon: Workflow,
  },
  BLUE_INPUT_GUARD: {
    title: "Blue input guard",
    subtitle: "Validate · allow · transform · block",
    domain: "blue",
    icon: ShieldCheck,
  },
  MODEL_WORKER: {
    title: "Model worker",
    subtitle: "Readiness ≠ inference",
    domain: "model",
    icon: Cpu,
  },
  BLUE_OUTPUT_GUARD: {
    title: "Blue output guard",
    subtitle: "Authorize observable output",
    domain: "blue",
    icon: LockKeyhole,
  },
  EVIDENCE_COLLECTOR: {
    title: "Evidence collector",
    subtitle: "Filtered persisted projection",
    domain: "trusted",
    icon: Database,
  },
};
type Data = {
  actor: Actor;
  status: NodeState;
  active: number;
  selected: boolean;
  physical: string;
  inspect: (actor: Actor) => void;
  skipped: boolean;
  provider: string;
};
type XNode = Node<Data, "xray">;
function WorkloadNode({ data }: NodeProps<XNode>) {
  const d = descriptions[data.actor],
    Icon = d.icon;
  return (
    <button
      className={`xray-node nodrag nopan xray-domain-${d.domain} ${data.selected ? "xray-node-selected" : ""}`}
      data-state={data.status}
      onClick={() => data.inspect(data.actor)}
      aria-label={`Inspect ${d.title}`}
      aria-pressed={data.selected}
    >
      <Handle type="target" position={Position.Left} id="in" />
      <Handle type="source" position={Position.Right} id="out" />
      <Handle type="source" position={Position.Left} id="out-left" />
      <Handle type="target" position={Position.Right} id="in-right" />
      <div className="xray-node-header">
        <span className="xray-node-icon">
          <Icon size={18} />
        </span>
        <span className="xray-state-dot" />
        <span>{data.status}</span>
      </div>
      <strong>{d.title}</strong>
      <small>{data.actor === "MODEL_WORKER" ? data.provider : d.subtitle}</small>
      <div className="xray-node-foot">
        <span>
          {data.skipped && data.actor === "MODEL_WORKER"
            ? "SKIPPED · input blocked"
            : data.active > 0
              ? `${data.active} recorded active trace${data.active > 1 ? "s" : ""}`
              : data.physical}
        </span>
        <ArrowUpRight size={11} />
      </div>
    </button>
  );
}
type EData = {
  decision: string;
  sequence: number;
  message: string;
  pulse: boolean;
  selected: boolean;
  inspect: () => void;
};
type XEdge = Edge<EData, "message">;
function MessageEdge(props: EdgeProps<XEdge>) {
  const [path, x, y] = getBezierPath(props);
  const d = props.data!;
  const denied = d.decision === "DENY";
  return (
    <>
      <BaseEdge
        path={path}
        markerEnd={props.markerEnd}
        style={{
          stroke: denied ? "var(--danger)" : d.selected ? "var(--accent)" : "#8b9bb4",
          strokeWidth: d.selected ? 2.3 : 1.4,
          strokeDasharray: denied ? "5 5" : undefined,
        }}
      />
      {d.pulse && !denied && (
        <path
          key={d.sequence}
          d={path}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={3}
          className="xray-message-pulse"
        />
      )}
      <EdgeLabelRenderer>
        <button
          className={`xray-route-label nodrag nopan ${denied ? "xray-denied" : ""}`}
          style={{
            transform: `translate(-50%,-50%) translate(${x}px,${y + (props.source === "REFERENCE_MONITOR" ? -16 : 16)}px)`,
          }}
          onClick={d.inspect}
          title={`${d.decision} · ${d.message} · sequence ${d.sequence}`}
          aria-label={`Inspect ${d.decision} route ${props.source} to ${props.target}, ${d.message}, sequence ${d.sequence}`}
        >
          {denied ? "⊘ DENIED" : "✓"}
          <span>#{d.sequence}</span>
        </button>
      </EdgeLabelRenderer>
    </>
  );
}
function TrustRegion({ data }: NodeProps) {
  return <span>{String(data.label ?? "")}</span>;
}
const nodeTypes = { xray: WorkloadNode, group: TrustRegion };
const edgeTypes = { message: MessageEdge };
const positions: Record<Actor, { x: number; y: number }> = {
  RED_RUNNER: { x: 25, y: 210 },
  REFERENCE_MONITOR: { x: 250, y: 210 },
  BLUE_INPUT_GUARD: { x: 475, y: 20 },
  MODEL_WORKER: { x: 700, y: 20 },
  BLUE_OUTPUT_GUARD: { x: 475, y: 210 },
  EVIDENCE_COLLECTOR: { x: 700, y: 210 },
};
export function XrayCanvas({
  state,
  correlation,
  selected,
  inspect,
  eventSequence,
  provider,
  pulseSequence,
  onRoute,
  humanDomains = false,
}: {
  humanDomains?: boolean;
  state: Engine;
  correlation: string | null;
  selected: Actor | null;
  inspect: (a: Actor) => void;
  eventSequence: number;
  provider: string;
  pulseSequence: number;
  onRoute: (sequence: number) => void;
}) {
  const reduced = useReducedMotion();
  // Controlled nodes must retain React Flow's measured dimensions across evidence updates.
  const [measured, setMeasured] = useState<Record<string, { width: number; height: number }>>({});
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setMeasured((previous) => {
      let next = previous;
      for (const change of changes) {
        if (change.type !== "dimensions" || !change.dimensions) continue;
        const size = change.dimensions;
        if (
          previous[change.id]?.width === size.width &&
          previous[change.id]?.height === size.height
        )
          continue;
        if (next === previous) next = { ...previous };
        next[change.id] = size;
      }
      return next;
    });
  }, []);
  const nodes = useMemo(() => {
    const views = nodeViews(state, correlation);
    const trace = correlation ? state.traces[correlation] : null;
    const groups: Node[] = [
      {
        id: "domain-red",
        type: "group",
        position: { x: 5, y: 165 },
        style: { width: 215, height: 205 },
        data: { label: "RED · RESTRICTED WORKLOAD" },
        className: "xray-region xray-region-red",
        selectable: false,
      },
      {
        id: "domain-trusted",
        type: "group",
        position: { x: 230, y: 165 },
        style: { width: 215, height: 205 },
        data: { label: "TRUSTED CONTROL / STORAGE" },
        className: "xray-region xray-region-trusted",
        selectable: false,
      },
      {
        id: "domain-blue",
        type: "group",
        position: { x: 455, y: -25 },
        style: { width: 215, height: 395 },
        data: { label: "BLUE · ONE CONTAINER, TWO STAGES" },
        className: "xray-region xray-region-blue",
        selectable: false,
      },
      {
        id: "domain-model",
        type: "group",
        position: { x: 680, y: -25 },
        style: { width: 215, height: 205 },
        data: { label: "MODEL · RESTRICTED WORKLOAD" },
        className: "xray-region xray-region-model",
        selectable: false,
      },
    ];
    if (humanDomains)
      groups.push(
        {
          id: "human-red",
          type: "group",
          position: { x: 5, y: -25 },
          style: { width: 215, height: 155 },
          data: { label: "RED HUMAN · PRIVATE SOURCE / NOT A WORKLOAD" },
          className: "xray-region xray-region-red",
          selectable: false,
        },
        {
          id: "human-blue",
          type: "group",
          position: { x: 230, y: -25 },
          style: { width: 215, height: 155 },
          data: { label: "BLUE HUMAN · PRIVATE POLICY / NOT A WORKLOAD" },
          className: "xray-region xray-region-blue",
          selectable: false,
        },
      );
    groups.push({
      id: "domain-evidence",
      type: "group",
      position: { x: 680, y: 165 },
      style: { width: 215, height: 205 },
      data: { label: "PERMITTED EVIDENCE · READ ONLY" },
      className: "xray-region xray-region-trusted",
      selectable: false,
    });
    const workload: XNode[] = actors.map((a) => ({
      id: a,
      type: "xray",
      position: positions[a],
      style: { width: 175 },
      measured: measured[a],
      data: {
        actor: a,
        ...views[a],
        selected: selected === a,
        physical:
          a === "REFERENCE_MONITOR"
            ? "Logical mediation service"
            : a === "EVIDENCE_COLLECTOR"
              ? "Recorded projection"
              : state.physical === "Not recorded"
                ? "Provisioning evidence unavailable"
                : state.physical,
        inspect,
        skipped: trace?.skipped ?? false,
        provider,
      },
    }));
    return [...groups.map((group) => ({ ...group, measured: measured[group.id] })), ...workload];
  }, [state, correlation, selected, inspect, provider, measured, humanDomains]);
  const edges = useMemo(
    () =>
      routesFor(state, correlation).map((route): XEdge => ({
        id: route.id,
        source: route.source,
        target: route.target,
        sourceHandle: positions[route.source].x > positions[route.target].x ? "out-left" : "out",
        targetHandle: positions[route.source].x > positions[route.target].x ? "in-right" : "in",
        type: "message",
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: route.decision === "DENY" ? "#a83c4d" : "#7486a4",
        },
        data: {
          ...route,
          selected: route.sequence === eventSequence,
          pulse: !reduced && route.sequence === pulseSequence,
          message: route.message,
          inspect: () => onRoute(route.sequence),
        },
      })),
    [state, correlation, eventSequence, pulseSequence, reduced, onRoute],
  );
  return (
    <div className="xray-canvas-wrapper">
      <div className="xray-mobile-actors" aria-label="Accessible execution overview">
        {actors.map((a) => (
          <button
            key={a}
            onClick={() => inspect(a)}
            aria-label={`Inspect ${descriptions[a].title} overview`}
          >
            <strong>{descriptions[a].title}</strong>
            <small>{nodeViews(state, correlation)[a].status}</small>
          </button>
        ))}
      </div>
      <div className="xray-canvas" data-testid="xray-canvas">
        <ReactFlow
          nodes={nodes}
          onNodesChange={onNodesChange}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={{ padding: 0.12 }}
          minZoom={0.1}
          maxZoom={1.6}
          nodesConnectable={false}
          nodesDraggable={false}
          edgesReconnectable={false}
          elementsSelectable={false}
          aria-label="Recorded logical execution topology"
          proOptions={{ hideAttribution: false }}
        >
          <RecordedGraphFit />
          <Background color="#dce3ee" gap={24} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <div className="xray-canvas-legend">
        <span>
          <i className="xray-legend-observed" />
          Observed application routes
        </span>
        <span>Network controls: inspect recorded probes</span>
      </div>
    </div>
  );
}
