# M0: Static React Flow Mockup

You are implementing Milestone M0 for the Glasshouse project. Read these files first:
- ARCHITECTURE.md (sections 5, 5.1 for frontend layout)
- TODO.md (M0 section for detailed tasks)
- SPEC.md (for understanding the visualization requirements)

## Environment
- Use Node.js (18+ recommended)
- All frontend work goes in `frontend/` directory

## Goal
Build a static React + React Flow visualization that renders architecture contracts as non-overlapping DAGs.

## Tasks
1. Initialize React + Vite + TypeScript project in `frontend/`
2. Install dependencies: `npm install reactflow dagre @types/dagre tailwindcss postcss autoprefixer zustand`
3. Create sample contract JSON files in `public/`:
   - `sample_contract_small.json` (4 nodes, 5 edges)
   - `sample_contract_medium.json` (8 nodes, 12 edges)
4. Implement `Graph.tsx` with dagre layout
5. Implement `NodeCard.tsx` custom node renderer with:
   - Name header, kind badge, status badge
   - Confidence bar (red < 0.5, yellow 0.5-0.8, green > 0.8)
   - First assumption (truncated), expandable details
6. Implement `EdgeLabel.tsx` with hover info
7. Add contract dropdown switcher
8. Style with Tailwind (dark background, light nodes)

## Acceptance Criteria
- `npm run dev` works
- Small contract renders without overlapping nodes
- Medium contract renders without overlapping nodes
- Switching contracts re-renders without page refresh

## Contract Schema Reference
See ARCHITECTURE.md section 4 for the full contract JSON schema. Key structures:
- `nodes[]` with id, name, kind, status, confidence, assumptions
- `edges[]` with id, source, target, kind, payload_schema

Create the branch commit when done: `git add -A && git commit -m "feat(m0): static React Flow mockup with dagre layout"`
