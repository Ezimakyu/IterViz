import { useContractStore } from "../state/contract";
import { useWebSocketStore } from "../state/websocket";
import { API } from "../api/client";
import type { ImplementMode } from "../types/contract";

export function ControlBar() {
  const sessionId = useContractStore((s) => s.sessionId);
  const isLoading = useContractStore((s) => s.isLoading);
  const resetSession = useContractStore((s) => s.resetSession);
  const error = useContractStore((s) => s.error);
  const isImplementing = useContractStore((s) => s.isImplementing);
  const implementationComplete = useContractStore(
    (s) => s.implementationComplete,
  );
  const implement = useContractStore((s) => s.implement);
  const wsConnect = useWebSocketStore((s) => s.connect);

  const canImplement =
    !!sessionId && !isLoading && !isImplementing && !implementationComplete;
  const canDownload = !!sessionId && implementationComplete;

  const startImplement = async (mode: ImplementMode) => {
    if (!sessionId) return;
    wsConnect(sessionId);
    await implement(mode);
  };

  return (
    <header className="flex items-center justify-between border-b border-slate-800 bg-panel px-4 py-3">
      <div className="flex items-baseline gap-3">
        <h1 className="text-lg font-semibold tracking-tight">IterViz</h1>
        <span className="text-xs text-muted">
          {isImplementing
            ? "Implementing…"
            : implementationComplete
            ? "Implementation complete"
            : "Planning"}
        </span>
      </div>

      <div className="flex items-center gap-4 text-sm">
        <button
          type="button"
          className="rounded bg-violet-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-slate-700"
          onClick={() => void startImplement("internal")}
          disabled={!canImplement}
          data-testid="implement-button"
        >
          {isImplementing ? "Implementing…" : "Implement"}
        </button>

        {canDownload && (
          <a
            href={API.downloadGenerated(sessionId)}
            className="rounded bg-amber-500 px-3 py-1.5 text-sm font-semibold text-slate-900 hover:bg-amber-400"
            data-testid="download-button"
          >
            Download
          </a>
        )}

        <button
          type="button"
          className="rounded border border-slate-700 px-2 py-1 text-xs text-muted hover:text-ink"
          onClick={resetSession}
          disabled={isLoading}
          title="Start a new session"
        >
          Reset
        </button>
        {error && (
          <span className="text-xs text-red-400 max-w-[200px] truncate">
            {error}
          </span>
        )}
      </div>
    </header>
  );
}

