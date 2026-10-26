"use client";
import { useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useReducedMotion } from "motion/react";
import {
  ArrowDownRight,
  ArrowRight,
  Box,
  ChevronRight,
  Cpu,
  Crosshair,
  Fingerprint,
  Info,
  LockKeyhole,
  Pause,
  Play,
  RotateCcw,
  ShieldCheck,
  Workflow,
  X,
} from "lucide-react";
import { scenarios, type DomainId, type ScenarioId } from "@/lib/scenarios";
import { roleLabels } from "@/lib/auth-types";
import { useAuth } from "./auth-provider";
import { Badge, Button } from "./ui";
import "@xyflow/react/dist/style.css";
const domains: Record<
  DomainId,
  {
    title: string;
    label: string;
    description: string;
    classification: string;
    owner: string;
    icon: typeof Cpu;
    scope: string;
  }
> = {
  red: {
    title: "Red Runner",
    label: "ADVERSARIAL DOMAIN",
    description: "Represents scoped adversarial requests through the broker boundary.",
    classification: "RED CONFIDENTIAL",
    owner: "Red operator",
    icon: Crosshair,
    scope: "Attack artifacts are restricted to their Red owner.",
  },
  monitor: {
    title: "Reference Monitor",
    label: "TRUSTED CONTROL PLANE",
    description: "Represents default-deny mediation of evaluation messages.",
    classification: "TRUSTED INFRASTRUCTURE",
    owner: "Trusted service",
    icon: Workflow,
    scope: "This diagram is illustrative; inspect recorded Reference Monitor decisions in X-Ray.",
  },
  blue: {
    title: "Sealed Blue Defence",
    label: "DEFENSIVE DOMAIN",
    description: "Represents approved defensive logic with protected private state.",
    classification: "BLUE CONFIDENTIAL",
    owner: "Blue operator",
    icon: ShieldCheck,
    scope: "Private content is owner-only; sealed content is restricted even from its operator.",
  },
  model: {
    title: "Client LLM",
    label: "INFERENCE DOMAIN",
    description: "Represents controlled inference with explicit context and scoped credentials.",
    classification: "EPHEMERAL CONTEXT",
    owner: "Model service",
    icon: Cpu,
    scope: "This illustration launches no inference or cache-isolation experiment.",
  },
  evidence: {
    title: "Evidence Collector",
    label: "AUDIT DOMAIN",
    description: "Represents permitted metadata collection and independently verifiable snapshots.",
    classification: "AUDITOR APPROVED",
    owner: "Auditor",
    icon: Fingerprint,
    scope: "Scenario fixtures are unsigned. Inspect real signed snapshots in Proof Vault.",
  },
};
type DomainNode = Node<
  { domain: DomainId; active: boolean; selected: boolean; inspect: () => void },
  "securityDomain"
>;
function SecurityDomain({ data }: NodeProps<DomainNode>) {
  const domain = domains[data.domain];
  const Icon = domain.icon;
  return (
    <button
      type="button"
      className={`security-node security-node-${data.domain} ${data.selected ? "node-selected" : ""} ${data.active ? "node-sim-active" : ""}`}
      onClick={data.inspect}
      aria-label={`Inspect ${domain.title}`}
      aria-pressed={data.selected}
    >
      <Handle type="target" position={Position.Left} />
      <Handle id="return" type="source" position={Position.Bottom} />
      <Handle id="return-target" type="target" position={Position.Bottom} />
      <Handle id="direct" type="source" position={Position.Top} />
      <Handle id="inbound" type="target" position={Position.Top} />
      <div className="security-node-top">
        <span className="security-node-icon">
          <Icon size={22} />
        </span>
        <span className="node-runtime">
          <span />
          REFERENCE
        </span>
      </div>
      <strong>{domain.title}</strong>
      <span className="node-classification">{domain.classification}</span>
      <span className="node-description">{domain.description}</span>
      <span className="node-inspect">
        Inspect boundary
        <ChevronRight size={13} />
      </span>
      <Handle type="source" position={Position.Right} />
    </button>
  );
}
const nodeTypes = { securityDomain: SecurityDomain };
const positions: Record<DomainId, { x: number; y: number }> = {
  red: { x: 30, y: 100 },
  monitor: { x: 310, y: 100 },
  blue: { x: 590, y: 100 },
  model: { x: 870, y: 100 },
  evidence: { x: 590, y: 420 },
};
const baseline: Edge[] = [
  { id: "red-monitor", source: "red", target: "monitor" },
  { id: "monitor-blue", source: "monitor", target: "blue" },
  { id: "blue-model", source: "blue", target: "model" },
  {
    id: "model-blue",
    source: "model",
    target: "blue",
    sourceHandle: "return",
    targetHandle: "return-target",
  },
  {
    id: "blue-monitor",
    source: "blue",
    target: "monitor",
    sourceHandle: "return",
    targetHandle: "return-target",
  },
  {
    id: "monitor-red",
    source: "monitor",
    target: "red",
    sourceHandle: "return",
    targetHandle: "return-target",
  },
  { id: "monitor-evidence", source: "monitor", target: "evidence", sourceHandle: "return" },
];
export function SecurityTopology({ compact = false }: { compact?: boolean }) {
  const { session } = useAuth();
  const reducedMotion = useReducedMotion();
  const [scenario, setScenario] = useState<ScenarioId>("authorized");
  const [cursor, setCursor] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<DomainId | null>(null);
  const fixture = scenarios[scenario];
  const step = cursor >= 0 ? fixture.steps[cursor] : null;
  useEffect(() => {
    if (!playing || cursor >= fixture.steps.length - 1) return;
    const timer = setInterval(() => {
      setCursor((value) => {
        if (value >= fixture.steps.length - 1) {
          return value;
        }
        return value + 1;
      });
    }, 1100);
    return () => clearInterval(timer);
  }, [playing, fixture, cursor]);
  const completed = cursor === fixture.steps.length - 1;
  const nodes = useMemo(() => {
    const boundaries: Node[] = (Object.keys(domains) as DomainId[]).map((domain) => ({
      id: `boundary-${domain}`,
      position: { x: positions[domain].x - 12, y: positions[domain].y - 45 },
      data: { label: domains[domain].label },
      style: {
        width: 254,
        height: 269,
        border: `1px dashed ${domain === "red" ? "#efcbd1" : domain === "blue" ? "#c5e4d5" : "#d4cdec"}`,
        background: domain === "monitor" ? "#f0edfb" : "#f3f5fa",
        borderRadius: 12,
        color: "#596980",
        fontSize: 10,
        paddingTop: 11,
      },
      selectable: false,
      draggable: false,
      focusable: false,
      connectable: false,
    }));
    const actual: DomainNode[] = (Object.keys(domains) as DomainId[]).map((domain) => ({
      id: domain,
      type: "securityDomain",
      position: positions[domain],
      data: {
        domain,
        active: Boolean(
          step && (step.route.startsWith(domain + "-") || step.route.endsWith("-" + domain)),
        ),
        selected: selected === domain,
        inspect: () => setSelected(domain),
      },
      focusable: false,
    }));
    return [...boundaries, ...actual];
  }, [selected, step]);
  const edges = useMemo(() => {
    const routes = [...baseline];
    if (scenario === "forbidden")
      routes.push({
        id: "red-blue-denied",
        source: "red",
        target: "blue",
        sourceHandle: "direct",
        targetHandle: "inbound",
        type: "default",
        label: "DENIED · SIMULATED",
      });
    return routes.map((route) => {
      const active = step?.route === route.id;
      const denied = route.id.includes("denied");
      return {
        ...route,
        type: route.type || "smoothstep",
        animated: active && !reducedMotion,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: denied ? "#a83c4d" : active ? "#5546ad" : "#8b9bb4",
          width: 16,
          height: 16,
        },
        style: {
          stroke: denied ? "#a83c4d" : active ? "#5546ad" : "#8b9bb4",
          strokeWidth: active ? 2.4 : 1.2,
          strokeDasharray: denied ? "6 4" : "4 4",
          opacity: active || denied ? 1 : 0.65,
        },
        labelStyle: { fill: "#a83c4d", fontSize: 10 },
        labelBgStyle: { fill: "#fff1f2", fillOpacity: 1 },
        zIndex: denied ? 5 : 1,
      };
    });
  }, [scenario, step, reducedMotion]);
  const domain = selected ? domains[selected] : null;
  function changeScenario(value: ScenarioId) {
    setScenario(value);
    setCursor(-1);
    setPlaying(false);
  }
  function run() {
    if (completed || cursor < 0) {
      setCursor(0);
      setPlaying(true);
    } else setPlaying((value) => !value);
  }
  return (
    <div className={`security-topology ${compact ? "security-topology-compact" : ""}`}>
      <div className="scenario-toolbar">
        <div>
          <Badge tone="amber" dot>
            SIMULATED SECURITY SCENARIO
          </Badge>
          <p>Explore the intended policy. No runtime enforcement is active.</p>
        </div>
        <span className="simulation-watermark">
          <Box size={14} />
          FIXTURE-DRIVEN · NO WORKLOADS
        </span>
      </div>
      <div className="scenario-options" aria-label="Security scenario">
        {(Object.keys(scenarios) as ScenarioId[]).map((key) => (
          <button
            key={key}
            className="scenario-option"
            aria-pressed={scenario === key}
            onClick={() => changeScenario(key)}
          >
            <span>{scenarios[key].letter}</span>
            <strong>{scenarios[key].title}</strong>
            <ChevronRight size={15} />
          </button>
        ))}
      </div>
      <div className="domain-shortcuts" aria-label="Quick boundary inspection">
        {(Object.keys(domains) as DomainId[]).map((id) => {
          const Icon = domains[id].icon;
          return (
            <button
              key={id}
              aria-label={`Select ${domains[id].title} boundary`}
              aria-pressed={selected === id}
              onClick={() => setSelected(id)}
            >
              <Icon size={13} />
              {
                {
                  red: "Red",
                  monitor: "Monitor",
                  blue: "Blue",
                  model: "LLM",
                  evidence: "Evidence",
                }[id]
              }
            </button>
          );
        })}
      </div>
      <div className="topology-workbench">
        <div className="security-canvas" role="region" aria-label="Illustrative security topology">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.13 }}
            minZoom={0.25}
            maxZoom={1.5}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            nodesFocusable={false}
            edgesFocusable={false}
            proOptions={{ hideAttribution: false }}
            colorMode="dark"
          >
            <Background gap={22} color="#dce3ee" size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
          <span className="canvas-design-label">NEXUS / PROPOSED TRUST BOUNDARIES</span>
          <div className="canvas-legend">
            <span>
              <i />
              Planned route
            </span>
            <span>
              <i className="denied-legend" />
              Denied in simulation
            </span>
          </div>
        </div>
        {domain && selected && (
          <aside
            className={`node-inspector inspector-${selected}`}
            aria-label="Boundary inspection"
          >
            <div className="inspector-heading">
              <span>BOUNDARY INSPECTOR</span>
              <button
                className="icon-button"
                aria-label="Close boundary inspection"
                onClick={() => setSelected(null)}
              >
                <X size={17} />
              </button>
            </div>
            <span className="inspector-icon">
              <domain.icon size={29} />
            </span>
            <h3>{domain.title}</h3>
            <Badge>{domain.classification}</Badge>
            <p>{domain.description}</p>
            <dl>
              <div>
                <dt>Operational status</dt>
                <dd>Illustrative boundary</dd>
              </div>
              <div>
                <dt>Responsible domain</dt>
                <dd>{domain.owner}</dd>
              </div>
              <div>
                <dt>Your operator role</dt>
                <dd>{roleLabels[session.user.role]}</dd>
              </div>
              <div>
                <dt>Container enforcement</dt>
                <dd>Not established by this illustration</dd>
              </div>
            </dl>
            <div className="inspector-policy">
              <LockKeyhole size={16} />
              <p>{domain.scope}</p>
            </div>
            <div className="inspector-app-boundary">
              <ShieldCheck size={15} />
              <span>Application authorization is enforced separately by the API.</span>
            </div>
          </aside>
        )}
      </div>
      <div className="scenario-playback">
        <div className="scenario-player-actions">
          <Button variant="primary" onClick={run}>
            {playing && !completed ? <Pause size={14} /> : <Play size={14} />}
            {playing && !completed
              ? "Pause scenario"
              : completed
                ? "Replay scenario"
                : "Run scenario"}
          </Button>
          <button
            className="icon-button"
            aria-label="Reset scenario"
            onClick={() => {
              setCursor(-1);
              setPlaying(false);
            }}
          >
            <RotateCcw size={16} />
          </button>
          <Button
            onClick={() => {
              setPlaying(false);
              setCursor((value) => Math.min(value + 1, fixture.steps.length - 1));
            }}
            disabled={completed}
          >
            Next step
            <ArrowRight size={14} />
          </Button>
        </div>
        <span className="scenario-step-count">
          {cursor < 0
            ? "Ready to explore"
            : `STEP ${String(cursor + 1).padStart(2, "0")} / ${String(fixture.steps.length).padStart(2, "0")}`}
        </span>
      </div>
      <div
        className={`scenario-outcome ${step?.event.permitted_metadata.decision === "DENY" ? "scenario-denied" : ""}`}
        role="status"
      >
        <span className="scenario-outcome-icon">
          {step?.event.permitted_metadata.decision === "DENY" ? (
            <LockKeyhole size={21} />
          ) : (
            <ArrowDownRight size={21} />
          )}
        </span>
        <div>
          <strong>{step ? step.title : fixture.title}</strong>
          <p>{step ? step.description : fixture.description}</p>
          {completed && <p className="scenario-completed">{fixture.outcome}</p>}
        </div>
        <Badge tone={step?.event.permitted_metadata.decision === "DENY" ? "red" : "neutral"}>
          {step?.event.permitted_metadata.decision || "NOT STARTED"} · SIMULATED
        </Badge>
      </div>
      <div className="scenario-events">
        <div className="scenario-event-heading">
          <span>SCENARIO EVENT TRACE</span>
          <span>Typed fixture events · never persisted as runtime evidence</span>
        </div>
        {cursor < 0 ? (
          <div className="scenario-events-empty">
            Run the scenario or advance one step to inspect its deterministic event trace.
          </div>
        ) : (
          fixture.steps.slice(0, cursor + 1).map((item, index) => (
            <div key={item.event.event_id} className="scenario-event">
              <span className="event-step">{String(index + 1).padStart(2, "0")}</span>
              <span className={`event-decision event-${item.event.permitted_metadata.decision}`}>
                {item.event.permitted_metadata.decision}
              </span>
              <strong>{item.event.event_type}</strong>
              <span className="event-path">
                {item.event.source.replaceAll("_", " ")}
                <ArrowRight size={12} />
                {item.event.destination.replaceAll("_", " ")}
              </span>
              <span className="event-sim-label">SIMULATED</span>
            </div>
          ))
        )}
      </div>
      <div className="topology-security-note">
        <Info size={14} />
        <span>
          This illustration does not launch workloads, enforce network policy or run inference. This
          canvas is not a security test result.
        </span>
      </div>
    </div>
  );
}
