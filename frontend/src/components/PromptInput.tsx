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
            IterViz will generate an architecture plan from your prompt
            that you can then implement with AI agents.
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

        {isLoading ? (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3 text-sm text-muted">
              <LoadingSpinner />
              <span>Generating architecture plan...</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-700">
              <div className="h-full w-1/3 animate-pulse bg-sky-500 transition-all duration-300" />
            </div>
            <p className="text-xs text-muted">
              This may take a minute depending on the complexity of your request.
            </p>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="rounded bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-700"
              onClick={submit}
              disabled={!prompt.trim()}
              data-testid="prompt-submit"
            >
              Generate Plan
            </button>
            <button
              type="button"
              className="rounded border border-slate-700 px-3 py-2 text-xs text-muted hover:text-ink"
              onClick={() => setPrompt(SAMPLE_PROMPT)}
            >
              Use sample prompt
            </button>
            {error && (
              <span className="text-xs text-red-400">{error}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function LoadingSpinner() {
  return (
    <svg
      className="h-4 w-4 animate-spin text-sky-400"
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}
