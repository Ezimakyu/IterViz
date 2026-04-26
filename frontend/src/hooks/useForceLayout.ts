import { useEffect, useRef } from "react";
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { useReactFlow, type Edge, type Node } from "reactflow";
import type { Contract } from "../types/contract";
import type { NodeCardData } from "../components/NodeCard";
import type { EdgeData } from "../components/EdgeLabel";
import {
  type Hierarchy,
  RANK_SPACING,
  TIER_CHARGE,
  TIER_SIZE,
} from "../utils/hierarchy";

interface SimNode extends SimulationNodeDatum {
  id: string;
  width: number;
  height: number;
  targetX: number;
  /** Parent id for child-tier nodes; used for snowflake clustering. */
  parentId: string | null;
  tier: keyof typeof TIER_CHARGE;
}

type SimLink = SimulationLinkDatum<SimNode> & { id: string };

const BOOST_CHARGE = -2800;
const LINK_DISTANCE = 380;
const CHILD_LINK_DISTANCE = 240;
/** Min clearance from any edge midpoint to a non-adjacent node. */
const LABEL_CLEARANCE = 140;
/** Min clearance between two edge midpoints (label-vs-label). */
const LABEL_LABEL_CLEARANCE = 130;

interface Options {
  boostedId: string | null;
  hierarchy: Hierarchy;
}

/**
 * Runs a d3-force simulation over the contract's nodes/edges and pushes
 * updated positions into React Flow on every tick. The simulation never
 * fully cools, so nodes gently jiggle (Obsidian-style) and react to
 * dragging and selection in real time.
 *
 * Layout semantics:
 *  - Per-tier charge (core pushes hardest, children stay near parent).
 *  - `forceX` pinned by DAG rank gives a left-to-right flow (entry
 *    points leftmost, downstream to the right).
 *  - A custom label-repel force pushes unrelated nodes away from the
 *    midpoint of every edge so the edge kind pill stays readable.
 */
export function useForceLayout(contract: Contract | null, opts: Options) {
  const { setNodes, setEdges, getNodes } = useReactFlow();
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const boostedRef = useRef<string | null>(null);

  useEffect(() => {
    boostedRef.current = opts.boostedId;
    const sim = simRef.current;
    if (sim) {
      sim.alpha(Math.max(sim.alpha(), 0.6)).restart();
    }
  }, [opts.boostedId]);

  const hierarchy = opts.hierarchy;

  useEffect(() => {
    if (!contract) return;

    const count = contract.nodes.length;
    const spanX = Math.max(hierarchy.maxRank, 1) * RANK_SPACING;
    const simNodes: SimNode[] = contract.nodes.map((n, i) => {
      const meta = hierarchy.byId.get(n.id);
      const tier = meta?.tier ?? "feature";
      const size = TIER_SIZE[tier];
      const rank = meta?.rank ?? 0;
      const targetX = rank * RANK_SPACING - spanX / 2;
      // Seed Y in a vertical fan so overlapping starts dissipate fast.
      const lane = (i / Math.max(count, 1) - 0.5) * 320;
      return {
        id: n.id,
        x: targetX + (Math.random() - 0.5) * 40,
        y: lane + (Math.random() - 0.5) * 40,
        vx: 0,
        vy: 0,
        width: size.width,
        height: size.height,
        targetX,
        parentId: meta?.parentId ?? null,
        tier,
      };
    });
    const simLinks: SimLink[] = contract.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
    }));

    const charge = forceManyBody<SimNode>().strength((n) =>
      n.id === boostedRef.current ? BOOST_CHARGE : TIER_CHARGE[n.tier],
    );
    const link = forceLink<SimNode, SimLink>(simLinks)
      .id((d) => d.id)
      .distance((l) => {
        const s = l.source as SimNode;
        const t = l.target as SimNode;
        if (s.tier === "child" || t.tier === "child") return CHILD_LINK_DISTANCE;
        return LINK_DISTANCE;
      })
      .strength(0.45);
    const collide = forceCollide<SimNode>((n) => {
      return Math.max(n.width, n.height) / 2 + 28;
    });

    // forceX pinned per-node to its rank column. forceY has a mild pull
    // to center so the graph doesn't drift vertically.
    const flowX = forceX<SimNode>((n) => n.targetX).strength(0.18);
    const centerY = forceY<SimNode>(0).strength(0.04);

    // Custom label-repel force: every edge midpoint pushes non-adjacent
    // nodes outward so the kind pill between two neighbors has room.
    const labelRepel = (alpha: number) => {
      for (const link of simLinks) {
        const s = link.source as SimNode | string;
        const t = link.target as SimNode | string;
        if (typeof s === "string" || typeof t === "string") continue;
        const sx = s.x ?? 0;
        const sy = s.y ?? 0;
        const tx = t.x ?? 0;
        const ty = t.y ?? 0;
        const lx = (sx + tx) / 2;
        const ly = (sy + ty) / 2;
        for (const n of simNodes) {
          if (n.id === s.id || n.id === t.id) continue;
          const dx = (n.x ?? 0) - lx;
          const dy = (n.y ?? 0) - ly;
          const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
          const minR = n.width / 2 + LABEL_CLEARANCE;
          if (dist < minR) {
            const push = ((minR - dist) / dist) * alpha * 1.4;
            n.vx = (n.vx ?? 0) + dx * push;
            n.vy = (n.vy ?? 0) + dy * push;
          }
        }
      }
    };

    // Label-vs-label repulsion: when two edge midpoints would draw
    // their kind pills on top of each other, nudge their endpoint
    // nodes apart so the labels separate. Edges that share an
    // endpoint are skipped (they'll inevitably be close).
    const labelLabelRepel = (alpha: number) => {
      const mids: { lx: number; ly: number; s: SimNode; t: SimNode }[] = [];
      for (const link of simLinks) {
        const s = link.source as SimNode | string;
        const t = link.target as SimNode | string;
        if (typeof s === "string" || typeof t === "string") continue;
        mids.push({
          lx: ((s.x ?? 0) + (t.x ?? 0)) / 2,
          ly: ((s.y ?? 0) + (t.y ?? 0)) / 2,
          s,
          t,
        });
      }
      const minR = LABEL_LABEL_CLEARANCE;
      for (let i = 0; i < mids.length; i++) {
        for (let j = i + 1; j < mids.length; j++) {
          const a = mids[i];
          const b = mids[j];
          if (a.s === b.s || a.s === b.t || a.t === b.s || a.t === b.t)
            continue;
          const dx = a.lx - b.lx;
          const dy = a.ly - b.ly;
          const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
          if (dist < minR) {
            const push = ((minR - dist) / dist) * alpha * 1.2;
            const fx = dx * push * 0.5;
            const fy = dy * push * 0.5;
            a.s.vx = (a.s.vx ?? 0) + fx;
            a.s.vy = (a.s.vy ?? 0) + fy;
            a.t.vx = (a.t.vx ?? 0) + fx;
            a.t.vy = (a.t.vy ?? 0) + fy;
            b.s.vx = (b.s.vx ?? 0) - fx;
            b.s.vy = (b.s.vy ?? 0) - fy;
            b.t.vx = (b.t.vx ?? 0) - fx;
            b.t.vy = (b.t.vy ?? 0) - fy;
          }
        }
      }
    };

    // Snowflake clustering: pull each child toward its parent's current
    // Y so children orbit near the parent instead of drifting off.
    const parentMap = new Map(simNodes.map((n) => [n.id, n]));
    const snowflake = (alpha: number) => {
      for (const n of simNodes) {
        if (n.tier !== "child" || !n.parentId) continue;
        const parent = parentMap.get(n.parentId);
        if (!parent) continue;
        const dx = (parent.x ?? 0) - (n.x ?? 0);
        const dy = (parent.y ?? 0) - (n.y ?? 0);
        // Horizontal pull is gentle (rank already owns X), vertical pull
        // stronger so children hug the parent's row.
        n.vx = (n.vx ?? 0) + dx * alpha * 0.08;
        n.vy = (n.vy ?? 0) + dy * alpha * 0.18;
      }
    };

    const sim = forceSimulation<SimNode, SimLink>(simNodes)
      .force("charge", charge)
      .force("link", link)
      .force("collide", collide)
      .force("flowX", flowX)
      .force("centerY", centerY)
      .force("labelRepel", labelRepel)
      .force("labelLabelRepel", labelLabelRepel)
      .force("snowflake", snowflake)
      .alpha(1)
      .alphaDecay(0.012)
      .alphaMin(0.02)
      .velocityDecay(0.35);

    sim.on("tick", () => {
      const current = getNodes();
      const byId = new Map(current.map((n) => [n.id, n]));
      const next: Node[] = [];
      for (const sn of simNodes) {
        const prev = byId.get(sn.id);
        if (!prev) continue;
        if (prev.dragging) {
          sn.fx = prev.position.x + (prev.width ?? sn.width) / 2;
          sn.fy = prev.position.y + (prev.height ?? sn.height) / 2;
          next.push(prev);
          continue;
        }
        if (sn.fx != null || sn.fy != null) {
          sn.fx = null;
          sn.fy = null;
        }
        const x = sn.x ?? 0;
        const y = sn.y ?? 0;
        next.push({
          ...prev,
          position: {
            x: x - sn.width / 2,
            y: y - sn.height / 2,
          },
        });
      }
      setNodes(next);
    });

    simRef.current = sim;

    // Seed React Flow with starting positions so edge rendering can
    // look up bounding boxes on the first paint.
    const initialNodes: Node<NodeCardData>[] = contract.nodes.map((n) => {
      const sn = simNodes.find((s) => s.id === n.id)!;
      return {
        id: n.id,
        type: "oval",
        data: { node: n, tier: sn.tier },
        position: { x: (sn.x ?? 0) - sn.width / 2, y: (sn.y ?? 0) - sn.height / 2 },
        width: sn.width,
        height: sn.height,
        draggable: true,
      };
    });
    const initialEdges: Edge<EdgeData>[] = contract.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: "floating",
      data: { edge: e },
    }));
    setNodes(initialNodes);
    setEdges(initialEdges);

    return () => {
      sim.on("tick", null);
      sim.stop();
      simRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contract, hierarchy]);
}
