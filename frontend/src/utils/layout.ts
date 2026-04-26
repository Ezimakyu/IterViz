import dagre from "dagre";
import type { Edge, Node } from "reactflow";

export const NODE_WIDTH = 280;
export const NODE_HEIGHT = 160;

export interface LayoutOptions {
  rankdir?: "TB" | "LR" | "BT" | "RL";
  nodesep?: number;
  ranksep?: number;
}

/**
 * Lay out React Flow nodes/edges using dagre. Mutates copies, does not
 * touch the inputs. Returns nodes positioned so dagre's center-based
 * coordinates align with React Flow's top-left positioning.
 */
export function layoutGraph(
  nodes: Node[],
  edges: Edge[],
  opts: LayoutOptions = {},
): { nodes: Node[]; edges: Edge[] } {
  const { rankdir = "TB", nodesep = 80, ranksep = 100 } = opts;

  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir, nodesep, ranksep, marginx: 24, marginy: 24 });

  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  const positionedNodes: Node[] = nodes.map((node) => {
    const { x, y } = g.node(node.id);
    return {
      ...node,
      position: { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 },
      // React Flow uses these to know node dimensions for edge routing.
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
    };
  });

  return { nodes: positionedNodes, edges };
}
