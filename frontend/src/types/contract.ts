/**
 * TypeScript types mirroring the architecture_contract.json schema
 * defined in ARCHITECTURE.md §4. Only the fields needed for the
 * static M0 visualization are required; the rest are optional so we
 * can load partial fixtures without ceremony.
 */

export type NodeKind = "service" | "store" | "external" | "ui" | "job" | "interface";
export type NodeStatus = "drafted" | "in_progress" | "implemented" | "failed";
export type EdgeKind = "data" | "control" | "event" | "dependency";
export type DecidedBy = "user" | "agent" | "prompt";
export type ContractStatus =
  | "drafting"
  | "verified"
  | "implementing"
  | "complete";

export interface Assumption {
  text: string;
  confidence: number;
  decided_by: DecidedBy;
  load_bearing: boolean;
}

export interface ContractNode {
  id: string;
  name: string;
  kind: NodeKind;
  description?: string;
  responsibilities?: string[];
  assumptions?: Assumption[];
  confidence: number;
  open_questions?: string[];
  decided_by?: DecidedBy;
  status: NodeStatus;
}

export interface PayloadSchema {
  type?: string;
  properties?: Record<string, unknown>;
  required?: string[];
}

export interface ContractEdge {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  label?: string | null;
  payload_schema?: PayloadSchema | null;
  assumptions?: Assumption[];
  confidence?: number;
  decided_by?: DecidedBy;
}

export interface ContractMeta {
  id?: string;
  version?: number;
  status?: ContractStatus;
  stated_intent?: string;
}

export interface Contract {
  meta?: ContractMeta;
  nodes: ContractNode[];
  edges: ContractEdge[];
}
