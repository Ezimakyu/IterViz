import { useEffect, useState } from "react";
import { Graph } from "./components/Graph";
import { ControlBar } from "./components/ControlBar";
import { PromptInput } from "./components/PromptInput";
import { InfoPanelContent, useInfoPanelTitle } from "./components/InfoPanel";
import { AgentPanelContent, useAgentPanelVisible } from "./components/AgentPanel";
import { ResizablePanel } from "./components/ResizablePanel";
import { useContractStore } from "./state/contract";
import { useWebSocketStore } from "./state/websocket";

export default function App() {
  const sessionId = useContractStore((s) => s.sessionId);
  const contract = useContractStore((s) => s.contract);
  const wsConnect = useWebSocketStore((s) => s.connect);

  const [infoPanelOpen, setInfoPanelOpen] = useState(true);
  const [agentPanelOpen, setAgentPanelOpen] = useState(true);

  const infoPanelTitle = useInfoPanelTitle();
  const agentPanelVisible = useAgentPanelVisible();

  useEffect(() => {
    if (sessionId) wsConnect(sessionId);
  }, [sessionId, wsConnect]);

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
        <ResizablePanel
          title={infoPanelTitle}
          side="right"
          defaultWidth={400}
          minWidth={280}
          maxWidth={600}
          isOpen={infoPanelOpen}
          onToggle={() => setInfoPanelOpen(!infoPanelOpen)}
          testId="info-panel"
        >
          <InfoPanelContent />
        </ResizablePanel>
        {agentPanelVisible && (
          <ResizablePanel
            title="Phase 2 — Agents"
            side="right"
            defaultWidth={288}
            minWidth={200}
            maxWidth={450}
            isOpen={agentPanelOpen}
            onToggle={() => setAgentPanelOpen(!agentPanelOpen)}
            testId="agent-panel"
          >
            <AgentPanelContent />
          </ResizablePanel>
        )}
      </main>
    </div>
  );
}
