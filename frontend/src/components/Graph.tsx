import { useMemo, useRef } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlowProvider,
  type EdgeMouseHandler,
  type EdgeTypes,
  type NodeMouseHandler,
  type NodeTypes,
} from "reactflow";
import "reactflow/dist/style.css";
import type { Contract } from "../types/contract";
import { NodeCard } from "./NodeCard";
import { EdgeLabel } from "./EdgeLabel";
import { NodeDetailsPopup } from "./NodeDetailsPopup";
import { EdgeDetailsPopup } from "./EdgeDetailsPopup";
import { NodePopupManager } from "./NodePopupManager";
import { SubgraphView } from "./SubgraphView";
import { useForceLayout } from "../hooks/useForceLayout";
import { useContractStore } from "../state/contract";
import { useSubgraphStore } from "../state/subgraph";
import { buildHierarchy } from "../utils/hierarchy";
import { API, isApiError } from "../api/client";

const nodeTypes: NodeTypes = { oval: NodeCard };
const edgeTypes: EdgeTypes = { floating: EdgeLabel };

export interface GraphProps {
  contract: Contract;
}

export function Graph(props: GraphProps) {
  return (
    <ReactFlowProvider>
      <GraphInner {...props} />
    </ReactFlowProvider>
  );
}

function GraphInner({ contract }: GraphProps) {
  const {
    selectedNodeId,
    selectedEdgeId,
    toggleSelectedNode,
    toggleSelectedEdge,
    clearSelection,
  } = useContractStore();
  const sessionId = useContractStore((s) => s.sessionId);
  const previousContract = useContractStore((s) => s.previousContract);
  const provenanceView = useContractStore((s) => s.provenanceView);
  const toggleProvenanceView = useContractStore(
    (s) => s.toggleProvenanceView,
  );
  const activeParentNodeId = useSubgraphStore((s) => s.activeParentNodeId);
  const setActiveSubgraph = useSubgraphStore((s) => s.setActiveSubgraph);
  const upsertSubgraph = useSubgraphStore((s) => s.upsertSubgraph);
  const subgraphCache = useSubgraphStore((s) => s.subgraphs);
  // M5's ControlBar already opens the session WebSocket via
  // `useWebSocketStore.connect`; subgraph events are routed by the same
  // store handler -- no extra subscription needed here.

  const userEditedCount = useMemo(
    () =>
      contract.nodes.filter((n) => n.decided_by === "user").length,
    [contract],
  );

  const hierarchy = useMemo(() => buildHierarchy(contract), [contract]);

  // Diff bookkeeping: which nodes/edges changed since the previous contract?
  const diff = useMemo(() => {
    if (!previousContract) {
      return { newNodeIds: new Set<string>(), changedNodeIds: new Set<string>() };
    }
    const prevById = new Map(
      previousContract.nodes.map((n) => [n.id, n] as const),
    );
    const newNodeIds = new Set<string>();
    const changedNodeIds = new Set<string>();
    for (const n of contract.nodes) {
      const prev = prevById.get(n.id);
      if (!prev) {
        newNodeIds.add(n.id);
        continue;
      }
      if (
        prev.confidence !== n.confidence ||
        prev.decided_by !== n.decided_by ||
        prev.name !== n.name
      ) {
        changedNodeIds.add(n.id);
      }
    }
    return { newNodeIds, changedNodeIds };
  }, [contract, previousContract]);

  // Uncontrolled React Flow: the force simulation drives node positions
  // via `useReactFlow().setNodes`, so we don't own node state here.
  useForceLayout(contract, {
    boostedId: selectedNodeId ?? null,
    hierarchy,
  });

  // Tracks the most recently clicked node id so a slow generateSubgraph
  // response from an earlier click can't stomp the active subgraph after
  // the user has already clicked a different node.
  const latestClickRef = useRef<string | null>(null);

  const onNodeClick: NodeMouseHandler = async (event, rfNode) => {
    event.stopPropagation();
    if (!sessionId) {
      toggleSelectedNode(rfNode.id);
      return;
    }

    latestClickRef.current = rfNode.id;

    // Left-click enters the implementation subgraph for the node.
    // Generate it lazily on the first click.
    if (!subgraphCache[rfNode.id]) {
      const result = await API.generateSubgraph(sessionId, rfNode.id);
      if (latestClickRef.current !== rfNode.id) return;
      if (!isApiError(result)) {
        upsertSubgraph(result.subgraph);
      } else {
        toggleSelectedNode(rfNode.id);
        return;
      }
    }
    if (latestClickRef.current !== rfNode.id) return;
    setActiveSubgraph(rfNode.id);
  };

  const onEdgeClick: EdgeMouseHandler = (event, edge) => {
    event.stopPropagation();
    toggleSelectedEdge(edge.id);
  };

  const selectedNode = selectedNodeId
    ? contract.nodes.find((n) => n.id === selectedNodeId) ?? null
    : null;
  const selectedEdge = selectedEdgeId
    ? contract.edges.find((e) => e.id === selectedEdgeId) ?? null
    : null;
  const edgeEndpoints = selectedEdge
    ? {
        source:
          contract.nodes.find((n) => n.id === selectedEdge.source)?.name ??
          selectedEdge.source,
        target:
          contract.nodes.find((n) => n.id === selectedEdge.target)?.name ??
          selectedEdge.target,
      }
    : null;

  return (
    <div className="relative h-full w-full">
      <ReactFlow
        defaultNodes={[]}
        defaultEdges={[]}
        onNodeClick={onNodeClick}
        onEdgeClick={onEdgeClick}
        onPaneClick={clearSelection}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultViewport={{ x: 200, y: 360, zoom: 1 }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.2}
        maxZoom={1.8}
        nodesDraggable
        panOnDrag
        zoomOnDoubleClick={false}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={24}
          size={1}
          color="#1f2540"
        />
        <Controls position="bottom-left" showInteractive={false} />
      </ReactFlow>

      {(diff.newNodeIds.size > 0 || diff.changedNodeIds.size > 0) && (
        <div className="pointer-events-none absolute right-3 top-3 rounded border border-yellow-500/40 bg-yellow-500/10 px-2 py-1 text-[11px] text-yellow-300">
          {diff.newNodeIds.size} new · {diff.changedNodeIds.size} changed
        </div>
      )}

      {/* M4: provenance view toggle. Highlights only user-edited nodes. */}
      <div className="absolute left-3 top-3 flex flex-col items-start gap-2">
        <button
          type="button"
          onClick={toggleProvenanceView}
          data-testid="provenance-view-toggle"
          aria-pressed={provenanceView}
          className={`rounded border px-2 py-1 text-[11px] font-medium uppercase tracking-wide transition ${
            provenanceView
              ? "border-blue-400 bg-blue-500/20 text-blue-200"
              : "border-slate-600 bg-slate-800/70 text-slate-300 hover:border-blue-400 hover:text-blue-200"
          }`}
        >
          Provenance view {provenanceView ? "on" : "off"}
        </button>
        {provenanceView && (
          <div className="pointer-events-none rounded border border-slate-600/60 bg-slate-900/80 px-2 py-1 text-[10px] leading-tight text-slate-200 shadow">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-blue-400" />
              <span>User-edited ({userEditedCount})</span>
            </div>
            <div className="mt-0.5 flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-slate-400 opacity-60" />
              <span>Other</span>
            </div>
          </div>
        )}
      </div>

      {selectedNode && (
        <NodeDetailsPopup
          node={selectedNode}
          onClose={() => toggleSelectedNode(selectedNode.id)}
        />
      )}
      {selectedEdge && edgeEndpoints && (
        <EdgeDetailsPopup
          edge={selectedEdge}
          sourceName={edgeEndpoints.source}
          targetName={edgeEndpoints.target}
          onClose={() => toggleSelectedEdge(selectedEdge.id)}
        />
      )}

      {activeParentNodeId && (
        <div className="absolute inset-0 z-30 bg-canvas">
          <SubgraphView
            parentNodeId={activeParentNodeId}
            onBack={() => setActiveSubgraph(null)}
          />
        </div>
      )}

      <NodePopupManager />
    </div>
  );
}
