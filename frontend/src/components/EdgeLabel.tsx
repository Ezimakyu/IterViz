import { useCallback } from "react";
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  useStore,
  type EdgeProps,
  type ReactFlowState,
} from "reactflow";
import type { ContractEdge } from "../types/contract";
import { getEdgeParams } from "../utils/floatingEdges";
import { EDGE_KIND_COLOR } from "../utils/edgeKind";
import { useContractStore } from "../state/contract";

export interface EdgeData {
  edge: ContractEdge;
}

export function EdgeLabel(props: EdgeProps<EdgeData>) {
  const { id, source, target, data, markerEnd } = props;
  const selectedEdgeId = useContractStore((s) => s.selectedEdgeId);
  const toggleSelectedEdge = useContractStore((s) => s.toggleSelectedEdge);

  const sourceNode = useStore(
    useCallback((s: ReactFlowState) => s.nodeInternals.get(source), [source]),
  );
  const targetNode = useStore(
    useCallback((s: ReactFlowState) => s.nodeInternals.get(target), [target]),
  );

  if (!sourceNode || !targetNode) return null;

  const { sx, sy, tx, ty, sourcePos, targetPos } = getEdgeParams(
    sourceNode,
    targetNode,
  );
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX: sx,
    sourceY: sy,
    sourcePosition: sourcePos,
    targetX: tx,
    targetY: ty,
    targetPosition: targetPos,
  });

  const edge = data?.edge;
  const color = edge ? EDGE_KIND_COLOR[edge.kind] : "#94a3b8";
  const isSelected = selectedEdgeId === id;

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          stroke: color,
          strokeWidth: isSelected ? 2.6 : 1.5,
          opacity: isSelected ? 1 : 0.85,
        }}
      />
      {edge && (
        <EdgeLabelRenderer>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              toggleSelectedEdge(id);
            }}
            className="group pointer-events-auto absolute cursor-pointer select-none rounded-full border bg-slate-900/90 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-100 shadow transition hover:scale-[1.05]"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              borderColor: color,
              color: isSelected ? "#0b1020" : "#e6e8ef",
              background: isSelected ? color : "rgba(17, 22, 42, 0.9)",
            }}
            aria-label={`${edge.kind} edge, click to ${
              isSelected ? "hide" : "show"
            } details`}
          >
            {edge.kind}
          </button>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
