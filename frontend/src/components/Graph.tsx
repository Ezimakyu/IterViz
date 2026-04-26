import { useMemo } from "react";
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
import { useForceLayout } from "../hooks/useForceLayout";
import { useContractStore } from "../state/contract";
import { buildHierarchy } from "../utils/hierarchy";

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
  const previousContract = useContractStore((s) => s.previousContract);

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

  const onNodeClick: NodeMouseHandler = (event, node) => {
    event.stopPropagation();
    toggleSelectedNode(node.id);
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
    </div>
  );
}
