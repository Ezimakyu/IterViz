import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import type { ContractNode } from "../types/contract";
import { useContractStore } from "../state/contract";
import { type Tier, TIER_SIZE } from "../utils/hierarchy";

export interface NodeCardData {
  node: ContractNode;
  tier: Tier;
}

const KIND_RING: Record<ContractNode["kind"], string> = {
  service: "ring-sky-400/60",
  store: "ring-emerald-400/60",
  external: "ring-fuchsia-400/60",
  ui: "ring-amber-400/60",
  job: "ring-indigo-400/60",
  interface: "ring-slate-300/60",
};

const TIER_TEXT_SIZE: Record<Tier, string> = {
  core: "text-[15px]",
  feature: "text-sm",
  child: "text-[11px]",
  orphan: "text-[11px]",
};

const TIER_RING_WIDTH: Record<Tier, string> = {
  core: "ring-[3px]",
  feature: "ring-2",
  child: "ring-1",
  orphan: "ring-1",
};

function confidenceColor(confidence: number): string {
  if (confidence < 0.5) return "bg-red-500";
  if (confidence < 0.8) return "bg-yellow-400";
  return "bg-green-500";
}

function NodeCardImpl({ id, data, selected }: NodeProps<NodeCardData>) {
  const { node, tier } = data;
  const confidencePct = Math.round(node.confidence * 100);
  const selectedNodeId = useContractStore((s) => s.selectedNodeId);
  const isSpotlight = selectedNodeId === id;
  const size = TIER_SIZE[tier];

  return (
    <div
      className={[
        "relative flex flex-col justify-center rounded-full border bg-slate-100 text-slate-900 shadow-md transition",
        tier === "child" || tier === "orphan" ? "px-3 py-1.5" : "px-5 py-2",
        KIND_RING[node.kind],
        TIER_RING_WIDTH[tier],
        selected || isSpotlight
          ? "border-sky-500 shadow-sky-500/30"
          : "border-slate-400",
      ].join(" ")}
      style={{ width: size.width, height: size.height }}
      data-testid={`node-card-${node.id}`}
      data-tier={tier}
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
        <h3
          className={`truncate text-center font-semibold leading-tight ${TIER_TEXT_SIZE[tier]}`}
        >
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
