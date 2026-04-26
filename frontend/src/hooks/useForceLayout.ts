import { useEffect, useRef } from "react";
import {
  forceCenter,
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
import { useReactFlow, type Node } from "reactflow";
import type { Contract } from "../types/contract";
import { NODE_HEIGHT, NODE_WIDTH } from "../utils/layout";

interface SimNode extends SimulationNodeDatum {
  id: string;
}

type SimLink = SimulationLinkDatum<SimNode> & { id: string };

const BASE_CHARGE = -900;
const BOOST_CHARGE = -2400;
const COLLISION_RADIUS = Math.max(NODE_WIDTH, NODE_HEIGHT) / 2 + 24;
const LINK_DISTANCE = 220;

interface Options {
  boostedId: string | null;
}

/**
 * Runs a d3-force simulation over the contract's nodes/edges and pushes
 * updated positions into React Flow on every tick. The simulation never
 * fully cools, so nodes gently jiggle (Obsidian-style) and react to
 * dragging and selection in real time.
 */
export function useForceLayout(contract: Contract | null, opts: Options) {
  const { setNodes, getNodes } = useReactFlow();
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const boostedRef = useRef<string | null>(null);

  // Keep the charge force aware of which node should repel harder.
  useEffect(() => {
    boostedRef.current = opts.boostedId;
    const sim = simRef.current;
    if (sim) {
      sim.alpha(Math.max(sim.alpha(), 0.6)).restart();
    }
  }, [opts.boostedId]);

  // (Re)build the simulation whenever the contract changes.
  useEffect(() => {
    if (!contract) return;

    const count = contract.nodes.length;
    const simNodes: SimNode[] = contract.nodes.map((n, i) => {
      const angle = (i / Math.max(count, 1)) * Math.PI * 2;
      const r = 180 + (count > 6 ? 80 : 0);
      return {
        id: n.id,
        x: Math.cos(angle) * r,
        y: Math.sin(angle) * r,
        vx: 0,
        vy: 0,
      };
    });
    const simLinks: SimLink[] = contract.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
    }));

    const charge = forceManyBody<SimNode>().strength((n) =>
      n.id === boostedRef.current ? BOOST_CHARGE : BASE_CHARGE,
    );
    const link = forceLink<SimNode, SimLink>(simLinks)
      .id((d) => d.id)
      .distance(LINK_DISTANCE)
      .strength(0.35);
    const collide = forceCollide<SimNode>(COLLISION_RADIUS);

    const sim = forceSimulation<SimNode, SimLink>(simNodes)
      .force("charge", charge)
      .force("link", link)
      .force("collide", collide)
      .force("center", forceCenter(0, 0))
      .force("x", forceX(0).strength(0.03))
      .force("y", forceY(0).strength(0.03))
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
          // Pin the sim to follow the user's pointer while dragging.
          sn.fx = prev.position.x + (prev.width ?? NODE_WIDTH) / 2;
          sn.fy = prev.position.y + (prev.height ?? NODE_HEIGHT) / 2;
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
            x: x - (prev.width ?? NODE_WIDTH) / 2,
            y: y - (prev.height ?? NODE_HEIGHT) / 2,
          },
        });
      }
      setNodes(next);
    });

    simRef.current = sim;

    // Seed React Flow with the initial positions immediately so edges
    // can look up node positions on the first render.
    const initialNodes: Node[] = contract.nodes.map((n, i) => {
      const sn = simNodes[i];
      const x = sn.x ?? 0;
      const y = sn.y ?? 0;
      return {
        id: n.id,
        type: "oval",
        data: n,
        position: { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 },
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        draggable: true,
      };
    });
    setNodes(initialNodes);

    return () => {
      sim.on("tick", null);
      sim.stop();
      simRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contract]);
}
