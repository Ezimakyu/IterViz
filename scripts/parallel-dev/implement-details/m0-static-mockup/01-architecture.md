# 01 — Architecture

## File layout

```
frontend/
├── public/
│   ├── sample_contract_small.json     4 nodes, 5 edges (CLI tool)
│   └── sample_contract_medium.json    8 nodes, 12 edges (web app + auth + DB)
└── src/
    ├── App.tsx                        Header + dropdown + <Graph>
    ├── main.tsx                       React entrypoint
    ├── index.css                      Tailwind + a few RF-overrides
    ├── state/
    │   └── contract.ts                Zustand store (active contract + selection)
    ├── types/
    │   └── contract.ts                Contract / Node / Edge TS types
    ├── utils/
    │   ├── hierarchy.ts               Tier classification + BFS rank
    │   ├── floatingEdges.ts           Intersection + side-picking helpers
    │   ├── edgeKind.ts                Kind → colour/label mapping
    │   └── layout.ts                  Default NODE_WIDTH / NODE_HEIGHT fallback
    ├── hooks/
    │   └── useForceLayout.ts          d3-force simulation + tick → RF bridge
    └── components/
        ├── Graph.tsx                  React Flow canvas
        ├── NodeCard.tsx               Pill node renderer
        ├── EdgeLabel.tsx              Floating edge + kind pill button
        ├── NodeDetailsPopup.tsx       Top-right scrollable popup
        └── EdgeDetailsPopup.tsx       Bottom-right scrollable popup
```

## Data flow

```
public/*.json
   │  fetch (in App.tsx on dropdown change)
   ▼
contract: Contract  ─────►  useContractStore (Zustand)
   │                                │
   │                                ├─ selectedNodeId
   │                                └─ selectedEdgeId
   ▼
buildHierarchy(contract)           │
   │  → byId: Map<id, NodeMeta>    │
   │  → maxRank                    │
   ▼                                │
useForceLayout(contract, {boostedId, hierarchy})
   │
   │  d3-force simulation  ──tick──►  setNodes / setEdges (React Flow)
   ▼
ReactFlow renders <NodeCard> + <EdgeLabel> per element
```

The contract JSON is fetched in `App.tsx` whenever the dropdown changes. The
result is normalised into the Zustand store. `Graph.tsx` reads the contract
out of the store, builds the hierarchy synchronously (cheap — O(V+E)), and
hands both off to `useForceLayout`. The hook owns the simulation and pushes
positions back into React Flow on every tick via `useReactFlow().setNodes`.

## Key types

```ts
// src/types/contract.ts
interface ContractNode {
  id: string;
  name: string;
  kind: "ui" | "service" | "data_store" | "external" | "interface" | ...;
  status: "active" | "draft" | "deprecated";
  confidence: number;        // 0..1
  description?: string;
  responsibilities?: string[];
  assumptions?: string[];
  open_questions?: string[];
}

interface ContractEdge {
  id: string;
  source: string;            // node id
  target: string;            // node id
  kind: "data" | "control" | "event" | "dependency";
  label?: string;
  payload_schema?: Record<string, unknown>;
}
```

## Component responsibilities at a glance

| Component | Owns | Reads | Writes |
|---|---|---|---|
| `App` | dropdown state, JSON fetch | — | store.setContract |
| `Graph` | React Flow lifecycle | store.selectedXxx | store.toggleSelectedXxx |
| `useForceLayout` | d3 sim, custom forces | contract, hierarchy, boostedId | RF nodes via setNodes |
| `NodeCard` | pill rendering | tier, name, confidence | — |
| `EdgeLabel` | floating path + kind pill | edge, RF coords | — |
| `NodeDetailsPopup` | popup chrome | node | onClose |
| `EdgeDetailsPopup` | popup chrome | edge | onClose |

`Graph.tsx` deliberately uses React Flow in **uncontrolled** mode
(`defaultNodes={[]}` / `defaultEdges={[]}`). The simulation is the source of
truth for positions; React Flow is only the renderer and event source.
