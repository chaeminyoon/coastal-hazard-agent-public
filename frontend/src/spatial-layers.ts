import type { SpatialOperationResult } from "./api";

export function upsertTemporaryLayer(
  layers: SpatialOperationResult[],
  layer: SpatialOperationResult,
) {
  return [...layers.filter((item) => item.operation_id !== layer.operation_id), layer];
}

export function spatialStateFromOperation(operation: SpatialOperationResult) {
  const primary = operation.conditions[0];
  return {
    region: operation.region,
    context: operation.name,
    metric: primary?.metric_id || "overall",
    grades: primary?.grades || [],
    focusNames: [],
  };
}
