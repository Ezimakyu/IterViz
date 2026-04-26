import { useState } from "react";
import { useContractStore } from "../state/contract";

const SAMPLE_PROMPT = "Build a Slack bot that summarizes unread DMs daily.";

export function PromptInput() {
  const startSession = useContractStore((s) => s.startSession);
  const isLoading = useContractStore((s) => s.isLoading);
  const error = useContractStore((s) => s.error);
  const [prompt, setPrompt] = useState("");

  const submit = async () => {
    if (!prompt.trim() || isLoading) return;
    await startSession(prompt.trim());
  };

  return (
    <div className="flex h-full w-full items-center justify-center p-8">
      <div className="flex w-full max-w-2xl flex-col gap-4 rounded-lg border border-slate-700 bg-panel p-6 shadow-xl">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">
            Describe what you want to build
          </h2>
          <p className="mt-1 text-sm text-muted">
            Glasshouse will draft an architecture contract from your prompt
            and run the Blind Compiler against it.
          </p>
        </div>

        <textarea
          className="min-h-[160px] w-full resize-y rounded border border-slate-700 bg-slate-900 p-3 text-sm text-ink placeholder:text-slate-600 focus:border-sky-500 focus:outline-none"
          placeholder={SAMPLE_PROMPT}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          disabled={isLoading}
          data-testid="prompt-input"
        />

        <div className="flex items-center gap-3">
          <button
            type="button"
            className="rounded bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-700"
            onClick={submit}
            disabled={isLoading || !prompt.trim()}
            data-testid="prompt-submit"
          >
            {isLoading ? "Drafting…" : "Architect"}
          </button>
          <button
            type="button"
            className="rounded border border-slate-700 px-3 py-2 text-xs text-muted hover:text-ink"
            onClick={() => setPrompt(SAMPLE_PROMPT)}
            disabled={isLoading}
          >
            Use sample prompt
          </button>
          {error && (
            <span className="text-xs text-red-400">{error}</span>
          )}
        </div>
      </div>
    </div>
  );
}
