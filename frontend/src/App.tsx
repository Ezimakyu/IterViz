import { useEffect } from "react";
import { Graph } from "./components/Graph";
import { CONTRACT_CATALOG, useContractStore } from "./state/contract";

export default function App() {
  const { selectedId, contract, loading, error, selectContract } =
    useContractStore();

  useEffect(() => {
    void selectContract(selectedId);
    // Only run on mount; subsequent loads happen via the dropdown handler.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex h-screen w-screen flex-col bg-canvas text-ink">
      <header className="flex items-center justify-between border-b border-slate-800 bg-panel px-4 py-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-lg font-semibold tracking-tight">Glasshouse</h1>
          <span className="text-xs text-muted">
            M0 · static architecture contract viewer
          </span>
        </div>
        <div className="flex items-center gap-2">
          <label
            htmlFor="contract-select"
            className="text-xs uppercase tracking-wide text-muted"
          >
            Contract
          </label>
          <select
            id="contract-select"
            className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-ink focus:border-sky-500 focus:outline-none"
            value={selectedId}
            onChange={(e) => {
              void selectContract(e.target.value);
            }}
          >
            {CONTRACT_CATALOG.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.label}
              </option>
            ))}
          </select>
        </div>
      </header>

      <main className="relative flex-1">
        {error && (
          <div className="absolute left-1/2 top-4 z-10 -translate-x-1/2 rounded border border-red-700 bg-red-900/80 px-3 py-2 text-sm text-red-100">
            Failed to load contract: {error}
          </div>
        )}
        {loading && !contract && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-muted">
            Loading contract…
          </div>
        )}
        {contract && <Graph contract={contract} />}
      </main>
    </div>
  );
}
