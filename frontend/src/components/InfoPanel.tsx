import { useMemo } from "react";
import { useContractStore } from "../state/contract";
import { useSubgraphStore } from "../state/subgraph";
import type { SubgraphNode } from "../types/subgraph";

const STATUS_COLORS: Record<SubgraphNode["status"], string> = {
  pending: "text-slate-400",
  in_progress: "text-yellow-400",
  completed: "text-green-400",
  failed: "text-red-400",
};

export function useInfoPanelTitle(): string {
  const activeParentNodeId = useSubgraphStore((s) => s.activeParentNodeId);
  const subgraphs = useSubgraphStore((s) => s.subgraphs);
  const activeSubgraph = activeParentNodeId
    ? subgraphs[activeParentNodeId]
    : null;
  
  return activeSubgraph ? "Implementation Tasks" : "Planning Summary";
}

export function InfoPanelContent() {
  const contract = useContractStore((s) => s.contract);
  const isLoading = useContractStore((s) => s.isLoading);
  const activeParentNodeId = useSubgraphStore((s) => s.activeParentNodeId);
  const subgraphs = useSubgraphStore((s) => s.subgraphs);

  const activeSubgraph = activeParentNodeId
    ? subgraphs[activeParentNodeId]
    : null;

  if (activeSubgraph) {
    return <SubgraphInfoContent subgraph={activeSubgraph} />;
  }

  return <PlanningInfoContent contract={contract} isLoading={isLoading} />;
}

function PlanningInfoContent({
  contract,
  isLoading,
}: {
  contract: ReturnType<typeof useContractStore.getState>["contract"];
  isLoading: boolean;
}) {
  const subgraphs = useSubgraphStore((s) => s.subgraphs);
  const isImplementing = useContractStore((s) => s.isImplementing);
  const nodeProgressMessages = useContractStore((s) => s.nodeProgressMessages);
  
  const nodesByKind = useMemo(() => {
    if (!contract) return {};
    const groups: Record<string, typeof contract.nodes> = {};
    for (const node of contract.nodes) {
      if (!groups[node.kind]) groups[node.kind] = [];
      groups[node.kind].push(node);
    }
    return groups;
  }, [contract]);
  
  const subgraphProgress = useMemo(() => {
    if (!contract) return { ready: 0, total: 0 };
    const total = contract.nodes.length;
    const ready = contract.nodes.filter((n) => subgraphs[n.id]).length;
    return { ready, total };
  }, [contract, subgraphs]);

  // Find the current activity (most recent progress message)
  const currentActivity = useMemo(() => {
    if (!contract || !isImplementing) return null;
    
    // Find node that is in_progress
    const inProgressNode = contract.nodes.find((n) => n.status === "in_progress");
    if (!inProgressNode) return null;
    
    const message = nodeProgressMessages.get(inProgressNode.id);
    return {
      nodeName: inProgressNode.name,
      message: message || "Generating code...",
    };
  }, [contract, isImplementing, nodeProgressMessages]);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3 p-4">
        <div className="flex items-center gap-2 text-sm text-muted">
          <LoadingSpinner />
          <span>Generating plan...</span>
        </div>
      </div>
    );
  }

  if (!contract) {
    return (
      <div className="flex flex-col gap-3 p-4">
        <p className="text-sm text-muted">
          Enter a prompt to generate a system architecture plan.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      {currentActivity && (
        <div className="rounded border border-sky-600 bg-sky-900/30 p-3 animate-pulse">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-sky-300 mb-2">
            Current Activity
          </h3>
          <div className="flex items-center gap-2">
            <LoadingSpinner />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-ink truncate">
                {currentActivity.nodeName}
              </p>
              <p className="text-xs text-muted truncate">
                {currentActivity.message}
              </p>
            </div>
          </div>
        </div>
      )}

      {contract.meta?.stated_intent && (
        <div className="rounded border border-slate-700 bg-slate-900/60 p-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted mb-2">
            Stated Intent
          </h3>
          <p className="text-sm text-ink leading-relaxed">
            {contract.meta.stated_intent}
          </p>
        </div>
      )}

      <div className="rounded border border-slate-700 bg-slate-900/60 p-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted mb-2">
          Architecture Overview
        </h3>
        <div className="flex gap-4 text-sm mb-3">
          <span className="text-muted">
            <span className="text-ink font-semibold">{contract.nodes.length}</span> components
          </span>
          <span className="text-muted">
            <span className="text-ink font-semibold">{contract.edges.length}</span> connections
          </span>
        </div>
        
        <div className="space-y-2">
          {Object.entries(nodesByKind).map(([kind, nodes]) => (
            <div key={kind} className="flex items-center gap-2 text-sm">
              <KindBadge kind={kind} />
              <span className="text-muted">
                {nodes.length} {kind}{nodes.length !== 1 ? "s" : ""}
              </span>
            </div>
          ))}
        </div>
      </div>

      {subgraphProgress.total > 0 && (
        <div className="rounded border border-slate-700 bg-slate-900/60 p-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted mb-2">
            Implementation Details
          </h3>
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="text-muted">Subgraphs ready</span>
            <span className="text-ink font-semibold">
              {subgraphProgress.ready}/{subgraphProgress.total}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-700">
            <div
              className={`h-full transition-all duration-300 ${
                subgraphProgress.ready === subgraphProgress.total
                  ? "bg-green-500"
                  : "bg-sky-500"
              }`}
              style={{
                width: `${(subgraphProgress.ready / subgraphProgress.total) * 100}%`,
              }}
            />
          </div>
          <p className="text-xs text-muted mt-2">
            {subgraphProgress.ready === subgraphProgress.total
              ? "Click on any node to view its implementation breakdown"
              : "Generating implementation details in the background..."}
          </p>
        </div>
      )}

      <div className="rounded border border-slate-700 bg-slate-900/60 p-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted mb-2">
          Components
        </h3>
        <ol className="space-y-2">
          {contract.nodes.map((node, idx) => (
            <li
              key={node.id}
              className="flex items-start gap-2 text-sm"
            >
              <span className="text-muted font-mono text-xs mt-0.5">
                {(idx + 1).toString().padStart(2, "0")}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-ink truncate">{node.name}</span>
                  <KindBadge kind={node.kind} small />
                </div>
                {node.description && (
                  <p className="text-xs text-muted mt-0.5 line-clamp-2">
                    {node.description}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      </div>

      {contract.decisions && contract.decisions.length > 0 && (
        <div className="rounded border border-slate-700 bg-slate-900/60 p-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted mb-2">
            Decisions Made ({contract.decisions.length})
          </h3>
          <ol className="space-y-2">
            {contract.decisions.slice(0, 5).map((decision) => (
              <li key={decision.id} className="text-sm">
                <p className="text-muted text-xs">{decision.question}</p>
                <p className="text-ink">{decision.answer}</p>
              </li>
            ))}
            {contract.decisions.length > 5 && (
              <li className="text-xs text-muted">
                +{contract.decisions.length - 5} more decisions
              </li>
            )}
          </ol>
        </div>
      )}
    </div>
  );
}

function SubgraphInfoContent({
  subgraph,
}: {
  subgraph: ReturnType<typeof useSubgraphStore.getState>["subgraphs"][string];
}) {
  const tasksByStatus = useMemo(() => {
    const groups: Record<SubgraphNode["status"], SubgraphNode[]> = {
      pending: [],
      in_progress: [],
      completed: [],
      failed: [],
    };
    for (const node of subgraph.nodes) {
      groups[node.status].push(node);
    }
    return groups;
  }, [subgraph]);

  const progressPct = Math.round(subgraph.progress * 100);

  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <h3 className="text-lg font-semibold text-ink">
          {subgraph.parent_node_name}
        </h3>
      </div>

      <div className="rounded border border-slate-700 bg-slate-900/60 p-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-muted">Progress</span>
          <span className="text-sm font-semibold text-ink">{progressPct}%</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-700">
          <div
            className={`h-full transition-all duration-300 ${getProgressColor(subgraph.status)}`}
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <div className="flex justify-between mt-2 text-xs text-muted">
          <span>{tasksByStatus.completed.length} completed</span>
          <span>{tasksByStatus.in_progress.length} in progress</span>
          <span>{tasksByStatus.pending.length} pending</span>
        </div>
      </div>

      <div className="space-y-3">
        {tasksByStatus.in_progress.length > 0 && (
          <TaskGroup title="In Progress" tasks={tasksByStatus.in_progress} />
        )}
        {tasksByStatus.pending.length > 0 && (
          <TaskGroup title="Pending" tasks={tasksByStatus.pending} />
        )}
        {tasksByStatus.completed.length > 0 && (
          <TaskGroup title="Completed" tasks={tasksByStatus.completed} />
        )}
        {tasksByStatus.failed.length > 0 && (
          <TaskGroup title="Failed" tasks={tasksByStatus.failed} />
        )}
      </div>

      {subgraph.total_estimated_lines && (
        <div className="text-xs text-muted border-t border-slate-700 pt-3">
          Estimated total: ~{subgraph.total_estimated_lines} lines of code
        </div>
      )}
    </div>
  );
}

function TaskGroup({
  title,
  tasks,
}: {
  title: string;
  tasks: SubgraphNode[];
}) {
  return (
    <div className="rounded border border-slate-700 bg-slate-900/60 p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted mb-2">
        {title} ({tasks.length})
      </h3>
      <ul className="space-y-2">
        {tasks.map((task) => (
          <li key={task.id} className="text-sm">
            <div className="flex items-center gap-2">
              <span className={`${STATUS_COLORS[task.status]}`}>
                {getStatusIcon(task.status)}
              </span>
              <span className="font-medium text-ink truncate">{task.name}</span>
              <KindBadge kind={task.kind} small />
            </div>
            {task.description && (
              <p className="text-xs text-muted mt-0.5 ml-5 line-clamp-2">
                {task.description}
              </p>
            )}
            {task.error_message && (
              <p className="text-xs text-red-400 mt-0.5 ml-5">
                {task.error_message}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function KindBadge({ kind, small }: { kind: string; small?: boolean }) {
  const colors: Record<string, string> = {
    service: "bg-sky-500/20 text-sky-300",
    store: "bg-emerald-500/20 text-emerald-300",
    external: "bg-fuchsia-500/20 text-fuchsia-300",
    ui: "bg-amber-500/20 text-amber-300",
    job: "bg-indigo-500/20 text-indigo-300",
    interface: "bg-slate-500/20 text-slate-300",
    function: "bg-blue-500/20 text-blue-300",
    module: "bg-purple-500/20 text-purple-300",
    test_unit: "bg-green-500/20 text-green-300",
    test_integration: "bg-teal-500/20 text-teal-300",
    test_eval: "bg-cyan-500/20 text-cyan-300",
    type_def: "bg-orange-500/20 text-orange-300",
    config: "bg-gray-500/20 text-gray-300",
    error_handler: "bg-red-500/20 text-red-300",
    util: "bg-lime-500/20 text-lime-300",
  };
  
  const colorClass = colors[kind] ?? "bg-slate-500/20 text-slate-300";
  const sizeClass = small
    ? "text-[9px] px-1 py-0.5"
    : "text-[10px] px-1.5 py-0.5";

  return (
    <span
      className={`rounded ${sizeClass} font-medium uppercase tracking-wide ${colorClass}`}
    >
      {kind.replace("_", " ")}
    </span>
  );
}

function getStatusIcon(status: SubgraphNode["status"]): string {
  switch (status) {
    case "completed":
      return "✓";
    case "in_progress":
      return "●";
    case "failed":
      return "✕";
    default:
      return "○";
  }
}

function getProgressColor(status: SubgraphNode["status"]): string {
  switch (status) {
    case "completed":
      return "bg-green-500";
    case "failed":
      return "bg-red-500";
    case "in_progress":
      return "bg-yellow-400";
    default:
      return "bg-slate-400";
  }
}

function LoadingSpinner() {
  return (
    <svg
      className="h-4 w-4 animate-spin"
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}
