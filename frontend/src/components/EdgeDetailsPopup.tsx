import type { ContractEdge } from "../types/contract";
import { EDGE_KIND_COLOR, payloadSummary } from "../utils/edgeKind";

interface Props {
  edge: ContractEdge;
  sourceName: string;
  targetName: string;
  onClose: () => void;
}

export function EdgeDetailsPopup({
  edge,
  sourceName,
  targetName,
  onClose,
}: Props) {
  const color = EDGE_KIND_COLOR[edge.kind];
  const fieldCount = edge.payload_schema?.properties
    ? Object.keys(edge.payload_schema.properties).length
    : 0;
  const required = edge.payload_schema?.required ?? [];
  const properties = edge.payload_schema?.properties ?? {};
  const confidencePct =
    edge.confidence !== undefined ? Math.round(edge.confidence * 100) : null;

  return (
    <div
      className="pointer-events-auto absolute bottom-4 right-4 z-20 flex max-h-[50vh] w-[320px] flex-col overflow-hidden rounded-lg border border-slate-700 bg-panel/95 text-ink shadow-2xl backdrop-blur"
      role="dialog"
      aria-label={`Edge details: ${sourceName} to ${targetName}`}
    >
      <header className="flex items-start justify-between gap-3 border-b border-slate-700 px-3 py-2">
        <div className="min-w-0">
          <span
            className="inline-block rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide"
            style={{ borderColor: color, color }}
          >
            {edge.kind}
          </span>
          <h2 className="mt-1 truncate text-sm font-semibold">
            {sourceName} → {targetName}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded p-1 text-muted hover:bg-slate-700/60 hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
          aria-label="Close edge details"
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

      <div className="flex-1 space-y-2 overflow-y-auto px-3 py-2 text-[11px] leading-snug text-slate-200">
        {edge.label && (
          <p>
            <span className="text-muted">Label · </span>
            {edge.label}
          </p>
        )}
        <p>
          <span className="text-muted">Payload · </span>
          {payloadSummary(edge.payload_schema)}
        </p>

        {fieldCount > 0 && (
          <section>
            <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
              Fields
            </h3>
            <ul className="ml-4 list-disc space-y-0.5">
              {Object.entries(properties).map(([name, schema]) => {
                const type =
                  typeof schema === "object" &&
                  schema !== null &&
                  "type" in (schema as Record<string, unknown>)
                    ? String((schema as Record<string, unknown>).type)
                    : "any";
                return (
                  <li key={name}>
                    <code className="font-mono text-sky-300">{name}</code>
                    <span className="text-muted">
                      {" "}
                      : {type}
                      {required.includes(name) ? " · required" : ""}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {confidencePct !== null && (
          <p className="text-[10px] uppercase tracking-wide text-muted">
            confidence · {confidencePct}%
          </p>
        )}
        {edge.decided_by && (
          <p className="text-[10px] uppercase tracking-wide text-muted">
            decided by · {edge.decided_by}
          </p>
        )}
      </div>
    </div>
  );
}
