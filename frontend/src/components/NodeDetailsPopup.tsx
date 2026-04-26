import type { ContractNode } from "../types/contract";

const KIND_LABEL: Record<ContractNode["kind"], string> = {
  service: "Service",
  store: "Data Store",
  external: "External Service",
  ui: "UI",
  job: "Event Handler",
  interface: "Interface",
};

const KIND_ACCENT: Record<ContractNode["kind"], string> = {
  service: "border-sky-500 text-sky-300",
  store: "border-emerald-500 text-emerald-300",
  external: "border-fuchsia-500 text-fuchsia-300",
  ui: "border-amber-500 text-amber-300",
  job: "border-indigo-400 text-indigo-300",
  interface: "border-slate-400 text-slate-200",
};

const STATUS_BADGE: Record<ContractNode["status"], string> = {
  drafted: "border-slate-400 text-slate-200",
  in_progress: "border-yellow-400 text-yellow-200",
  implemented: "border-green-400 text-green-200",
  failed: "border-red-400 text-red-200",
};

function confidenceColor(confidence: number): string {
  if (confidence < 0.5) return "bg-red-500";
  if (confidence < 0.8) return "bg-yellow-400";
  return "bg-green-500";
}

interface Props {
  node: ContractNode;
  onClose: () => void;
}

export function NodeDetailsPopup({ node, onClose }: Props) {
  const confidencePct = Math.round(node.confidence * 100);
  return (
    <div
      className="pointer-events-auto absolute right-4 top-4 z-20 flex max-h-[calc(100vh-6rem)] w-[420px] flex-col overflow-hidden rounded-lg border border-slate-700 bg-panel/95 text-ink shadow-2xl backdrop-blur"
      role="dialog"
      aria-label={`Details for ${node.name}`}
    >
      <header className="flex items-start justify-between gap-3 border-b border-slate-700 px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <span
              className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${KIND_ACCENT[node.kind]}`}
            >
              {KIND_LABEL[node.kind]}
            </span>
            <span
              className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${STATUS_BADGE[node.status]}`}
            >
              {node.status.replace("_", " ")}
            </span>
          </div>
          <h2 className="mt-1.5 text-base font-semibold leading-tight">
            {node.name}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded p-1 text-muted hover:bg-slate-700/60 hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
          aria-label="Close details"
        >
          <svg
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M6 6l12 12M18 6l-12 12" />
          </svg>
        </button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 text-xs leading-snug text-slate-200">
        <div>
          <div className="flex items-center justify-between text-[10px] uppercase tracking-wide text-muted">
            <span>Confidence</span>
            <span>{confidencePct}%</span>
          </div>
          <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-700">
            <div
              className={`h-full ${confidenceColor(node.confidence)}`}
              style={{ width: `${confidencePct}%` }}
            />
          </div>
        </div>

        {node.description && (
          <p className="leading-relaxed">{node.description}</p>
        )}

        {node.responsibilities && node.responsibilities.length > 0 && (
          <section>
            <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
              Responsibilities
            </h3>
            <ul className="ml-4 list-disc space-y-0.5">
              {node.responsibilities.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </section>
        )}

        {node.assumptions && node.assumptions.length > 0 && (
          <section>
            <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
              Assumptions
            </h3>
            <ul className="ml-4 list-disc space-y-0.5">
              {node.assumptions.map((a, i) => (
                <li key={i}>
                  {a.text}{" "}
                  <span className="text-muted">
                    ({Math.round(a.confidence * 100)}
                    {a.load_bearing ? ", load-bearing" : ""})
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {node.open_questions && node.open_questions.length > 0 && (
          <section>
            <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
              Open questions
            </h3>
            <ul className="ml-4 list-disc space-y-0.5">
              {node.open_questions.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ul>
          </section>
        )}

        {node.decided_by && (
          <p className="text-[10px] uppercase tracking-wide text-muted">
            decided by · {node.decided_by}
          </p>
        )}
      </div>
    </div>
  );
}
