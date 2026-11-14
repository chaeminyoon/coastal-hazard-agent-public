import { describe, expect, it } from "vitest";

import { spatialStateFromOperation } from "./spatial-layers";


describe("spatial operation state", () => {
  it("applies the operation region, metric and grades when a result opens on the map", () => {
    const state = spatialStateFromOperation({
      operation_id: "filter-1",
      operation: "filter",
      name: "종합 위험 4·5등급",
      region: "부산광역시 수영구",
      conditions: [{
        metric_id: "overall",
        label: "종합 위험",
        grade_column: "위험성지수_등급",
        grades: ["4", "5"],
      }],
      stats: { feature_count: 56 },
      summary: "56개 격자",
      feature_collection: { type: "FeatureCollection", features: [], metadata: { count: 56, truncated: false } },
      evidence: { source: "GPKG", queries: [] },
      report_material: { question: "필터", answer: "56개", region: "부산광역시 수영구", grounded: true, queries: [], results: [] },
    });

    expect(state).toEqual({
      region: "부산광역시 수영구",
      context: "종합 위험 4·5등급",
      metric: "overall",
      grades: ["4", "5"],
      focusNames: [],
    });
  });
});
