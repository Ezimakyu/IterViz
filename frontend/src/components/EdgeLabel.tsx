import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from "reactflow";
import type { ContractEdge, PayloadSchema } from "../types/contract";

export interface EdgeData {
  edge: ContractEdge;
}

const KIND_COLOR: Record<ContractEdge["kind"], string> = {
  data: "#60a5fa",
  control: "#f59e0b",
  event: "#a78bfa",
  dependency: "#6b7280",
};

function payloadSummary(schema: PayloadSchema | null | undefined): string {
  if (!schema || !schema.properties) return "no payload";
  const fieldCount = Object.keys(schema.properties).length;
  return `${schema.type ?? "object"} with ${fieldCount} field${fieldCount === 1 ? "" : "s"}`;
}

export function EdgeLabel(props: EdgeProps<EdgeData>) {
  const {
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    data,
    markerEnd,
  } = props;

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const edge = data?.edge;
  const color = edge ? KIND_COLOR[edge.kind] : "#94a3b8";
  const summary = edge ? payloadSummary(edge.payload_schema) : "";

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{ stroke: color, strokeWidth: 1.75 }}
      />
      {edge && (
        <EdgeLabelRenderer>
          <div
            className="group pointer-events-auto absolute -translate-x-1/2 -translate-y-1/2"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            <div
              className="cursor-default rounded border border-slate-600 bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-100 shadow"
              style={{ borderColor: color }}
            >
              {edge.kind}
            </div>
            <div className="invisible absolute left-1/2 top-full z-10 mt-1 w-44 -translate-x-1/2 rounded border border-slate-600 bg-slate-900 p-2 text-[10px] leading-snug text-slate-100 shadow-lg group-hover:visible">
              <div className="font-semibold uppercase tracking-wide" style={{ color }}>
                {edge.kind}
              </div>
              {edge.label && <div className="mt-0.5">{edge.label}</div>}
              <div className="mt-0.5 text-slate-300">payload: {summary}</div>
            </div>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
