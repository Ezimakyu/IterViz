import { useEffect, useMemo, useState } from "react";
import { useContractStore } from "../state/contract";
import type { Decision, Violation } from "../types/contract";

/**
 * Right-side panel listing the Compiler's top questions with answer
 * fields. Submitting POSTs answers and triggers a refine, advancing
 * the iteration counter in the store.
 */
export function QuestionPanel() {
  const questions = useContractStore((s) => s.questions);
  const violations = useContractStore((s) => s.violations);
  const contract = useContractStore((s) => s.contract);
  const isLoading = useContractStore((s) => s.isLoading);
  const setSelectedNode = useContractStore((s) => s.setSelectedNode);
  const setSelectedEdge = useContractStore((s) => s.setSelectedEdge);
  const submit = useContractStore((s) => s.submitAnswersAndRefine);

  // Reset answers whenever the question set changes (e.g. after refine).
  const [answers, setAnswers] = useState<Record<string, string>>({});
  useEffect(() => {
    setAnswers({});
  }, [questions]);

  const violationByQuestion = useMemo(() => {
    const map = new Map<string, Violation>();
    for (const v of violations) {
      if (v.suggested_question) map.set(v.suggested_question, v);
    }
    return map;
  }, [violations]);

  const nodeById = useMemo(() => {
    const m = new Map<string, { id: string; name: string; kind: string }>();
    for (const n of contract?.nodes ?? []) m.set(n.id, n);
    return m;
  }, [contract]);

  const onSubmit = async () => {
    const decisions: Decision[] = questions
      .filter((q) => (answers[q] ?? "").trim().length > 0)
      .map((q) => {
        const v = violationByQuestion.get(q);
        return {
          id: cryptoUUID(),
          question: q,
          answer: answers[q].trim(),
          answered_at: new Date().toISOString(),
          affects: v?.affects ?? [],
          source_violation_id: v?.id ?? null,
        };
      });
    if (decisions.length === 0) return;
    await submit(decisions);
  };

  if (questions.length === 0) {
    return (
      <aside className="flex h-full w-[360px] flex-col gap-3 border-l border-slate-800 bg-panel p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
          Compiler Questions
        </h2>
        <p className="text-sm text-muted">
          Click <span className="text-ink">Verify</span> to ask the Blind
          Compiler what's missing.
        </p>
      </aside>
    );
  }

  return (
    <aside className="flex h-full w-[400px] flex-col gap-3 overflow-y-auto border-l border-slate-800 bg-panel p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
          Compiler Questions ({questions.length})
        </h2>
      </div>

      <ol className="flex flex-col gap-3">
        {questions.map((q, idx) => {
          const v = violationByQuestion.get(q);
          const affects = v?.affects ?? [];
          return (
            <li
              key={`${idx}-${q}`}
              className="rounded border border-slate-700 bg-slate-900/60 p-3"
              data-testid={`question-${idx}`}
            >
              <p className="text-sm leading-snug text-ink">{q}</p>
              {v && (
                <p className="mt-1 text-[11px] text-muted">
                  <span
                    className={
                      v.severity === "error"
                        ? "text-red-400"
                        : "text-yellow-400"
                    }
                  >
                    {v.severity}
                  </span>{" "}
                  · {v.type}
                </p>
              )}
              {affects.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  <span className="text-[11px] text-muted">Affects:</span>
                  {affects.map((id) => {
                    const node = nodeById.get(id);
                    const label = node ? node.name : id.slice(0, 8);
                    return (
                      <button
                        key={id}
                        type="button"
                        className="rounded bg-slate-800 px-2 py-0.5 text-[11px] text-sky-300 hover:bg-slate-700"
                        onClick={() =>
                          node ? setSelectedNode(id) : setSelectedEdge(id)
                        }
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              )}
              <textarea
                className="mt-2 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm text-ink focus:border-sky-500 focus:outline-none"
                rows={2}
                placeholder="Your answer…"
                value={answers[q] ?? ""}
                onChange={(e) =>
                  setAnswers((s) => ({ ...s, [q]: e.target.value }))
                }
                disabled={isLoading}
                data-testid={`question-${idx}-input`}
              />
            </li>
          );
        })}
      </ol>

      <button
        type="button"
        className="mt-2 rounded bg-emerald-600 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-slate-700"
        onClick={() => void onSubmit()}
        disabled={
          isLoading ||
          questions.every((q) => (answers[q] ?? "").trim().length === 0)
        }
        data-testid="submit-answers"
      >
        {isLoading ? "Refining…" : "Submit Answers"}
      </button>
    </aside>
  );
}

function cryptoUUID(): string {
  // Use the WebCrypto API if available, fall back to a Math.random UUID.
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return (crypto as Crypto & { randomUUID(): string }).randomUUID();
  }
  return "id-" + Math.random().toString(36).slice(2);
}
