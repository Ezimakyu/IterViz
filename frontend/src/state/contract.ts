import { create } from "zustand";
import type {
  Assumption,
  CompilerResponse,
  Contract,
  Decision,
  Violation,
} from "../types/contract";
import {
  API,
  isApiError,
  type NodeUpdateRequest,
} from "../api/client";

/**
 * Session-aware store for M3.
 *
 * Owns the live session id, the current contract returned by the backend,
 * the most recent Compiler verdict (violations + questions + UVDC), the
 * previous contract for diff highlighting, and selection / loading state.
 */

interface ContractState {
  // ---- session ----
  sessionId: string | null;
  contract: Contract | null;
  previousContract: Contract | null;

  // ---- verification ----
  violations: Violation[];
  questions: string[];
  uvdcScore: number;
  iteration: number; // # of completed verify -> answer -> refine loops

  // ---- selection (used by Graph + NodeCard) ----
  selectedNodeId: string | null;
  selectedEdgeId: string | null;

  // ---- ui ----
  isLoading: boolean;
  error: string | null;

  // ---- M4: per-field user-edit tracking (nodeId -> fieldNames[]) ----
  userEditedFields: Record<string, string[]>;
  provenanceView: boolean;

  // ---- actions ----
  setSession: (sessionId: string, contract: Contract) => void;
  setVerificationResult: (result: CompilerResponse) => void;
  updateContract: (contract: Contract) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setSelectedNode: (id: string | null) => void;
  setSelectedEdge: (id: string | null) => void;
  toggleSelectedNode: (id: string) => void;
  toggleSelectedEdge: (id: string) => void;
  clearSelection: () => void;
  resetSession: () => void;
  clearUserEdits: () => void;
  toggleProvenanceView: () => void;
  setProvenanceView: (on: boolean) => void;

  // ---- thunks ----
  startSession: (prompt: string) => Promise<void>;
  verify: () => Promise<void>;
  submitAnswersAndRefine: (decisions: Decision[]) => Promise<void>;
  updateNodeField: (
    nodeId: string,
    field: "description" | "responsibilities" | "assumptions",
    value: string | string[] | Assumption[],
  ) => Promise<void>;
}

const initialSelection = {
  selectedNodeId: null as string | null,
  selectedEdgeId: null as string | null,
};

export const useContractStore = create<ContractState>((set, get) => ({
  sessionId: null,
  contract: null,
  previousContract: null,
  violations: [],
  questions: [],
  uvdcScore: 0,
  iteration: 0,
  ...initialSelection,
  isLoading: false,
  error: null,
  userEditedFields: {},
  provenanceView: false,

  setSession: (sessionId, contract) =>
    set({
      sessionId,
      contract,
      previousContract: null,
      violations: [],
      questions: [],
      uvdcScore: 0,
      iteration: 0,
      error: null,
      userEditedFields: {},
      ...initialSelection,
    }),

  setVerificationResult: (result) =>
    set({
      violations: result.violations ?? [],
      questions: result.questions ?? [],
      uvdcScore: result.uvdc_score ?? 0,
    }),

  updateContract: (contract) =>
    set((s) => ({
      previousContract: s.contract,
      contract,
    })),

  setLoading: (isLoading) => set({ isLoading }),
  setError: (error) => set({ error }),

  setSelectedNode: (id) =>
    set({ selectedNodeId: id, selectedEdgeId: null }),
  setSelectedEdge: (id) =>
    set({ selectedEdgeId: id, selectedNodeId: null }),
  toggleSelectedNode: (id) =>
    set((s) => ({
      selectedNodeId: s.selectedNodeId === id ? null : id,
      selectedEdgeId: null,
    })),
  toggleSelectedEdge: (id) =>
    set((s) => ({
      selectedEdgeId: s.selectedEdgeId === id ? null : id,
      selectedNodeId: null,
    })),
  clearSelection: () => set({ ...initialSelection }),

  resetSession: () =>
    set({
      sessionId: null,
      contract: null,
      previousContract: null,
      violations: [],
      questions: [],
      uvdcScore: 0,
      iteration: 0,
      ...initialSelection,
      isLoading: false,
      error: null,
      userEditedFields: {},
    }),

  clearUserEdits: () => set({ userEditedFields: {} }),

  toggleProvenanceView: () =>
    set((s) => ({ provenanceView: !s.provenanceView })),

  setProvenanceView: (provenanceView) => set({ provenanceView }),

  // ---------------------------------------------------------------------
  // Thunks
  // ---------------------------------------------------------------------

  startSession: async (prompt: string) => {
    set({ isLoading: true, error: null });
    const result = await API.createSession(prompt);
    if (isApiError(result)) {
      set({ isLoading: false, error: result.detail });
      return;
    }
    get().setSession(result.session_id, result.contract);
    set({ isLoading: false });
  },

  verify: async () => {
    const sid = get().sessionId;
    if (!sid) return;
    set({ isLoading: true, error: null });
    const result = await API.verifyContract(sid);
    if (isApiError(result)) {
      set({ isLoading: false, error: result.detail });
      return;
    }
    get().setVerificationResult(result);
    set({ isLoading: false });
  },

  updateNodeField: async (
    nodeId: string,
    field: "description" | "responsibilities" | "assumptions",
    value: string | string[] | Assumption[],
  ) => {
    const sid = get().sessionId;
    const contract = get().contract;
    if (!sid || !contract) return;

    const updates: NodeUpdateRequest = {};
    if (field === "description") updates.description = value as string;
    if (field === "responsibilities") {
      updates.responsibilities = value as string[];
    }
    if (field === "assumptions") updates.assumptions = value as Assumption[];

    set({ isLoading: true, error: null });
    const result = await API.updateNode(sid, nodeId, updates);
    if (isApiError(result)) {
      set({ isLoading: false, error: result.detail });
      return;
    }

    // Patch the node in-place. Treat the previous contract as the diff
    // baseline so the graph highlights this single edit.
    const updatedNodes = contract.nodes.map((n) =>
      n.id === nodeId ? { ...n, ...result.node } : n,
    );
    const previousFields = get().userEditedFields[nodeId] ?? [];
    const mergedFields = Array.from(
      new Set([...previousFields, ...result.fields_updated]),
    );

    set({
      previousContract: contract,
      contract: { ...contract, nodes: updatedNodes },
      isLoading: false,
      userEditedFields: {
        ...get().userEditedFields,
        [nodeId]: mergedFields,
      },
    });
  },

  submitAnswersAndRefine: async (decisions: Decision[]) => {
    const sid = get().sessionId;
    if (!sid) return;
    set({ isLoading: true, error: null });
    const ans = await API.submitAnswers(sid, decisions);
    if (isApiError(ans)) {
      set({ isLoading: false, error: ans.detail });
      return;
    }
    const refined = await API.refineContract(sid, decisions);
    if (isApiError(refined)) {
      set({ isLoading: false, error: refined.detail });
      return;
    }
    set((s) => ({
      previousContract: s.contract,
      contract: refined.contract,
      // Clear all verification artifacts: they were computed against
      // the *previous* contract and are stale once we refine.
      violations: [],
      questions: [],
      uvdcScore: 0,
      iteration: s.iteration + 1,
      isLoading: false,
    }));
  },
}));
