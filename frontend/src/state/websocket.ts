import { useEffect } from "react";
import { API } from "../api/client";
import { useSubgraphStore } from "./subgraph";
import type { WSMessage } from "../types/subgraph";

/**
 * Open a WebSocket to ``/sessions/{id}/stream`` and route incoming
 * subgraph events into the Zustand store. Returns nothing -- the hook
 * cleans itself up on unmount or session-id change.
 *
 * The client stays connected for the lifetime of the session view.
 * The backend currently emits two message types:
 *
 * - ``subgraph_created`` -- a new implementation subgraph was generated.
 * - ``subgraph_node_status_changed`` -- a subgraph node's status moved.
 */
export function useSessionStream(sessionId: string | null): void {
  const upsertSubgraph = useSubgraphStore((s) => s.upsertSubgraph);
  const updateNodeStatus = useSubgraphStore((s) => s.updateNodeStatus);

  useEffect(() => {
    if (!sessionId) return;
    if (typeof window === "undefined") return;

    const url = API.sessionStreamUrl(sessionId);
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (err) {
      console.warn("[ws] failed to open session stream", err);
      return;
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as WSMessage;
        handleMessage(data, upsertSubgraph, updateNodeStatus);
      } catch (err) {
        console.warn("[ws] invalid message", err);
      }
    };

    ws.onerror = () => {
      // Errors fire on the same socket close as well -- we just log.
      console.warn("[ws] connection error");
    };

    return () => {
      try {
        ws.close();
      } catch {
        /* socket already closed */
      }
    };
  }, [sessionId, upsertSubgraph, updateNodeStatus]);
}

function handleMessage(
  msg: WSMessage,
  upsertSubgraph: ReturnType<typeof useSubgraphStore.getState>["upsertSubgraph"],
  updateNodeStatus: ReturnType<
    typeof useSubgraphStore.getState
  >["updateNodeStatus"],
): void {
  switch (msg.type) {
    case "subgraph_created":
      upsertSubgraph(msg.subgraph);
      return;
    case "subgraph_node_status_changed":
      updateNodeStatus(
        msg.parent_node_id,
        msg.subgraph_node_id,
        msg.status,
        msg.progress,
      );
      return;
  }
}
