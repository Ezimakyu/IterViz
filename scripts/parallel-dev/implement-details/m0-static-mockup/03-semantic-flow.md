# 03 — Semantic Flow & Hierarchy

`src/utils/hierarchy.ts` classifies each node into a **tier** and assigns
it a **rank**. Both feed the layout: tier drives rendered size and
physics charge, rank drives the L→R column it's pinned to.

## Tier classification

```ts
type Tier = "core" | "feature" | "child" | "orphan";
```

Decision tree, evaluated per node after computing in/out degrees:

```
degree(n) === 0                   → orphan
degree(n) ≥ 3  OR  outdeg(n) ≥ 2  → core
indeg(n) === 1
  AND  outdeg(n) ≤ 1
  AND  parent is core             → child  (parentId = parent.id)
otherwise                         → feature
```

Examples on the medium contract:

| Node | indeg | outdeg | Tier |
|---|---:|---:|---|
| `Web UI` | 0 | 2 | core |
| `REST API` | 2 | 4 | core |
| `Auth Service` | 2 | 1 | feature |
| `Postgres` | 3 | 0 | core |
| `Redis Cache` | 1 | 1 | feature |
| `Stripe API` | 1 | 0 | child of REST API |
| `Email Provider` | 1 | 0 | child of Webhook Worker |
| `Webhook Worker` | 1 | 1 | feature |

## Per-tier visuals & physics

Defined in `src/utils/hierarchy.ts`:

```ts
TIER_SIZE = {
  core:    { width: 240, height: 80 },
  feature: { width: 200, height: 72 },
  child:   { width: 160, height: 56 },
  orphan:  { width: 160, height: 56 },
};

TIER_CHARGE = {
  core:    -1800,   // hubs push hardest
  feature: -1050,
  child:   -260,    // children stay near parent
  orphan:  -1400,   // floats out of the way
};
```

The size table also propagates into:

- the pill DOM (`NodeCard.tsx` reads `tier` from node data),
- the collision force (`forceCollide` reads `node.width / node.height`),
- the floating-edge intersection math (`getNodeIntersection`).

## Rank: BFS from entry points

An "entry point" is any node with `indeg === 0`. Rank is computed as the
shortest BFS distance from any entry point. Cycles are handled by giving
each unreached node `max(rank of any predecessor) + 1`:

```ts
// rank.set(entry, 0); BFS over outgoing edges, first-visit wins.
// Then for any node still missing a rank (only reachable through cycles):
//   rank[n] = max(rank[p] + 1 for p in parents(n) if rank.has(p))
```

The rank is then turned into a horizontal target via `forceX`:

```ts
const spanX = max(maxRank, 1) * RANK_SPACING;
targetX = rank * RANK_SPACING - spanX / 2;
```

So rank-0 nodes (entry points) sit at the leftmost column, rank-1 in the
next column, and so on. `forceX` strength is 0.18 — enough to keep nodes
in their column, loose enough that snowflake clustering and label-repel
can still nudge them sideways.

## Putting it together

For the small contract:

```
rank 0           rank 1           rank 2
CLI Entry Point  Data Fetcher     Local Cache
                 Report Writer
```

For the medium contract:

```
rank 0    rank 1       rank 2          rank 3
Web UI    REST API     Auth Service    Postgres
                       Webhook Worker  Redis Cache
                                       Stripe API     (child of REST API)
                                       Email Provider (child of Webhook)
```

This is what produces the user-visible "login → main → backend"
left-to-right flow even though the contract JSON itself has no
positional information.
