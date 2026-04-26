import { memo, useState } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import type { ContractNode } from "../types/contract";

const KIND_LABEL: Record<ContractNode["kind"], string> = {
  service: "Service",
  store: "Store",
  external: "External",
  ui: "UI",
  job: "Job",
  interface: "Interface",
};

const KIND_BADGE: Record<ContractNode["kind"], string> = {
  service: "bg-sky-900/60 text-sky-200 border-sky-700",
  store: "bg-emerald-900/60 text-emerald-200 border-emerald-700",
  external: "bg-fuchsia-900/60 text-fuchsia-200 border-fuchsia-700",
  ui: "bg-amber-900/60 text-amber-200 border-amber-700",
  job: "bg-indigo-900/60 text-indigo-200 border-indigo-700",
  interface: "bg-slate-700/70 text-slate-100 border-slate-500",
};

const STATUS_BADGE: Record<ContractNode["status"], string> = {
  drafted: "bg-slate-600/60 text-slate-100 border-slate-400",
  in_progress: "bg-yellow-700/60 text-yellow-100 border-yellow-500",
  implemented: "bg-green-700/60 text-green-100 border-green-500",
  failed: "bg-red-800/70 text-red-100 border-red-500",
};

function confidenceColor(confidence: number): string {
  if (confidence < 0.5) return "bg-red-500";
  if (confidence < 0.8) return "bg-yellow-400";
  return "bg-green-500";
}

function truncate(text: string, max = 90): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

function NodeCardImpl({ data }: NodeProps<ContractNode>) {
  const [expanded, setExpanded] = useState(false);
  const node = data;
  const firstAssumption = node.assumptions?.[0];
  const confidencePct = Math.round(node.confidence * 100);

  return (
    <div
      className="w-[280px] rounded-md border border-slate-600 bg-slate-100 text-slate-900 shadow-md"
      data-testid={`node-card-${node.id}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-slate-500" />

      <div className="flex items-center justify-between gap-2 border-b border-slate-300 px-3 py-2">
        <h3 className="truncate text-sm font-semibold" title={node.name}>
          {node.name}
        </h3>
        <span
          className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${KIND_BADGE[node.kind]}`}
        >
          {KIND_LABEL[node.kind]}
        </span>
      </div>

      <div className="space-y-2 px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <span
            className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${STATUS_BADGE[node.status]}`}
          >
            {node.status.replace("_", " ")}
          </span>
          <span className="text-[10px] text-slate-500">
            confidence {confidencePct}%
          </span>
        </div>

        <div
          className="h-1.5 w-full overflow-hidden rounded bg-slate-300"
          aria-label={`confidence ${confidencePct}%`}
        >
          <div
            className={`h-full ${confidenceColor(node.confidence)}`}
            style={{ width: `${confidencePct}%` }}
          />
        </div>

        {firstAssumption && (
          <p className="text-xs leading-snug text-slate-700">
            <span className="font-medium">Assumes:</span>{" "}
            {truncate(firstAssumption.text)}
          </p>
        )}

        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((v) => !v);
          }}
          className="text-[11px] font-medium text-sky-700 hover:underline focus:outline-none"
        >
          {expanded ? "Hide details" : "Show details"}
        </button>

        {expanded && (
          <div className="space-y-2 border-t border-slate-200 pt-2 text-[11px] text-slate-700">
            {node.description && (
              <p className="leading-snug">{node.description}</p>
            )}

            {node.responsibilities && node.responsibilities.length > 0 && (
              <div>
                <p className="font-medium text-slate-800">Responsibilities</p>
                <ul className="ml-4 list-disc space-y-0.5">
                  {node.responsibilities.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}

            {node.assumptions && node.assumptions.length > 0 && (
              <div>
                <p className="font-medium text-slate-800">Assumptions</p>
                <ul className="ml-4 list-disc space-y-0.5">
                  {node.assumptions.map((a, i) => (
                    <li key={i}>
                      {a.text}{" "}
                      <span className="text-slate-500">
                        ({Math.round(a.confidence * 100)}%)
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {node.open_questions && node.open_questions.length > 0 && (
              <div>
                <p className="font-medium text-slate-800">Open questions</p>
                <ul className="ml-4 list-disc space-y-0.5">
                  {node.open_questions.map((q, i) => (
                    <li key={i}>{q}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-slate-500"
      />
    </div>
  );
}

export const NodeCard = memo(NodeCardImpl);
