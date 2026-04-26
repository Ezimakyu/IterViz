import { create } from "zustand";
import type { WSMessage } from "../types/contract";
import { useContractStore } from "./contract";

/**
 * Live WebSocket store for Phase 2.
 *
 * Connects to ``ws://<api>/sessions/<id>/stream`` and dispatches
 * incoming JSON messages into the contract store so the rest of the
 * UI can stay declarative.
 */

interface WebSocketState {
  socket: WebSocket | null;
  connected: boolean;
  sessionId: string | null;
  reconnectAttempts: number;
  lastError: string | null;

  connect: (sessionId: string) => void;
  disconnect: () => void;
}

const WS_BASE = (
  (import.meta as ImportMeta & { env?: { VITE_WS_BASE?: string } }).env
    ?.VITE_WS_BASE ?? "ws://localhost:8000/api/v1"
);

const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAY_MS = 1500;

function handleMessage(message: WSMessage): void {
  const store = useContractStore.getState();

  switch (message.type) {
    case "node_status_changed": {
      const agent =
        message.agent_id && message.agent_name
          ? { id: message.agent_id, name: message.agent_name }
          : null;
      store.updateNodeStatus(message.node_id, message.status, agent);
      break;
    }
    case "node_claimed": {
      store.updateNodeStatus(message.node_id, "in_progress", {
        id: message.agent_id,
        name: message.agent_name,
      });
      break;
    }
    case "node_progress": {
      store.setNodeProgress(message.node_id, message.progress);
      break;
    }
    case "agent_connected": {
      store.setAgentInfo(message.agent_id, {
        id: message.agent_id,
        name: message.agent_name,
        type: message.agent_type ?? "custom",
        status: "active",
        registered_at: message.timestamp,
        last_seen_at: message.timestamp,
      });
      break;
    }
    case "implementation_complete": {
      store.setImplementationComplete(message.success);
      break;
    }
    case "integration_result": {
      store.setIntegrationMismatches(message.mismatches);
      break;
    }
    case "error": {
      console.warn("[ws] error:", message.message);
      break;
    }
    default:
      break;
  }
}

export const useWebSocketStore = create<WebSocketState>((set, get) => ({
  socket: null,
  connected: false,
  sessionId: null,
  reconnectAttempts: 0,
  lastError: null,

  connect: (sessionId: string) => {
    const existing = get().socket;
    if (existing && get().sessionId === sessionId) return;
    if (existing) existing.close();

    const url = `${WS_BASE}/sessions/${sessionId}/stream`;

    const open = (): void => {
      const socket = new WebSocket(url);

      socket.onopen = () => {
        set({
          socket,
          connected: true,
          sessionId,
          reconnectAttempts: 0,
          lastError: null,
        });
      };

      socket.onmessage = (event: MessageEvent<string>) => {
        try {
          const data = JSON.parse(event.data) as WSMessage;
          handleMessage(data);
        } catch (err) {
          console.error("[ws] failed to parse message", err);
        }
      };

      socket.onclose = () => {
        set({ connected: false });
        const attempts = get().reconnectAttempts;
        if (
          get().sessionId === sessionId &&
          attempts < MAX_RECONNECT_ATTEMPTS
        ) {
          set({ reconnectAttempts: attempts + 1 });
          setTimeout(open, RECONNECT_DELAY_MS);
        }
      };

      socket.onerror = (event: Event) => {
        console.warn("[ws] error", event);
        set({ lastError: "WebSocket connection error" });
      };
    };

    open();
  },

  disconnect: () => {
    const socket = get().socket;
    if (socket) socket.close();
    set({
      socket: null,
      connected: false,
      sessionId: null,
      reconnectAttempts: 0,
    });
  },
}));
