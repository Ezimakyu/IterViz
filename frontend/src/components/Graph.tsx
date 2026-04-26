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

  const hierarchy = useMemo(() => buildHierarchy(contract), [contract]);

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
        fitView
        fitViewOptions={{ padding: 0.3 }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.2}
        maxZoom={1.8}
        nodesDraggable
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
