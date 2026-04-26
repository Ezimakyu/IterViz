import type { ContractNode } from "../types/contract";
import type {
  ImplementationSubgraph,
  SubgraphNode,
  SubgraphNodeStatus,
} from "../types/subgraph";
import { useContractStore } from "../state/contract";
import { useSubgraphStore } from "../state/subgraph";
import { DraggablePopup } from "./DraggablePopup";

/**
 * Coordinates the (potentially multiple) draggable popups shown above
 * the graph canvas:
 *
 * - Big-picture node popup (assumption-free description + responsibilities).
 * - Subgraph node popup (concrete implementation task details).
 *
 * Both popups are independent: the user can open either, both, or
 * neither, and dragging one does not affect the other.
 */

const KIND_LABELS: Record<SubgraphNode["kind"], string> = {
  function: "Function",
  module: "Module",
  test_unit: "Unit Test",
  test_integration: "Integration Test",
  test_eval: "Evaluation Test",
  type_def: "Type / Schema",
  config: "Config",
  error_handler: "Error Handler",
  util: "Utility",
};

const STATUS_LABEL: Record<SubgraphNodeStatus, string> = {
  pending: "Pending",
  in_progress: "In progress",
  completed: "Completed",
  failed: "Failed",
};

const STATUS_DOT: Record<SubgraphNodeStatus, string> = {
  pending: "bg-slate-400",
  in_progress: "bg-yellow-400 animate-pulse",
  completed: "bg-green-500",
  failed: "bg-red-500",
};

export function NodePopupManager() {
  const contract = useContractStore((s) => s.contract);
  const popups = useSubgraphStore((s) => s.popups);
  const subgraphs = useSubgraphStore((s) => s.subgraphs);
  const closeBigPicturePopup = useSubgraphStore((s) => s.closeBigPicturePopup);
  const closeSubgraphPopup = useSubgraphStore((s) => s.closeSubgraphPopup);

  const bigNode: ContractNode | null =
    popups.bigPictureNodeId && contract
      ? contract.nodes.find((n) => n.id === popups.bigPictureNodeId) ?? null
      : null;

  const subgraph: ImplementationSubgraph | null =
    popups.subgraphParentNodeId
      ? subgraphs[popups.subgraphParentNodeId] ?? null
      : null;

  const sgNode: SubgraphNode | null =
    subgraph && popups.subgraphNodeId
      ? subgraph.nodes.find((n) => n.id === popups.subgraphNodeId) ?? null
      : null;

  return (
    <>
      {bigNode && (
        <DraggablePopup
          title={bigNode.name}
          onClose={closeBigPicturePopup}
          initialPosition={{ x: 100, y: 100 }}
          zIndex={70}
          testId={`big-picture-popup-${bigNode.id}`}
        >
          <BigPictureNodeContent node={bigNode} />
        </DraggablePopup>
      )}

      {sgNode && (
        <DraggablePopup
          title={sgNode.name}
          onClose={closeSubgraphPopup}
          initialPosition={{ x: 480, y: 140 }}
          zIndex={75}
          testId={`subgraph-popup-${sgNode.id}`}
        >
          <SubgraphNodeContent node={sgNode} />
        </DraggablePopup>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Content components
// ---------------------------------------------------------------------------

function BigPictureNodeContent({ node }: { node: ContractNode }) {
  return (
    <div className="space-y-3">
      <p>
        <span className="text-muted">Type · </span>
        {node.kind}
      </p>

      {node.description && (
        <section>
          <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            Description
          </h4>
          <p className="whitespace-pre-wrap">{node.description}</p>
        </section>
      )}

      {node.responsibilities && node.responsibilities.length > 0 && (
        <section>
          <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            Responsibilities
          </h4>
          <ul className="list-disc space-y-1 pl-4">
            {node.responsibilities.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </section>
      )}

      <p className="border-t border-slate-700 pt-2 text-[10px] italic text-muted">
        Big-picture popup intentionally omits assumptions — those are
        verified via the Phase 1 loop before implementation begins.
      </p>
    </div>
  );
}

function SubgraphNodeContent({ node }: { node: SubgraphNode }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <span className="rounded-full border border-slate-500 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300">
          {KIND_LABELS[node.kind]}
        </span>
        <span className="flex items-center gap-1.5 text-[11px]">
          <span className={`h-2 w-2 rounded-full ${STATUS_DOT[node.status]}`} />
          {STATUS_LABEL[node.status]}
        </span>
      </div>

      {node.description && (
        <section>
          <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            Description
          </h4>
          <p className="whitespace-pre-wrap">{node.description}</p>
        </section>
      )}

      {node.signature && (
        <section>
          <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            Signature
          </h4>
          <pre className="whitespace-pre-wrap break-words rounded bg-slate-900/70 px-2 py-1 font-mono text-[11px]">
            {node.signature}
          </pre>
        </section>
      )}

      {node.dependencies.length > 0 && (
        <section>
          <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            Depends on
          </h4>
          <ul className="list-disc space-y-0.5 pl-4 text-[11px]">
            {node.dependencies.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </section>
      )}

      {node.estimated_lines !== null && node.estimated_lines !== undefined && (
        <p className="text-[11px] text-muted">
          Estimated ~{node.estimated_lines} lines
        </p>
      )}

      {node.error_message && (
        <section className="rounded border border-red-700/50 bg-red-900/30 px-2 py-1.5">
          <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-red-200">
            Error
          </h4>
          <p className="whitespace-pre-wrap text-red-100">
            {node.error_message}
          </p>
        </section>
      )}
    </div>
  );
}
