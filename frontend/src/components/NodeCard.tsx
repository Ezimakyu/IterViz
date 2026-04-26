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

const STATUS_RING: Record<
  NonNullable<ContractNode["status"]>,
  string
> = {
  drafted: "",
  in_progress: "!ring-yellow-400 ring-[4px] animate-pulse",
  implemented: "!ring-emerald-500 ring-[4px]",
  failed: "!ring-red-500 ring-[4px]",
};

function NodeCardImpl({ id, data, selected }: NodeProps<NodeCardData>) {
  const { node, tier } = data;
  const confidencePct = Math.round(node.confidence * 100);
  const selectedNodeId = useContractStore((s) => s.selectedNodeId);
  const previousContract = useContractStore((s) => s.previousContract);
  const nodeAgents = useContractStore((s) => s.nodeAgents);
  const isSpotlight = selectedNodeId === id;
  const size = TIER_SIZE[tier];
  const statusRing = STATUS_RING[node.status] ?? "";
  const agentInfo = nodeAgents.get(id);

  // Diff highlight: yellow ring/badge when this node changed (or is new).
  const prev = previousContract?.nodes.find((n) => n.id === id);
  const isNew = previousContract != null && prev == null;
  const isChanged =
    !isNew &&
    prev != null &&
    (prev.confidence !== node.confidence ||
      prev.decided_by !== node.decided_by ||
      prev.name !== node.name);

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
        isNew || isChanged ? "!ring-yellow-400/80 ring-[3px]" : "",
        statusRing,
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

      {isNew && (
        <span className="absolute -top-2 right-1 rounded bg-yellow-400 px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide text-slate-900">
          NEW
        </span>
      )}
      {agentInfo && (
        <span
          className="absolute -top-2 left-1 max-w-[80%] truncate rounded bg-violet-500 px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white"
          title={`Claimed by ${agentInfo.agentName}`}
        >
          {agentInfo.agentName}
        </span>
      )}
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
