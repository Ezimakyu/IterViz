import { Graph } from "./components/Graph";
import { ControlBar } from "./components/ControlBar";
import { PromptInput } from "./components/PromptInput";
import { QuestionPanel } from "./components/QuestionPanel";
import { useContractStore } from "./state/contract";

export default function App() {
  const sessionId = useContractStore((s) => s.sessionId);
  const contract = useContractStore((s) => s.contract);

  if (!sessionId || !contract) {
    return (
      <div className="flex h-screen w-screen items-stretch bg-canvas text-ink">
        <PromptInput />
      </div>
    );
  }

  return (
    <div className="flex h-screen w-screen flex-col bg-canvas text-ink">
      <ControlBar />
      <main className="relative flex flex-1 overflow-hidden">
        <div className="relative flex-1">
          <Graph contract={contract} />
        </div>
        <QuestionPanel />
      </main>
    </div>
  );
}
