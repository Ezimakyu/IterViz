import { useContractStore } from "../state/contract";

export function ControlBar() {
  const sessionId = useContractStore((s) => s.sessionId);
  const isLoading = useContractStore((s) => s.isLoading);
  const verify = useContractStore((s) => s.verify);
  const resetSession = useContractStore((s) => s.resetSession);
  const uvdcScore = useContractStore((s) => s.uvdcScore);
  const iteration = useContractStore((s) => s.iteration);
  const violations = useContractStore((s) => s.violations);
  const error = useContractStore((s) => s.error);

  const errorCount = violations.filter((v) => v.severity === "error").length;
  const warningCount = violations.filter((v) => v.severity === "warning").length;

  return (
    <header className="flex items-center justify-between border-b border-slate-800 bg-panel px-4 py-3">
      <div className="flex items-baseline gap-3">
        <h1 className="text-lg font-semibold tracking-tight">Glasshouse</h1>
        <span className="text-xs text-muted">
          M3 · Architect ↔ Compiler ↔ Q&amp;A loop
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
          disabled={!sessionId || isLoading}
          data-testid="verify-button"
        >
          {isLoading ? "Verifying…" : "Verify"}
        </button>
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
