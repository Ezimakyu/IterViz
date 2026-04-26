import { useMemo } from "react";
import dagre from "dagre";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlowProvider,
  type Edge,
  type Node,
  type EdgeTypes,
  type NodeTypes,
} from "reactflow";
import "reactflow/dist/style.css";
import type {
  ImplementationSubgraph,
  SubgraphEdge,
  SubgraphNode,
  SubgraphNodeStatus,
} from "../types/subgraph";
import { useSubgraphStore } from "../state/subgraph";
import {
  SubgraphNodeCard,
  type SubgraphNodeCardData,
} from "./SubgraphNodeCard";

const nodeTypes: NodeTypes = { sg: SubgraphNodeCard };
const edgeTypes: EdgeTypes = {};

// Match the big-picture node spacing constants (M6 spec §6).
const NODE_WIDTH = 200;
const NODE_HEIGHT = 60;
const NODESEP = 60;
const RANKSEP = 80;

interface SubgraphViewProps {
  parentNodeId: string;
  onBack: () => void;
}

export function SubgraphView({ parentNodeId, onBack }: SubgraphViewProps) {
  return (
    <ReactFlowProvider>
      <SubgraphInner parentNodeId={parentNodeId} onBack={onBack} />
    </ReactFlowProvider>
  );
}

function SubgraphInner({ parentNodeId, onBack }: SubgraphViewProps) {
  const subgraph = useSubgraphStore((s) => s.subgraphs[parentNodeId]);
  const openSubgraphPopup = useSubgraphStore((s) => s.openSubgraphPopup);

  const { nodes, edges } = useMemo(() => {
    if (!subgraph) return { nodes: [] as Node[], edges: [] as Edge[] };
    return buildLaidOutGraph(subgraph, (sgNodeId: string) =>
      openSubgraphPopup(parentNodeId, sgNodeId),
    );
  }, [subgraph, parentNodeId, openSubgraphPopup]);

  return (
    <div className="relative h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        proOptions={{ hideAttribution: true }}
        defaultViewport={{ x: 80, y: 80, zoom: 0.85 }}
        minZoom={0.2}
        maxZoom={1.8}
        nodesDraggable={false}
        panOnDrag
        zoomOnDoubleClick={false}
        fitView
        fitViewOptions={{ padding: 0.2 }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={24}
          size={1}
          color="#1f2540"
        />
        <Controls position="bottom-left" showInteractive={false} />
      </ReactFlow>

      <SubgraphHeader subgraph={subgraph ?? null} onBack={onBack} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header / progress
// ---------------------------------------------------------------------------

const STATUS_BADGE: Record<SubgraphNodeStatus, string> = {
  pending: "border-slate-500 text-slate-200",
  in_progress: "border-yellow-400 text-yellow-200",
  completed: "border-green-400 text-green-200",
  failed: "border-red-400 text-red-200",
};

function SubgraphHeader({
  subgraph,
  onBack,
}: {
  subgraph: ImplementationSubgraph | null;
  onBack: () => void;
}) {
  const total = subgraph?.nodes.length ?? 0;
  const completed = subgraph?.nodes.filter((n) => n.status === "completed").length ?? 0;
  const progressPct = subgraph ? Math.round(subgraph.progress * 100) : 0;

  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-start justify-between gap-3 p-3">
      <button
        type="button"
        onClick={onBack}
        data-testid="subgraph-back-button"
        className="pointer-events-auto inline-flex items-center gap-1.5 rounded border border-slate-600 bg-slate-800/80 px-2.5 py-1 text-[12px] font-medium text-slate-200 hover:border-sky-400 hover:text-sky-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
      >
        <svg
          viewBox="0 0 24 24"
          className="h-3.5 w-3.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M15 18l-6-6 6-6" />
        </svg>
        Back to graph
      </button>

      {subgraph && (
        <div className="pointer-events-auto flex flex-col items-end gap-1 rounded border border-slate-700 bg-slate-900/80 px-3 py-2 text-[11px] text-slate-200 shadow backdrop-blur">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-100">
              {subgraph.parent_node_name}
            </span>
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${STATUS_BADGE[subgraph.status]}`}
            >
              {subgraph.status.replace("_", " ")}
            </span>
          </div>
          <div className="flex items-center gap-2 text-slate-300">
            <span>
              {completed}/{total} tasks done
            </span>
            <div className="h-1.5 w-32 overflow-hidden rounded-full bg-slate-700">
              <div
                className={`h-full ${progressBarColor(subgraph.status)}`}
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <span className="tabular-nums">{progressPct}%</span>
          </div>
        </div>
      )}
    </div>
  );
}

function progressBarColor(status: SubgraphNodeStatus): string {
  switch (status) {
    case "completed":
      return "bg-green-500";
    case "failed":
      return "bg-red-500";
    case "in_progress":
      return "bg-yellow-400";
    default:
      return "bg-slate-400";
  }
}

// ---------------------------------------------------------------------------
// dagre layout
// ---------------------------------------------------------------------------

function buildLaidOutGraph(
  subgraph: ImplementationSubgraph,
  onSelect: (subgraphNodeId: string) => void,
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "TB", nodesep: NODESEP, ranksep: RANKSEP });
  g.setDefaultEdgeLabel(() => ({}));

  for (const node of subgraph.nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of subgraph.edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  const nodes: Node<SubgraphNodeCardData>[] = subgraph.nodes.map(
    (node: SubgraphNode) => {
      const dn = g.node(node.id);
      return {
        id: node.id,
        type: "sg",
        position: dn
          ? { x: dn.x - NODE_WIDTH / 2, y: dn.y - NODE_HEIGHT / 2 }
          : { x: 0, y: 0 },
        data: {
          node,
          parentNodeId: subgraph.parent_node_id,
          onSelect,
        },
      };
    },
  );

  const edges: Edge[] = subgraph.edges.map((edge: SubgraphEdge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: edge.label ?? undefined,
    style: { stroke: "#475569", strokeWidth: 1.5 },
  }));

  return { nodes, edges };
}
