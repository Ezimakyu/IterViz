import { useMemo } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Edge,
  type EdgeTypes,
  type Node,
  type NodeTypes,
} from "reactflow";
import "reactflow/dist/style.css";
import type { Contract } from "../types/contract";
import { layoutGraph } from "../utils/layout";
import { NodeCard } from "./NodeCard";
import { EdgeLabel, type EdgeData } from "./EdgeLabel";

const nodeTypes: NodeTypes = { card: NodeCard };
const edgeTypes: EdgeTypes = { labeled: EdgeLabel };

export interface GraphProps {
  contract: Contract;
}

export function Graph({ contract }: GraphProps) {
  const { nodes, edges } = useMemo(() => {
    const rfNodes: Node[] = contract.nodes.map((n) => ({
      id: n.id,
      type: "card",
      data: n,
      position: { x: 0, y: 0 },
    }));
    const rfEdges: Edge<EdgeData>[] = contract.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: "labeled",
      data: { edge: e },
    }));
    return layoutGraph(rfNodes, rfEdges, {
      rankdir: "TB",
      nodesep: 80,
      ranksep: 100,
    });
  }, [contract]);

  return (
    <ReactFlow
      // `key` forces React Flow to remount + re-fit when the contract changes,
      // which is the simplest way to guarantee the new layout is centered.
      key={contract.meta?.id ?? `${nodes.length}:${edges.length}`}
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      proOptions={{ hideAttribution: true }}
      minZoom={0.2}
      maxZoom={1.5}
    >
      <Background
        variant={BackgroundVariant.Dots}
        gap={24}
        size={1}
        color="#1f2540"
      />
      <Controls position="bottom-right" showInteractive={false} />
      <MiniMap
        pannable
        zoomable
        nodeColor="#cbd5e1"
        maskColor="rgba(11, 16, 32, 0.7)"
      />
    </ReactFlow>
  );
}
