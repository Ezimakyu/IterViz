import type { Contract } from "../types/contract";

export type Tier = "core" | "feature" | "child" | "orphan";

export interface NodeMeta {
  tier: Tier;
  rank: number;
  /** `true` if the node has no incoming edges. */
  isEntry: boolean;
  /** Parent id when `tier === "child"`, else null. */
  parentId: string | null;
}

export interface Hierarchy {
  byId: Map<string, NodeMeta>;
  /** Max rank across the graph (entry points are rank 0). */
  maxRank: number;
}

/**
 * Per-tier visual/physics constants. Core nodes are the biggest and push
 * hardest; children are small and only weakly repel their parent.
 */
export const TIER_SIZE: Record<Tier, { width: number; height: number }> = {
  core: { width: 240, height: 80 },
  feature: { width: 200, height: 72 },
  child: { width: 160, height: 56 },
  orphan: { width: 160, height: 56 },
};

export const TIER_CHARGE: Record<Tier, number> = {
  core: -1800,
  feature: -1050,
  child: -260,
  orphan: -1400,
};

/** Width of each L->R rank column in the semantic flow layout. */
export const RANK_SPACING = 480;

/**
 * Classify nodes into hierarchy tiers and compute a DAG-style rank
 * (longest path from any entry point). The classification drives both
 * rendering (pill size) and physics (per-tier charge, forceX column).
 */
export function buildHierarchy(contract: Contract): Hierarchy {
  const indeg = new Map<string, number>();
  const outdeg = new Map<string, number>();
  const parents = new Map<string, string[]>();
  const children = new Map<string, string[]>();
  for (const n of contract.nodes) {
    indeg.set(n.id, 0);
    outdeg.set(n.id, 0);
    parents.set(n.id, []);
    children.set(n.id, []);
  }
  for (const e of contract.edges) {
    if (!indeg.has(e.target) || !outdeg.has(e.source)) continue;
    indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1);
    outdeg.set(e.source, (outdeg.get(e.source) ?? 0) + 1);
    parents.get(e.target)!.push(e.source);
    children.get(e.source)!.push(e.target);
  }

  // BFS distance from each entry point (nodes with 0 in-degree). This
  // gives a cycle-safe semantic rank: entry points at column 0, their
  // downstream neighbours at column 1, and so on. First-visit wins so
  // back-edges don't blow up the column count.
  const rank = new Map<string, number>();
  const queue: string[] = [];
  for (const n of contract.nodes) {
    if ((indeg.get(n.id) ?? 0) === 0) {
      rank.set(n.id, 0);
      queue.push(n.id);
    }
  }
  while (queue.length > 0) {
    const id = queue.shift()!;
    const r = rank.get(id)!;
    for (const child of children.get(id) ?? []) {
      if (!rank.has(child)) {
        rank.set(child, r + 1);
        queue.push(child);
      }
    }
  }
  // Nodes only reachable through cycles: place them one column past
  // their highest-ranked predecessor.
  for (const n of contract.nodes) {
    if (rank.has(n.id)) continue;
    let best = 0;
    for (const p of parents.get(n.id) ?? []) {
      if (rank.has(p)) best = Math.max(best, (rank.get(p) ?? 0) + 1);
    }
    rank.set(n.id, best);
  }

  // Tier classification. Core = graph hub (high total degree); child =
  // leaf with one parent which is itself a core; orphan = fully
  // disconnected; everything else is a feature.
  const byId = new Map<string, NodeMeta>();
  const degree = (id: string) =>
    (indeg.get(id) ?? 0) + (outdeg.get(id) ?? 0);
  const isCore = (id: string) =>
    degree(id) >= 3 || (outdeg.get(id) ?? 0) >= 2;

  for (const n of contract.nodes) {
    const d = degree(n.id);
    const isEntry = (indeg.get(n.id) ?? 0) === 0;
    let tier: Tier;
    let parentId: string | null = null;
    if (d === 0) {
      tier = "orphan";
    } else if (isCore(n.id)) {
      tier = "core";
    } else if (
      (indeg.get(n.id) ?? 0) === 1 &&
      (outdeg.get(n.id) ?? 0) <= 1 &&
      (parents.get(n.id)?.[0] != null) &&
      isCore(parents.get(n.id)![0])
    ) {
      tier = "child";
      parentId = parents.get(n.id)![0];
    } else {
      tier = "feature";
    }
    byId.set(n.id, {
      tier,
      rank: rank.get(n.id) ?? 0,
      isEntry,
      parentId,
    });
  }

  let maxRank = 0;
  for (const m of byId.values()) {
    if (m.rank > maxRank) maxRank = m.rank;
  }

  return { byId, maxRank };
}
