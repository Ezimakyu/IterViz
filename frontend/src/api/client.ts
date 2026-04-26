/**
 * Thin fetch wrappers for the Glasshouse v1 backend.
 *
 * All helpers throw on transport failures (network down, JSON-parse
 * errors) but return a structured `{ ok: false, status, detail }` for
 * 4xx/5xx responses so the UI can render a friendly error.
 */

import type {
  Agent,
  CompilerResponse,
  Contract,
  ContractDiff,
  Decision,
  FreezeResponse,
  ImplementMode,
  ImplementResponse,
  ListAgentsResponse,
  RegisterAgentResponse,
} from "../types/contract";

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
// M5: Phase 2 endpoints
// ---------------------------------------------------------------------------

export function freezeContract(sessionId: string) {
  return request<FreezeResponse>(`/sessions/${sessionId}/freeze`, {
    method: "POST",
  });
}

export function startImplementation(
  sessionId: string,
  mode: ImplementMode = "internal",
) {
  return request<ImplementResponse>(`/sessions/${sessionId}/implement`, {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

export function registerAgent(name: string, type: Agent["type"] = "custom") {
  return request<RegisterAgentResponse>(`/agents`, {
    method: "POST",
    body: JSON.stringify({ name, type }),
  });
}

export function listAgents() {
  return request<ListAgentsResponse>(`/agents`, { method: "GET" });
}

export function downloadGenerated(sessionId: string) {
  return `${API_BASE}/sessions/${sessionId}/generated`;
}

export const API = {
  createSession,
  getSession,
  verifyContract,
  submitAnswers,
  refineContract,
  freezeContract,
  startImplementation,
  registerAgent,
  listAgents,
  downloadGenerated,
};
