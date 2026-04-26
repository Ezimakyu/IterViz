import { useEffect, useMemo, useState } from "react";
import type { ContractNode } from "../types/contract";
import { useContractStore } from "../state/contract";

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
  const updateNodeField = useContractStore((s) => s.updateNodeField);
  const userEditedFields = useContractStore((s) => s.userEditedFields);
  const isLoading = useContractStore((s) => s.isLoading);
  const editedFields = userEditedFields[node.id] ?? [];

  const isUserEdited =
    editedFields.length > 0 || node.decided_by === "user";

  // Local edit state for description / responsibilities. We commit on
  // blur or Cmd/Ctrl+Enter.
  const [editingField, setEditingField] = useState<
    "description" | "responsibilities" | null
  >(null);
  const [draftDescription, setDraftDescription] = useState(
    node.description ?? "",
  );
  const [draftResponsibilities, setDraftResponsibilities] = useState(
    (node.responsibilities ?? []).join("\n"),
  );

  // Re-sync local drafts whenever the user opens a different node or the
  // backend sends back an update (e.g. after a remote edit).
  useEffect(() => {
    setDraftDescription(node.description ?? "");
    setDraftResponsibilities((node.responsibilities ?? []).join("\n"));
    setEditingField(null);
  }, [node.id, node.description, node.responsibilities]);

  const isDescriptionEdited = editedFields.includes("description");
  const isResponsibilitiesEdited = editedFields.includes("responsibilities");

  const fieldEditedClass = (edited: boolean) =>
    edited ? "border-l-2 border-blue-500 pl-2" : "";

  const commitDescription = async () => {
    setEditingField(null);
    if (draftDescription === (node.description ?? "")) return;
    await updateNodeField(node.id, "description", draftDescription);
  };

  const commitResponsibilities = async () => {
    setEditingField(null);
    const next = draftResponsibilities
      .split("\n")
      .map((r) => r.trim())
      .filter(Boolean);
    const current = node.responsibilities ?? [];
    if (
      next.length === current.length &&
      next.every((v, i) => v === current[i])
    ) {
      return;
    }
    await updateNodeField(node.id, "responsibilities", next);
  };

  const cancelEditing = () => {
    setEditingField(null);
    setDraftDescription(node.description ?? "");
    setDraftResponsibilities((node.responsibilities ?? []).join("\n"));
  };

  const provenanceTone = useMemo(() => {
    if (node.decided_by === "user") return "text-blue-300";
    if (node.decided_by === "prompt") return "text-emerald-300";
    return "text-slate-400";
  }, [node.decided_by]);

  return (
    <div
      className="pointer-events-auto absolute right-4 top-4 z-20 flex max-h-[calc(100vh-6rem)] w-[440px] flex-col overflow-hidden rounded-lg border border-slate-700 bg-panel/95 text-ink shadow-2xl backdrop-blur"
      role="dialog"
      aria-label={`Details for ${node.name}`}
    >
      <header
        className={`flex items-start justify-between gap-3 border-b border-slate-700 px-4 py-3 ${
          isUserEdited ? "bg-blue-900/20" : ""
        }`}
      >
        <div>
          <div className="flex flex-wrap items-center gap-2">
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
            {isUserEdited && (
              <span className="rounded border border-blue-400 bg-blue-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-200">
                User-edited
              </span>
            )}
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

        <section>
          <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            Description{" "}
            <span className="text-[9px] font-normal normal-case text-slate-500">
              (click to edit)
            </span>
          </h3>
          {editingField === "description" ? (
            <textarea
              data-testid={`node-edit-description-${node.id}`}
              className="w-full resize-y rounded border border-blue-500 bg-slate-800/80 p-2 text-sm leading-relaxed text-slate-100 focus:outline-none focus:ring-1 focus:ring-blue-400"
              value={draftDescription}
              onChange={(e) => setDraftDescription(e.target.value)}
              onBlur={commitDescription}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  commitDescription();
                }
                if (e.key === "Escape") {
                  e.preventDefault();
                  cancelEditing();
                }
              }}
              autoFocus
              rows={4}
              disabled={isLoading}
            />
          ) : (
            <p
              role="button"
              tabIndex={0}
              data-testid={`node-description-${node.id}`}
              className={`cursor-text rounded p-1 text-sm leading-relaxed text-slate-100 hover:bg-slate-700/40 ${fieldEditedClass(
                isDescriptionEdited,
              )}`}
              onClick={() => setEditingField("description")}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setEditingField("description");
                }
              }}
              title="Click to edit"
            >
              {node.description?.trim() || (
                <span className="italic text-slate-500">
                  Click to add a description
                </span>
              )}
            </p>
          )}
        </section>

        <section>
          <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            Responsibilities{" "}
            <span className="text-[9px] font-normal normal-case text-slate-500">
              (click to edit, one per line)
            </span>
          </h3>
          {editingField === "responsibilities" ? (
            <textarea
              data-testid={`node-edit-responsibilities-${node.id}`}
              className="w-full resize-y rounded border border-blue-500 bg-slate-800/80 p-2 text-sm leading-relaxed text-slate-100 focus:outline-none focus:ring-1 focus:ring-blue-400"
              value={draftResponsibilities}
              onChange={(e) => setDraftResponsibilities(e.target.value)}
              onBlur={commitResponsibilities}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  commitResponsibilities();
                }
                if (e.key === "Escape") {
                  e.preventDefault();
                  cancelEditing();
                }
              }}
              autoFocus
              rows={4}
              disabled={isLoading}
              placeholder="One responsibility per line"
            />
          ) : (
            <ul
              role="button"
              tabIndex={0}
              data-testid={`node-responsibilities-${node.id}`}
              className={`ml-4 list-disc cursor-text space-y-0.5 rounded p-1 hover:bg-slate-700/40 ${fieldEditedClass(
                isResponsibilitiesEdited,
              )}`}
              onClick={() => setEditingField("responsibilities")}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setEditingField("responsibilities");
                }
              }}
              title="Click to edit"
            >
              {(node.responsibilities ?? []).length > 0 ? (
                (node.responsibilities ?? []).map((r, i) => (
                  <li key={i}>{r}</li>
                ))
              ) : (
                <li className="list-none italic text-slate-500">
                  Click to add responsibilities
                </li>
              )}
            </ul>
          )}
        </section>

        {node.assumptions && node.assumptions.length > 0 && (
          <section>
            <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
              Assumptions
            </h3>
            <ul className="ml-4 list-disc space-y-0.5">
              {node.assumptions.map((a, i) => (
                <li
                  key={i}
                  className={
                    a.decided_by === "user"
                      ? "border-l-2 border-blue-500 pl-2"
                      : ""
                  }
                >
                  {a.text}{" "}
                  <span className="text-muted">
                    ({Math.round(a.confidence * 100)}
                    {a.load_bearing ? ", load-bearing" : ""}
                    {a.decided_by ? `, by ${a.decided_by}` : ""})
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
          <p
            className={`text-[10px] uppercase tracking-wide ${provenanceTone}`}
          >
            decided by · {node.decided_by}
          </p>
        )}
      </div>
    </div>
  );
}
