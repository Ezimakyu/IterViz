import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import type { SubgraphNode, SubgraphNodeStatus } from "../types/subgraph";

export interface SubgraphNodeCardData {
  node: SubgraphNode;
  parentNodeId: string;
  onSelect: (subgraphNodeId: string) => void;
}

const KIND_RING: Record<SubgraphNode["kind"], string> = {
  function: "ring-sky-400/60",
  module: "ring-indigo-400/60",
  test_unit: "ring-amber-400/60",
  test_integration: "ring-amber-400/60",
  test_eval: "ring-amber-400/60",
  type_def: "ring-emerald-400/60",
  config: "ring-slate-300/60",
  error_handler: "ring-rose-400/60",
  util: "ring-fuchsia-400/60",
};

const KIND_ICON: Record<SubgraphNode["kind"], string> = {
  function: "ƒ",
  module: "□",
  test_unit: "✓",
  test_integration: "⇄",
  test_eval: "★",
  type_def: "T",
  config: "⚙",
  error_handler: "!",
  util: "·",
};

const STATUS_BORDER: Record<SubgraphNodeStatus, string> = {
  pending: "border-slate-500",
  in_progress: "border-yellow-400",
  completed: "border-green-500",
  failed: "border-red-500",
};

const STATUS_DOT: Record<SubgraphNodeStatus, string> = {
  pending: "bg-slate-400",
  in_progress: "bg-yellow-400 animate-pulse",
  completed: "bg-green-500",
  failed: "bg-red-500",
};

function SubgraphNodeCardImpl({
  data,
  selected,
}: NodeProps<SubgraphNodeCardData>) {
  const { node, onSelect } = data;
  return (
    <div
      data-testid={`subgraph-node-card-${node.id}`}
      data-status={node.status}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(node.id);
      }}
      className={[
        "relative flex w-[200px] flex-col gap-1 rounded-lg border bg-slate-100 px-3 py-2 text-slate-900 shadow-md transition",
        STATUS_BORDER[node.status],
        selected ? "ring-2 ring-sky-500" : "",
        node.status === "in_progress" ? `ring-2 ${KIND_RING[node.kind]}` : "",
      ].join(" ")}
      title={node.description || node.name}
    >
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

      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span
            aria-hidden
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-slate-200 text-[12px] font-semibold text-slate-700"
          >
            {KIND_ICON[node.kind]}
          </span>
          <h4 className="truncate text-[13px] font-semibold leading-tight">
            {node.name}
          </h4>
        </div>
        <span
          aria-label={`status: ${node.status}`}
          className={`mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full ${STATUS_DOT[node.status]}`}
        />
      </div>

      {node.signature && (
        <p className="truncate font-mono text-[10.5px] text-slate-600">
          {node.signature}
        </p>
      )}
    </div>
  );
}

export const SubgraphNodeCard = memo(SubgraphNodeCardImpl);
