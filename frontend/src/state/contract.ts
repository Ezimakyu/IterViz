import { create } from "zustand";
import type { Contract } from "../types/contract";

export interface ContractCatalogEntry {
  id: string;
  label: string;
  path: string;
}

export const CONTRACT_CATALOG: ContractCatalogEntry[] = [
  {
    id: "small",
    label: "Small (CLI tool)",
    path: "/sample_contract_small.json",
  },
  {
    id: "medium",
    label: "Medium (web app w/ auth + DB)",
    path: "/sample_contract_medium.json",
  },
];

interface ContractState {
  selectedId: string;
  contract: Contract | null;
  loading: boolean;
  error: string | null;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  selectContract: (id: string) => Promise<void>;
  setSelectedNode: (id: string | null) => void;
  setSelectedEdge: (id: string | null) => void;
  toggleSelectedEdge: (id: string) => void;
  toggleSelectedNode: (id: string) => void;
  clearSelection: () => void;
}

export const useContractStore = create<ContractState>((set, get) => ({
  selectedId: CONTRACT_CATALOG[0].id,
  contract: null,
  loading: false,
  error: null,
  selectedNodeId: null,
  selectedEdgeId: null,
  selectContract: async (id: string) => {
    const entry = CONTRACT_CATALOG.find((e) => e.id === id);
    if (!entry) {
      set({ error: `Unknown contract id: ${id}` });
      return;
    }
    set({
      selectedId: id,
      loading: true,
      error: null,
      selectedNodeId: null,
      selectedEdgeId: null,
    });
    try {
      const res = await fetch(entry.path);
      if (!res.ok) {
        throw new Error(`Failed to load ${entry.path}: ${res.status}`);
      }
      const data = (await res.json()) as Contract;
      // Only update if the user hasn't switched contracts mid-flight.
      if (get().selectedId === id) {
        set({ contract: data, loading: false });
      }
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  },
  setSelectedNode: (id) => set({ selectedNodeId: id, selectedEdgeId: null }),
  setSelectedEdge: (id) => set({ selectedEdgeId: id, selectedNodeId: null }),
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
  clearSelection: () => set({ selectedNodeId: null, selectedEdgeId: null }),
}));
