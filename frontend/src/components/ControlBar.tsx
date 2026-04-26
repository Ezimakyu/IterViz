import { useContractStore } from "../state/contract";
import { useWebSocketStore } from "../state/websocket";
import { API } from "../api/client";
import type { ImplementMode } from "../types/contract";

export function ControlBar() {
  const sessionId = useContractStore((s) => s.sessionId);
  const isLoading = useContractStore((s) => s.isLoading);
  const verify = useContractStore((s) => s.verify);
  const resetSession = useContractStore((s) => s.resetSession);
  const uvdcScore = useContractStore((s) => s.uvdcScore);
  const iteration = useContractStore((s) => s.iteration);
  const violations = useContractStore((s) => s.violations);
  const error = useContractStore((s) => s.error);
  const isFrozen = useContractStore((s) => s.isFrozen);
  const isImplementing = useContractStore((s) => s.isImplementing);
  const implementationComplete = useContractStore(
    (s) => s.implementationComplete,
  );
  const freeze = useContractStore((s) => s.freeze);
  const implement = useContractStore((s) => s.implement);
  const wsConnect = useWebSocketStore((s) => s.connect);

  const errorCount = violations.filter((v) => v.severity === "error").length;
  const warningCount = violations.filter((v) => v.severity === "warning").length;
  const canFreeze =
    !!sessionId && !isLoading && !isFrozen && uvdcScore >= 1.0 && errorCount === 0;
  const canImplement =
    !!sessionId && !isLoading && isFrozen && !isImplementing && !implementationComplete;
  const canDownload = !!sessionId && implementationComplete;

  const startImplement = async (mode: ImplementMode) => {
    if (!sessionId) return;
    wsConnect(sessionId);
    await implement(mode);
  };

  return (
    <header className="flex items-center justify-between border-b border-slate-800 bg-panel px-4 py-3">
      <div className="flex items-baseline gap-3">
        <h1 className="text-lg font-semibold tracking-tight">Glasshouse</h1>
        <span className="text-xs text-muted">
          {isImplementing
            ? "M5 · Phase 2 implementing…"
            : isFrozen
            ? "M5 · Phase 2 ready"
            : "M3 · Architect ↔ Compiler ↔ Q&A loop"}
        </span>
      </div>

      <div className="flex items-center gap-4 text-sm">
        <Stat label="Iteration" value={`${iteration}/3`} />
        <Stat
          label="Coverage"
          value={`${Math.round(uvdcScore * 100)}%`}
          tone={uvdcScore >= 0.8 ? "good" : uvdcScore >= 0.5 ? "warn" : "bad"}
        />
        <Stat
          label="Violations"
          value={`${errorCount}E / ${warningCount}W`}
          tone={errorCount === 0 ? "good" : "bad"}
        />

        <button
          type="button"
          className="rounded bg-sky-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-700"
          onClick={() => void verify()}
          disabled={!sessionId || isLoading || isFrozen}
          data-testid="verify-button"
        >
          {isLoading ? "Verifying…" : "Verify"}
        </button>

        <button
          type="button"
          className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-slate-700"
          onClick={() => void freeze()}
          disabled={!canFreeze}
          data-testid="freeze-button"
          title={
            isFrozen
              ? "Contract is frozen"
              : uvdcScore >= 1.0
              ? "Freeze the contract for implementation"
              : "Reach 100% coverage with 0 errors before freezing"
          }
        >
          {isFrozen ? "Frozen" : "Freeze"}
        </button>

        <button
          type="button"
          className="rounded bg-violet-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-slate-700"
          onClick={() => void startImplement("internal")}
          disabled={!canImplement}
          data-testid="implement-internal-button"
        >
          Implement (internal)
        </button>

        <button
          type="button"
          className="rounded border border-violet-500 bg-transparent px-3 py-1.5 text-sm font-semibold text-violet-300 hover:bg-violet-500/10 disabled:cursor-not-allowed disabled:opacity-50"
          onClick={() => void startImplement("external")}
          disabled={!canImplement}
          data-testid="implement-external-button"
        >
          Implement (external)
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

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "warn" | "bad";
}) {
  const toneClass =
    tone === "good"
      ? "text-emerald-400"
      : tone === "warn"
      ? "text-yellow-400"
      : tone === "bad"
      ? "text-red-400"
      : "text-ink";
  return (
    <div className="flex flex-col items-end leading-tight">
      <span className="text-[10px] uppercase tracking-wide text-muted">
        {label}
      </span>
      <span className={`text-sm font-semibold ${toneClass}`}>{value}</span>
    </div>
  );
}
