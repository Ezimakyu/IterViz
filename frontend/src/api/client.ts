/**
 * Thin fetch wrappers for the Glasshouse v1 backend.
 *
 * All helpers throw on transport failures (network down, JSON-parse
 * errors) but return a structured `{ ok: false, status, detail }` for
 * 4xx/5xx responses so the UI can render a friendly error.
 */

import type {
  Assumption,
  CompilerResponse,
  Contract,
  ContractDiff,
  ContractNode,
  Decision,
} from "../types/contract";
import type {
  ImplementationSubgraph,
  SubgraphNodeStatus,
} from "../types/subgraph";

const API_BASE = (
  (import.meta as ImportMeta & { env?: { VITE_API_BASE?: string } }).env
    ?.VITE_API_BASE ?? "http://localhost:8000/api/v1"
);

export interface ApiError {
  ok: false;
  status: number;
  detail: string;
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T | ApiError> {
  const url = `${API_BASE}${path}`;
  let resp: Response;
  try {
    resp = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch (err) {
    return {
      ok: false,
      status: 0,
      detail: err instanceof Error ? err.message : String(err),
    };
  }

  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // body wasn't JSON; keep the default detail.
    }
    return { ok: false, status: resp.status, detail };
  }

  return (await resp.json()) as T;
}

export function isApiError<T>(x: T | ApiError): x is ApiError {
  return Boolean(x) && (x as ApiError).ok === false;
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export interface CreateSessionResult {
  session_id: string;
  contract: Contract;
}

export function createSession(prompt: string) {
  return request<CreateSessionResult>("/sessions", {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

export function getSession(sessionId: string) {
  return request<{ contract: Contract }>(`/sessions/${sessionId}`, {
    method: "GET",
  });
}

export function verifyContract(sessionId: string) {
  return request<CompilerResponse>(
    `/sessions/${sessionId}/compiler/verify`,
    { method: "POST" },
  );
}

export function submitAnswers(sessionId: string, decisions: Decision[]) {
  return request<{ contract: Contract }>(`/sessions/${sessionId}/answers`, {
    method: "POST",
    body: JSON.stringify({ decisions }),
  });
}

export function refineContract(sessionId: string, answers: Decision[] = []) {
  return request<{ contract: Contract; diff?: ContractDiff }>(
    `/sessions/${sessionId}/architect/refine`,
    {
      method: "POST",
      body: JSON.stringify({ answers }),
    },
  );
}

// ---------------------------------------------------------------------------
// M4: Node update
// ---------------------------------------------------------------------------

export interface NodeUpdateRequest {
  description?: string;
  responsibilities?: string[];
  assumptions?: Assumption[];
}

export interface NodeUpdateResponse {
  node: ContractNode;
  fields_updated: string[];
  provenance_set: Record<string, string>;
}

export function updateNode(
  sessionId: string,
  nodeId: string,
  updates: NodeUpdateRequest,
) {
  return request<NodeUpdateResponse>(
    `/sessions/${sessionId}/nodes/${nodeId}`,
    {
      method: "PATCH",
      body: JSON.stringify(updates),
    },
  );
}

// ---------------------------------------------------------------------------
// M6: Implementation subgraphs
// ---------------------------------------------------------------------------

export interface SubgraphResponse {
  subgraph: ImplementationSubgraph;
}

export interface OptionalSubgraphResponse {
  subgraph: ImplementationSubgraph | null;
}

export interface UpdateSubgraphNodeResponse {
  success: boolean;
  subgraph: ImplementationSubgraph | null;
}

export function generateSubgraph(sessionId: string, nodeId: string) {
  return request<SubgraphResponse>(
    `/sessions/${sessionId}/nodes/${nodeId}/subgraph`,
    { method: "POST" },
  );
}

export function getSubgraph(sessionId: string, nodeId: string) {
  return request<OptionalSubgraphResponse>(
    `/sessions/${sessionId}/nodes/${nodeId}/subgraph`,
    { method: "GET" },
  );
}

export function getAllSubgraphs(sessionId: string) {
  return request<ImplementationSubgraph[]>(
    `/sessions/${sessionId}/subgraphs`,
    { method: "GET" },
  );
}

export function updateSubgraphNodeStatus(
  sessionId: string,
  nodeId: string,
  subgraphNodeId: string,
  status: SubgraphNodeStatus,
  errorMessage?: string,
) {
  return request<UpdateSubgraphNodeResponse>(
    `/sessions/${sessionId}/nodes/${nodeId}/subgraph/nodes/${subgraphNodeId}`,
    {
      method: "PATCH",
      body: JSON.stringify({
        status,
        ...(errorMessage !== undefined ? { error_message: errorMessage } : {}),
      }),
    },
  );
}

export function sessionStreamUrl(sessionId: string): string {
  // Browsers reject mixed http/ws schemes; derive ws/wss from the API base.
  const httpUrl = `${API_BASE}/sessions/${sessionId}/stream`;
  if (httpUrl.startsWith("https://")) return `wss://${httpUrl.slice(8)}`;
  if (httpUrl.startsWith("http://")) return `ws://${httpUrl.slice(7)}`;
  // Relative base: build from window.location.
  if (typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}${API_BASE}/sessions/${sessionId}/stream`;
  }
  return httpUrl;
}

export const API = {
  createSession,
  getSession,
  verifyContract,
  submitAnswers,
  refineContract,
  updateNode,
  generateSubgraph,
  getSubgraph,
  getAllSubgraphs,
  updateSubgraphNodeStatus,
  sessionStreamUrl,
};
