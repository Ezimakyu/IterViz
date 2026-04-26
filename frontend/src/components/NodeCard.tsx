import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import type { ContractNode } from "../types/contract";
import { NODE_HEIGHT, NODE_WIDTH } from "../utils/layout";
import { useContractStore } from "../state/contract";

const KIND_RING: Record<ContractNode["kind"], string> = {
  service: "ring-sky-400/60",
  store: "ring-emerald-400/60",
  external: "ring-fuchsia-400/60",
  ui: "ring-amber-400/60",
  job: "ring-indigo-400/60",
  interface: "ring-slate-300/60",
};

function confidenceColor(confidence: number): string {
  if (confidence < 0.5) return "bg-red-500";
  if (confidence < 0.8) return "bg-yellow-400";
  return "bg-green-500";
}

function NodeCardImpl({ id, data, selected }: NodeProps<ContractNode>) {
  const node = data;
  const confidencePct = Math.round(node.confidence * 100);
  const selectedNodeId = useContractStore((s) => s.selectedNodeId);
  const isSpotlight = selectedNodeId === id;

  return (
    <div
      className={[
        "relative flex flex-col justify-center rounded-full border bg-slate-100 px-5 py-2 text-slate-900 shadow-md ring-2 transition",
        KIND_RING[node.kind],
        selected || isSpotlight
          ? "border-sky-500 shadow-sky-500/30"
          : "border-slate-400",
      ].join(" ")}
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
      data-testid={`node-card-${node.id}`}
      title={node.description ?? node.name}
    >
      {/* Invisible centered handles — floating edges ignore side. */}
      <Handle
        type="target"
        position={Position.Top}
        className="!pointer-events-none !border-0 !bg-transparent !opacity-0"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        className="!pointer-events-none !border-0 !bg-transparent !opacity-0"
      />

      <div className="flex items-center justify-center">
        <h3 className="truncate text-sm font-semibold leading-tight text-center">
          {node.name}
        </h3>
      </div>

      <div
        className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-300"
        aria-label={`confidence ${confidencePct}%`}
      >
        <div
          className={`h-full ${confidenceColor(node.confidence)}`}
          style={{ width: `${confidencePct}%` }}
        />
      </div>
    </div>
  );
}

export const NodeCard = memo(NodeCardImpl);
