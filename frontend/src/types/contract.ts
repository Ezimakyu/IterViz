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

export interface Decision {
  id: string;
  question: string;
  answer: string;
  answered_at?: string;
  affects?: string[];
  source_violation_id?: string | null;
}

export interface VerificationLogEntry {
  id?: string;
  run_at?: string;
  verdict: "pass" | "fail";
  violations?: Violation[];
  questions?: string[];
  intent_guess?: string;
  uvdc_score?: number;
}

export interface Contract {
  meta?: ContractMeta;
  nodes: ContractNode[];
  edges: ContractEdge[];
  decisions?: Decision[];
  verification_log?: VerificationLogEntry[];
}

// ---------------------------------------------------------------------------
// Compiler / verification types
// ---------------------------------------------------------------------------

export type ViolationType =
  | "intent_mismatch"
  | "invariant"
  | "failure_scenario"
  | "provenance";

export type ViolationSeverity = "error" | "warning";

export interface Violation {
  id?: string;
  type: ViolationType;
  severity: ViolationSeverity;
  message: string;
  affects?: string[];
  suggested_question?: string;
}

export interface CompilerResponse {
  verdict: "pass" | "fail";
  violations: Violation[];
  questions: string[];
  intent_guess?: string;
  uvdc_score: number;
  confidence_updates?: Array<{
    node_id: string;
    new_confidence: number;
    reasoning: string;
  }>;
}

export interface ContractDiff {
  previous_version?: number;
  new_version?: number;
  n_decisions?: number;
  n_nodes_before?: number;
  n_nodes_after?: number;
  n_edges_before?: number;
  n_edges_after?: number;
}
