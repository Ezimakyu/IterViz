import { create } from "zustand";
import type {
  ImplementationSubgraph,
  SubgraphNode,
  SubgraphNodeStatus,
} from "../types/subgraph";

/**
 * Zustand store for M6 implementation subgraphs.
 *
 * Holds the per-node subgraph cache, the currently focused subgraph
 * (drives the SubgraphView), and lightweight popup state for the
 * draggable big-picture / subgraph node info popups.
 */

interface PopupState {
  /** Big-picture node currently shown in a draggable popup. */
  bigPictureNodeId: string | null;
  /** Subgraph node currently shown in a draggable popup. */
  subgraphNodeId: string | null;
  /** Parent node id for the open subgraph popup. */
  subgraphParentNodeId: string | null;
}

interface SubgraphStore {
  // ---- subgraph cache ----
  subgraphs: Record<string, ImplementationSubgraph>;
  activeParentNodeId: string | null;

  // ---- popups ----
  popups: PopupState;

  // ---- actions ----
  setSubgraph: (parentNodeId: string, subgraph: ImplementationSubgraph) => void;
  upsertSubgraph: (subgraph: ImplementationSubgraph) => void;
  clearSubgraphs: () => void;
  updateNodeStatus: (
    parentNodeId: string,
    subgraphNodeId: string,
    status: SubgraphNodeStatus,
    progress: number,
  ) => void;
  getSubgraph: (parentNodeId: string) => ImplementationSubgraph | undefined;
  hasSubgraph: (parentNodeId: string) => boolean;

  setActiveSubgraph: (parentNodeId: string | null) => void;

  openBigPicturePopup: (nodeId: string) => void;
  closeBigPicturePopup: () => void;
  openSubgraphPopup: (parentNodeId: string, subgraphNodeId: string) => void;
  closeSubgraphPopup: () => void;
  closeAllPopups: () => void;
}

const initialPopups: PopupState = {
  bigPictureNodeId: null,
  subgraphNodeId: null,
  subgraphParentNodeId: null,
};

export const useSubgraphStore = create<SubgraphStore>((set, get) => ({
  subgraphs: {},
  activeParentNodeId: null,
  popups: { ...initialPopups },

  setSubgraph: (parentNodeId, subgraph) =>
    set((s) => ({
      subgraphs: { ...s.subgraphs, [parentNodeId]: subgraph },
    })),

  upsertSubgraph: (subgraph) =>
    set((s) => ({
      subgraphs: { ...s.subgraphs, [subgraph.parent_node_id]: subgraph },
    })),

  clearSubgraphs: () =>
    set({
      subgraphs: {},
      activeParentNodeId: null,
      popups: { ...initialPopups },
    }),

  updateNodeStatus: (parentNodeId, subgraphNodeId, status, progress) =>
    set((s) => {
      const existing = s.subgraphs[parentNodeId];
      if (!existing) return {};

      const updatedNodes: SubgraphNode[] = existing.nodes.map((node) =>
        node.id === subgraphNodeId ? { ...node, status } : node,
      );

      const aggregateStatus = computeAggregateStatus(updatedNodes);

      return {
        subgraphs: {
          ...s.subgraphs,
          [parentNodeId]: {
            ...existing,
            nodes: updatedNodes,
            progress,
            status: aggregateStatus,
          },
        },
      };
    }),

  getSubgraph: (parentNodeId) => get().subgraphs[parentNodeId],
  hasSubgraph: (parentNodeId) => Boolean(get().subgraphs[parentNodeId]),

  setActiveSubgraph: (parentNodeId) =>
    set({ activeParentNodeId: parentNodeId }),

  openBigPicturePopup: (nodeId) =>
    set((s) => ({ popups: { ...s.popups, bigPictureNodeId: nodeId } })),

  closeBigPicturePopup: () =>
    set((s) => ({ popups: { ...s.popups, bigPictureNodeId: null } })),

  openSubgraphPopup: (parentNodeId, subgraphNodeId) =>
    set((s) => ({
      popups: {
        ...s.popups,
        subgraphParentNodeId: parentNodeId,
        subgraphNodeId,
      },
    })),

  closeSubgraphPopup: () =>
    set((s) => ({
      popups: {
        ...s.popups,
        subgraphNodeId: null,
        subgraphParentNodeId: null,
      },
    })),

  closeAllPopups: () => set({ popups: { ...initialPopups } }),
}));

function computeAggregateStatus(
  nodes: SubgraphNode[],
): SubgraphNodeStatus {
  if (nodes.length === 0) return "pending";
  if (nodes.every((n) => n.status === "completed")) return "completed";
  if (nodes.some((n) => n.status === "failed")) return "failed";
  if (nodes.some((n) => n.status === "in_progress")) return "in_progress";
  return "pending";
}
