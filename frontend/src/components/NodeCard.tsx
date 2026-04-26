import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import type { ContractNode } from "../types/contract";
import { useContractStore } from "../state/contract";
import { useSubgraphStore } from "../state/subgraph";
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
  const previousContract = useContractStore((s) => s.previousContract);
  const userEditedFields = useContractStore((s) => s.userEditedFields);
  const provenanceView = useContractStore((s) => s.provenanceView);
  const openBigPicturePopup = useSubgraphStore((s) => s.openBigPicturePopup);
  const hasSubgraph = useSubgraphStore((s) => Boolean(s.subgraphs[id]));
  const isSpotlight = selectedNodeId === id;
  const size = TIER_SIZE[tier];

  // Diff highlight: yellow ring/badge when this node changed (or is new).
  const prev = previousContract?.nodes.find((n) => n.id === id);
  const isNew = previousContract != null && prev == null;
  const isChanged =
    !isNew &&
    prev != null &&
    (prev.confidence !== node.confidence ||
      prev.decided_by !== node.decided_by ||
      prev.name !== node.name);

  // M4: provenance highlights. A node is treated as "user-edited" when
  // either the live store recorded an edit this session, or the backend
  // told us the node's provenance is now ``user``.
  const isUserEdited =
    (userEditedFields[id]?.length ?? 0) > 0 || node.decided_by === "user";

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
        isUserEdited ? "!ring-blue-500/80 ring-[3px] shadow-blue-500/30" : "",
        provenanceView && !isUserEdited ? "opacity-60" : "",
      ].join(" ")}
      style={{ width: size.width, height: size.height }}
      data-testid={`node-card-${node.id}`}
      data-tier={tier}
      data-decided-by={node.decided_by ?? "agent"}
      data-user-edited={isUserEdited ? "true" : "false"}
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
      {isUserEdited && !isNew && (
        <span
          className="absolute -top-2 -right-1 rounded bg-blue-500 px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white shadow-sm"
          data-testid={`node-user-badge-${node.id}`}
        >
          USER
        </span>
      )}
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          openBigPicturePopup(node.id);
        }}
        aria-label={`Show details for ${node.name}`}
        data-testid={`node-info-button-${node.id}`}
        className="absolute -top-1 right-0 z-10 flex h-5 w-5 items-center justify-center rounded-full border border-slate-400 bg-white/80 text-[11px] font-semibold text-slate-700 shadow hover:bg-sky-100 hover:text-sky-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
      >
        i
      </button>
      {hasSubgraph && (
        <span
          aria-hidden
          data-testid={`node-subgraph-indicator-${node.id}`}
          className="absolute -bottom-1 -right-1 inline-flex h-3 w-3 rounded-full border border-white bg-emerald-500 shadow"
        />
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
