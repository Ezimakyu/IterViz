import { create } from "zustand";
import type {
  Agent,
  Assumption,
  CompilerResponse,
  Contract,
  Decision,
  ImplementMode,
  IntegrationMismatch,
  NodeStatus,
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

  // ---- M5: Phase 2 orchestration ----
  isFrozen: boolean;
  isImplementing: boolean;
  implementationMode: ImplementMode | null;
  implementationComplete: boolean;
  implementationSuccess: boolean;
  connectedAgents: Map<string, Agent>;
  nodeAgents: Map<string, { agentId: string; agentName: string }>;
  nodeProgress: Map<string, number>;
  nodeProgressMessages: Map<string, string>;
  integrationMismatches: IntegrationMismatch[];

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

  // ---- M5 actions ----
  setFrozen: (frozen: boolean) => void;
  setImplementing: (implementing: boolean, mode?: ImplementMode) => void;
  updateNodeStatus: (
    nodeId: string,
    status: NodeStatus,
    agent?: { id: string; name: string } | null,
  ) => void;
  setNodeProgress: (nodeId: string, progress: number, message?: string | null) => void;
  setAgentInfo: (agentId: string, agent: Agent) => void;
  addMismatch: (mismatch: IntegrationMismatch) => void;
  setIntegrationMismatches: (mismatches: IntegrationMismatch[]) => void;
  setImplementationComplete: (success: boolean) => void;

  // ---- thunks ----
  startSession: (prompt: string) => Promise<void>;
  verify: () => Promise<void>;
  submitAnswersAndRefine: (decisions: Decision[]) => Promise<void>;
  freeze: () => Promise<void>;
  implement: (mode: ImplementMode) => Promise<void>;
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
  isFrozen: false,
  isImplementing: false,
  implementationMode: null,
  implementationComplete: false,
  implementationSuccess: false,
  connectedAgents: new Map(),
  nodeAgents: new Map(),
  nodeProgress: new Map(),
  nodeProgressMessages: new Map(),
  integrationMismatches: [],

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
      isFrozen: contract.meta?.status === "verified" ||
        contract.meta?.status === "implementing" ||
        contract.meta?.status === "complete",
      isImplementing: false,
      implementationMode: null,
      implementationComplete: false,
      implementationSuccess: false,
      connectedAgents: new Map(),
      nodeAgents: new Map(),
      nodeProgress: new Map(),
      nodeProgressMessages: new Map(),
      integrationMismatches: [],
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
      isFrozen: false,
      isImplementing: false,
      implementationMode: null,
      implementationComplete: false,
      implementationSuccess: false,
      connectedAgents: new Map(),
      nodeAgents: new Map(),
      nodeProgress: new Map(),
      nodeProgressMessages: new Map(),
      integrationMismatches: [],
    }),

  // ---------------------------------------------------------------------
  // M5 actions
  // ---------------------------------------------------------------------

  setFrozen: (frozen) => set({ isFrozen: frozen }),

  setImplementing: (implementing, mode) =>
    set({
      isImplementing: implementing,
      implementationMode: mode ?? null,
      implementationComplete: false,
    }),

  updateNodeStatus: (nodeId, status, agent) =>
    set((s) => {
      if (!s.contract) return {};
      const nodes = s.contract.nodes.map((n) =>
        n.id === nodeId ? { ...n, status } : n,
      );
      const nodeAgents = new Map(s.nodeAgents);
      if (agent) {
        nodeAgents.set(nodeId, { agentId: agent.id, agentName: agent.name });
      } else if (status === "drafted") {
        nodeAgents.delete(nodeId);
      }
      return {
        contract: { ...s.contract, nodes },
        nodeAgents,
      };
    }),

  setNodeProgress: (nodeId, progress, message) =>
    set((s) => {
      const np = new Map(s.nodeProgress);
      np.set(nodeId, progress);
      const npm = new Map(s.nodeProgressMessages);
      if (message) {
        npm.set(nodeId, message);
      }
      return { nodeProgress: np, nodeProgressMessages: npm };
    }),

  setAgentInfo: (agentId, agent) =>
    set((s) => {
      const next = new Map(s.connectedAgents);
      next.set(agentId, agent);
      return { connectedAgents: next };
    }),

  addMismatch: (mismatch) =>
    set((s) => ({
      integrationMismatches: [...s.integrationMismatches, mismatch],
    })),

  setIntegrationMismatches: (mismatches) =>
    set({ integrationMismatches: mismatches }),

  setImplementationComplete: (success) =>
    set({
      implementationComplete: true,
      implementationSuccess: success,
      isImplementing: false,
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

  // ---------------------------------------------------------------------
  // M5 thunks
  // ---------------------------------------------------------------------

  freeze: async () => {
    const sid = get().sessionId;
    if (!sid) return;
    set({ isLoading: true, error: null });
    const result = await API.freezeContract(sid);
    if (isApiError(result)) {
      set({ isLoading: false, error: result.detail });
      return;
    }
    set((s) => ({
      contract: result.contract,
      previousContract: s.contract,
      isFrozen: true,
      isLoading: false,
    }));
  },

  implement: async (mode) => {
    const sid = get().sessionId;
    if (!sid) return;
    set({ isLoading: true, error: null });
    const result = await API.startImplementation(sid, mode);
    if (isApiError(result)) {
      set({ isLoading: false, error: result.detail });
      return;
    }
    set({
      isImplementing: true,
      implementationMode: mode,
      implementationComplete: false,
      implementationSuccess: false,
      isLoading: false,
    });
  },
}));
