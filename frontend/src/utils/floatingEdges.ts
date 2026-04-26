import { Position, type Node } from "reactflow";
import { NODE_HEIGHT, NODE_WIDTH } from "./layout";

export interface Point {
  x: number;
  y: number;
}

function nodeCenter(node: Node): Point {
  const w = node.width ?? NODE_WIDTH;
  const h = node.height ?? NODE_HEIGHT;
  const pos = node.positionAbsolute ?? node.position;
  return { x: pos.x + w / 2, y: pos.y + h / 2 };
}

/**
 * Intersection of the ray from `source` center to `target` center with
 * the axis-aligned bounding box of `source`. Good enough for pill-shaped
 * nodes where the rounded ends are short relative to node width.
 */
export function getNodeIntersection(source: Node, target: Node): Point {
  const w = (source.width ?? NODE_WIDTH) / 2;
  const h = (source.height ?? NODE_HEIGHT) / 2;
  const sc = nodeCenter(source);
  const tc = nodeCenter(target);
  const dx = tc.x - sc.x;
  const dy = tc.y - sc.y;
  if (dx === 0 && dy === 0) return sc;
  const sx = dx === 0 ? Infinity : w / Math.abs(dx);
  const sy = dy === 0 ? Infinity : h / Math.abs(dy);
  const s = Math.min(sx, sy);
  return { x: sc.x + dx * s, y: sc.y + dy * s };
}

/**
 * Classify which side of `source`'s bounding box the edge leaves from.
 * Used purely for rendering cosmetics (marker rotation, handle choice);
 * path points themselves come from `getNodeIntersection`.
 */
export function getEdgeSide(source: Node, intersection: Point): Position {
  const w = source.width ?? NODE_WIDTH;
  const h = source.height ?? NODE_HEIGHT;
  const pos = source.positionAbsolute ?? source.position;
  const dx = intersection.x - (pos.x + w / 2);
  const dy = intersection.y - (pos.y + h / 2);
  if (Math.abs(dx) * h >= Math.abs(dy) * w) {
    return dx > 0 ? Position.Right : Position.Left;
  }
  return dy > 0 ? Position.Bottom : Position.Top;
}

export function getEdgeParams(source: Node, target: Node) {
  const sourceIntersect = getNodeIntersection(source, target);
  const targetIntersect = getNodeIntersection(target, source);
  return {
    sx: sourceIntersect.x,
    sy: sourceIntersect.y,
    tx: targetIntersect.x,
    ty: targetIntersect.y,
    sourcePos: getEdgeSide(source, sourceIntersect),
    targetPos: getEdgeSide(target, targetIntersect),
  };
}
