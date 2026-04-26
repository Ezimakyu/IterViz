/**
 * Implementation subgraph types (M6).
 *
 * Mirrors the Pydantic models in ``backend/app/schemas.py``. A subgraph
 * is a per-node breakdown of concrete implementation tasks: functions,
 * tests, types, error handlers, etc. It is generated from a *verified*
 * big-picture node and never carries architectural assumptions.
 */

export type SubgraphNodeKind =
  | "function"
  | "module"
  | "test_unit"
  | "test_integration"
  | "test_eval"
  | "type_def"
  | "config"
  | "error_handler"
  | "util";

export type SubgraphNodeStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "failed";

export interface SubgraphNode {
  id: string;
  name: string;
  kind: SubgraphNodeKind;
  description: string;
  status: SubgraphNodeStatus;
  signature?: string | null;
  dependencies: string[];
  estimated_lines?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
}

export interface SubgraphEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  label?: string | null;
}

export interface ImplementationSubgraph {
  id: string;
  parent_node_id: string;
  parent_node_name: string;
  session_id: string;
  created_at: string;
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
  status: SubgraphNodeStatus;
  progress: number;
  total_estimated_lines?: number | null;
}

// ---------------------------------------------------------------------------
// WebSocket message types (M6)
// ---------------------------------------------------------------------------

export type WSMessageType =
  | "subgraph_created"
  | "subgraph_node_status_changed";

export interface WSSubgraphCreated {
  type: "subgraph_created";
  parent_node_id: string;
  subgraph: ImplementationSubgraph;
}

export interface WSSubgraphNodeStatusChanged {
  type: "subgraph_node_status_changed";
  parent_node_id: string;
  subgraph_node_id: string;
  status: SubgraphNodeStatus;
  progress: number;
}

export type WSMessage =
  | WSSubgraphCreated
  | WSSubgraphNodeStatusChanged;
