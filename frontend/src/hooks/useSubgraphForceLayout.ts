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
import type { ImplementationSubgraph, SubgraphNode } from "../types/subgraph";
import type { SubgraphNodeCardData } from "../components/SubgraphNodeCard";

interface SimNode extends SimulationNodeDatum {
  id: string;
  width: number;
  height: number;
}

type SimLink = SimulationLinkDatum<SimNode> & { id: string };

const NODE_WIDTH = 200;
const NODE_HEIGHT = 60;
const CHARGE_STRENGTH = -400;
const LINK_DISTANCE = 120;
const COLLISION_PADDING = 20;

/**
 * Runs a d3-force simulation over the subgraph's nodes/edges and pushes
 * updated positions into React Flow on every tick. Similar to the main
 * graph's force layout but with simpler semantics:
 *  - All nodes have the same charge
 *  - Gentle center gravity keeps the graph from drifting
 *  - Nodes are draggable and simulation reacts in real-time
 */
export function useSubgraphForceLayout(
  subgraph: ImplementationSubgraph | null,
  parentNodeId: string,
  onSelect: (subgraphNodeId: string) => void,
) {
  const { setNodes, setEdges, getNodes } = useReactFlow();
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);

  useEffect(() => {
    if (!subgraph) return;

    const simNodes: SimNode[] = subgraph.nodes.map((n, i) => {
      const angle = (i / Math.max(subgraph.nodes.length, 1)) * Math.PI * 2;
      const radius = 150;
      return {
        id: n.id,
        x: Math.cos(angle) * radius + (Math.random() - 0.5) * 40,
        y: Math.sin(angle) * radius + (Math.random() - 0.5) * 40,
        vx: 0,
        vy: 0,
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
      };
    });

    const simLinks: SimLink[] = subgraph.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
    }));

    const charge = forceManyBody<SimNode>().strength(CHARGE_STRENGTH);
    
    const link = forceLink<SimNode, SimLink>(simLinks)
      .id((d) => d.id)
      .distance(LINK_DISTANCE)
      .strength(0.5);
    
    const collide = forceCollide<SimNode>((n) => {
      return Math.max(n.width, n.height) / 2 + COLLISION_PADDING;
    });

    const centerX = forceX<SimNode>(0).strength(0.05);
    const centerY = forceY<SimNode>(0).strength(0.05);

    const sim = forceSimulation<SimNode, SimLink>(simNodes)
      .force("charge", charge)
      .force("link", link)
      .force("collide", collide)
      .force("centerX", centerX)
      .force("centerY", centerY)
      .alpha(1)
      .alphaDecay(0.015)
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

    const initialNodes: Node<SubgraphNodeCardData>[] = subgraph.nodes.map(
      (node: SubgraphNode) => {
        const sn = simNodes.find((s) => s.id === node.id)!;
        return {
          id: node.id,
          type: "sg",
          data: {
            node,
            parentNodeId,
            onSelect,
          },
          position: {
            x: (sn.x ?? 0) - sn.width / 2,
            y: (sn.y ?? 0) - sn.height / 2,
          },
          width: sn.width,
          height: sn.height,
          draggable: true,
        };
      },
    );

    const initialEdges: Edge[] = subgraph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.label ?? undefined,
      style: { stroke: "#475569", strokeWidth: 1.5 },
      animated: false,
    }));

    setNodes(initialNodes);
    setEdges(initialEdges);

    return () => {
      sim.on("tick", null);
      sim.stop();
      simRef.current = null;
    };
  }, [subgraph, parentNodeId, onSelect, setNodes, setEdges, getNodes]);

  useEffect(() => {
    if (!subgraph || !simRef.current) return;

    const sim = simRef.current;
    const currentNodes = getNodes();
    
    for (const node of currentNodes) {
      const subgraphNode = subgraph.nodes.find((n) => n.id === node.id);
      if (subgraphNode && node.data?.node?.status !== subgraphNode.status) {
        setNodes((nodes) =>
          nodes.map((n) =>
            n.id === node.id
              ? { ...n, data: { ...n.data, node: subgraphNode } }
              : n,
          ),
        );
      }
    }
  }, [subgraph, getNodes, setNodes]);
}
