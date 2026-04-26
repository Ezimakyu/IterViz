import { useContractStore } from "../state/contract";

/**
 * Side panel listing connected agents and the nodes they're working on.
 *
 * Renders only when a Phase 2 implementation is in flight (or just
 * completed) so it stays out of the way during Phase 1.
 */
export function AgentPanel() {
  const isImplementing = useContractStore((s) => s.isImplementing);
  const implementationComplete = useContractStore(
    (s) => s.implementationComplete,
  );
  const implementationSuccess = useContractStore(
    (s) => s.implementationSuccess,
  );
  const connectedAgents = useContractStore((s) => s.connectedAgents);
  const nodeAgents = useContractStore((s) => s.nodeAgents);
  const contract = useContractStore((s) => s.contract);

  if (!isImplementing && !implementationComplete) return null;

  const agentToNodes = new Map<string, string[]>();
  if (contract) {
    nodeAgents.forEach((info, nodeId) => {
      const node = contract.nodes.find((n) => n.id === nodeId);
      const list = agentToNodes.get(info.agentId) ?? [];
      list.push(node?.name ?? nodeId);
      agentToNodes.set(info.agentId, list);
    });
  }

  const agents = Array.from(connectedAgents.values());

  return (
    <aside
      className="w-72 shrink-0 border-l border-slate-800 bg-panel p-4 text-sm overflow-auto"
      data-testid="agent-panel"
    >
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted">
        Phase 2 — Agents
      </h2>

      {implementationComplete && (
        <div
          className={`mb-3 rounded border px-2 py-1 text-xs ${
            implementationSuccess
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
              : "border-red-500/40 bg-red-500/10 text-red-200"
          }`}
        >
          {implementationSuccess
            ? "Implementation complete"
            : "Implementation finished with failures"}
        </div>
      )}

      {agents.length === 0 ? (
        <div className="text-xs text-muted">
          {isImplementing
            ? "Waiting for agents to connect…"
            : "No agents connected."}
        </div>
      ) : (
        <ul className="space-y-3">
          {agents.map((agent) => {
            const nodes = agentToNodes.get(agent.id) ?? [];
            return (
              <li
                key={agent.id}
                className="rounded border border-slate-700 bg-slate-900/40 p-2"
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold">{agent.name}</span>
                  <span
                    className={`text-[10px] uppercase tracking-wide ${
                      agent.status === "active"
                        ? "text-emerald-400"
                        : agent.status === "disconnected"
                        ? "text-red-400"
                        : "text-muted"
                    }`}
                  >
                    {agent.status}
                  </span>
                </div>
                <div className="text-[10px] uppercase tracking-wide text-muted">
                  {agent.type}
                </div>
                {nodes.length > 0 && (
                  <ul className="mt-2 space-y-0.5 text-xs text-slate-300">
                    {nodes.map((name) => (
                      <li key={name} className="truncate">
                        ↳ {name}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
