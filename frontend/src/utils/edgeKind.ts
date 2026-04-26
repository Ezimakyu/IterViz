import type { ContractEdge, PayloadSchema } from "../types/contract";

export const EDGE_KIND_COLOR: Record<ContractEdge["kind"], string> = {
  data: "#60a5fa",
  control: "#f59e0b",
  event: "#a78bfa",
  dependency: "#94a3b8",
};

export function payloadSummary(
  schema: PayloadSchema | null | undefined,
): string {
  if (!schema || !schema.properties) return "no payload";
  const fieldCount = Object.keys(schema.properties).length;
  return `${schema.type ?? "object"} with ${fieldCount} field${
    fieldCount === 1 ? "" : "s"
  }`;
}
