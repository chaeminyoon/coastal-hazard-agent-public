import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  boundsGeometry,
  buildSelectionGeometry,
  displaySharedFeatureTooltip,
  OperationResultCard,
  scenarioWorkspaceState,
  selectionPositions,
  watchMapResize,
} from "./SpatialStudio";
import { upsertTemporaryLayer } from "./spatial-layers";

afterEach(cleanup);

describe("spatial operation result card", () => {
  it("closes the latest spatial operation popup", () => {
    render(createElement(OperationResultCard, {
      operation: {
        operation_id: "scope-1",
        operation: "query_scope",
        name: "질문에 사용된 데이터 조회 범위",
        summary: "421개 격자를 조회했습니다.",
      } as never,
      saved: false,
      reportSelected: false,
      onKeep: () => undefined,
      onToggleReport: () => undefined,
    }));

    expect(screen.getByText("질문에 사용된 데이터 조회 범위")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "조회 결과 팝업 닫기" }));
    expect(screen.queryByText("질문에 사용된 데이터 조회 범위")).not.toBeInTheDocument();
  });
});


describe("spatial map resizing", () => {
  it("invalidates Leaflet when its container changes size", () => {
    const container = document.createElement("div");
    const invalidateSize = vi.fn();
    let resizeCallback: ResizeObserverCallback | null = null;
    const observe = vi.fn();
    const disconnect = vi.fn();
    class TestResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        resizeCallback = callback;
      }
      observe = observe;
      unobserve = vi.fn();
      disconnect = disconnect;
    }

    const cleanup = watchMapResize(
      { getContainer: () => container, invalidateSize },
      TestResizeObserver as unknown as typeof ResizeObserver,
    );

    expect(observe).toHaveBeenCalledWith(container);
    expect(invalidateSize).toHaveBeenCalledTimes(1);
    expect(resizeCallback).not.toBeNull();
    (resizeCallback as unknown as ResizeObserverCallback)([], {} as ResizeObserver);
    expect(invalidateSize).toHaveBeenCalledTimes(2);
    cleanup();
    expect(disconnect).toHaveBeenCalledOnce();
  });
});

describe("spatial feature tooltips", () => {
  it("reuses one tooltip overlay and suppresses it while dragging", () => {
    const overlay = {
      remove: vi.fn(),
      setContent: vi.fn(),
      setLatLng: vi.fn(),
      addTo: vi.fn(),
    };
    overlay.setContent.mockReturnValue(overlay);
    overlay.setLatLng.mockReturnValue(overlay);

    displaySharedFeatureTooltip(overlay as never, {} as never, "가덕도동 · 위해성 5등급", [35, 129] as never, false);
    displaySharedFeatureTooltip(overlay as never, {} as never, "다대동 · 위해성 4등급", [35.1, 129.1] as never, true);

    expect(overlay.remove).toHaveBeenCalledTimes(2);
    expect(overlay.setContent).toHaveBeenCalledOnce();
    expect(overlay.setLatLng).toHaveBeenCalledOnce();
    expect(overlay.addTo).toHaveBeenCalledOnce();
  });
});

describe("custom area drawing", () => {
  it("serializes the current map bounds for partial-image export", () => {
    expect(boundsGeometry({ south: 35.1, west: 129.1, north: 35.2, east: 129.3 })).toEqual({
      type: "Polygon",
      coordinates: [[[129.1, 35.1], [129.3, 35.1], [129.3, 35.2], [129.1, 35.2], [129.1, 35.1]]],
    });
  });

  it("closes clicked map points as a GeoJSON polygon", () => {
    const geometry = buildSelectionGeometry([
      [35.10, 129.10],
      [35.10, 129.20],
      [35.20, 129.20],
    ]);

    expect(geometry).toEqual({
      type: "Polygon",
      coordinates: [[
        [129.10, 35.10],
        [129.20, 35.10],
        [129.20, 35.20],
        [129.10, 35.10],
      ]],
    });
  });

  it("restores saved scenario geometry as Leaflet positions", () => {
    expect(selectionPositions({
      type: "Polygon",
      coordinates: [[[129.10, 35.10], [129.20, 35.10], [129.10, 35.10]]],
    })).toEqual([[35.10, 129.10], [35.10, 129.20]]);
  });
});

describe("temporary spatial layers", () => {
  it("keeps prior layers and replaces a layer with the same operation id", () => {
    const first = { operation_id: "one", name: "첫 레이어" } as never;
    const updated = { operation_id: "one", name: "수정 레이어" } as never;
    const second = { operation_id: "two", name: "둘째 레이어" } as never;

    expect(upsertTemporaryLayer(upsertTemporaryLayer([first], second), updated))
      .toEqual([second, updated]);
  });

  it("restores the saved region together with metric, grades and geometry", () => {
    expect(scenarioWorkspaceState({
      region: "제주특별자치도 제주시",
      metric: "overall",
      grades: ["4", "5"],
      geometry: {
        type: "Polygon",
        coordinates: [[[126.5, 33.5], [126.6, 33.5], [126.5, 33.5]]],
      },
    } as never)).toEqual({
      region: "제주특별자치도 제주시",
      metric: "overall",
      grades: ["4", "5"],
      points: [[33.5, 126.5], [33.5, 126.6]],
    });
  });
});

describe("boxSelectionPoints", () => {
  it("builds four corner points regardless of drag direction", async () => {
    const { boxSelectionPoints } = await import("./SpatialStudio");
    expect(boxSelectionPoints([35.2, 129.2], [35.1, 129.1])).toEqual([
      [35.1, 129.1],
      [35.1, 129.2],
      [35.2, 129.2],
      [35.2, 129.1],
    ]);
  });
});
