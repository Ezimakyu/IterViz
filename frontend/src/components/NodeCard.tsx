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

function progressColor(status: ContractNode["status"]): string {
  switch (status) {
    case "implemented":
      return "bg-green-500";
    case "in_progress":
      return "bg-yellow-400";
    case "failed":
      return "bg-red-500";
    default:
      return "bg-slate-400";
  }
}

function statusToProgress(status: ContractNode["status"]): number {
  switch (status) {
    case "implemented":
      return 100;
    case "in_progress":
      return 50;
    case "failed":
      return 100;
    default:
      return 0;
  }
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
  const nodeProgress = useContractStore((s) => s.nodeProgress);
  const storedProgress = nodeProgress.get(id);
  const progressPct = storedProgress ?? statusToProgress(node.status);
  const selectedNodeId = useContractStore((s) => s.selectedNodeId);
  const previousContract = useContractStore((s) => s.previousContract);
  const nodeAgents = useContractStore((s) => s.nodeAgents);
  const userEditedFields = useContractStore((s) => s.userEditedFields);
  const provenanceView = useContractStore((s) => s.provenanceView);
  const openBigPicturePopup = useSubgraphStore((s) => s.openBigPicturePopup);
  const hasSubgraph = useSubgraphStore((s) => Boolean(s.subgraphs[id]));
  const isGeneratingSubgraph = useSubgraphStore((s) => s.generatingSubgraphIds.has(id));
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
        statusRing,
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
      {agentInfo && (
        <span
          className="absolute -top-2 left-1 max-w-[80%] truncate rounded bg-violet-500 px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white"
          title={`Claimed by ${agentInfo.agentName}`}
        >
          {agentInfo.agentName}
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
        className="absolute -top-2 -right-1 z-10 flex h-7 w-7 items-center justify-center rounded-full border-2 border-slate-400 bg-white text-sm font-bold text-slate-700 shadow-md hover:bg-sky-100 hover:text-sky-700 hover:border-sky-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 transition-colors"
      >
        i
      </button>
      {isGeneratingSubgraph && (
        <span
          aria-label="Generating subgraph..."
          data-testid={`node-generating-indicator-${node.id}`}
          className="absolute -bottom-1 -right-1 inline-flex h-4 w-4 items-center justify-center rounded-full border border-white bg-yellow-400 shadow animate-pulse"
        >
          <svg className="h-2.5 w-2.5 animate-spin text-yellow-800" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        </span>
      )}
      {hasSubgraph && !isGeneratingSubgraph && (
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
        aria-label={`progress ${progressPct}%`}
      >
        <div
          className={`h-full transition-all duration-300 ${progressColor(node.status)}`}
          style={{ width: `${progressPct}%` }}
        />
      </div>
    </div>
  );
}

export const NodeCard = memo(NodeCardImpl);
