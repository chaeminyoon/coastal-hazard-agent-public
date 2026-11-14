import { ChangeEvent, CSSProperties, MouseEvent as ReactMouseEvent, useEffect, useMemo, useRef, useState } from "react";
import type { Feature, FeatureCollection, GeoJsonObject, Polygon as GeoJSONPolygon } from "geojson";
import {
  geoJSON,
  tooltip as createTooltip,
  type LatLngExpression,
  type Map as LeafletMap,
  type Tooltip as LeafletTooltip,
} from "leaflet";
import {
  BarChart3,
  BookMarked,
  BookmarkPlus,
  Check,
  ChevronDown,
  CircleAlert,
  Database,
  Download,
  Image,
  Layers3,
  MessageSquareText,
  MousePointer2,
  PanelBottom,
  SlidersHorizontal,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { displayRegionName } from "./conversation";
import { CircleMarker, GeoJSON, MapContainer, Polygon, Polyline, TileLayer, useMap, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";

import {
  api,
  McpAnalysisResult,
  ReportMaterial,
  SpatialAnnotationLayer,
  SpatialFeatureCollection,
  SpatialGradeMetric,
  SpatialLayer,
  SpatialMapExport,
  SpatialOperationResult,
  SpatialScenario,
  SpatialSelectionAnalysis,
  SpatialSelectionComparison,
} from "./api";
import { downloadInBrowser } from "./download";
import { GRADE_COLORS } from "./theme";

const PROPERTY_LABELS: Record<string, string> = {
  FTR_IDN: "격자 ID",
  SD_NM: "시·도",
  SGG_NM: "시·군·구",
  ADM_NM: "읍·면·동",
  "위해성지수_등급": "위해성",
  "노출성지수_등급": "노출성",
  "취약성지수(가중)_등급": "취약성",
  "취약성지수(저감)_등급": "저감능력",
  "위험성지수_등급": "종합 위험",
};

const DEFAULT_METRIC: SpatialGradeMetric = {
  id: "overall",
  label: "종합 위험",
  group: "종합",
  grade_column: "위험성지수_등급",
  grade_counts: {},
};

const ATTRIBUTE_TABLE_MIN_HEIGHT = 100;

export function attributeTableMaxHeight(viewportHeight: number) {
  if (!Number.isFinite(viewportHeight)) return 640;
  return Math.min(640, Math.max(240, Math.floor(viewportHeight - 420)));
}

function clampAttributeTableHeight(height: number, viewportHeight: number) {
  return Math.min(
    attributeTableMaxHeight(viewportHeight),
    Math.max(ATTRIBUTE_TABLE_MIN_HEIGHT, height),
  );
}

type Properties = Record<string, string | number | null>;

type ResizeAwareMap = {
  getContainer: () => HTMLElement;
  invalidateSize: (options?: { animate?: boolean }) => unknown;
};

type SharedFeatureTooltip = Pick<LeafletTooltip, "remove" | "setContent" | "setLatLng" | "addTo">;

export function displaySharedFeatureTooltip(
  overlay: SharedFeatureTooltip,
  map: LeafletMap,
  content: string,
  latlng: LatLngExpression,
  dragging: boolean,
) {
  overlay.remove();
  if (dragging) return;
  overlay.setContent(content).setLatLng(latlng).addTo(map);
}

export function watchMapResize(
  map: ResizeAwareMap,
  Observer: typeof ResizeObserver,
) {
  const invalidate = () => map.invalidateSize({ animate: false });
  const observer = new Observer(invalidate);
  observer.observe(map.getContainer());
  invalidate();
  return () => observer.disconnect();
}

type SelectionPoint = [number, number];
type ExportBackground = "satellite" | "composite" | "transparent";
type ExportExtent = "region" | "viewport" | "selection";

export function OperationResultCard({
  operation,
  saved,
  reportSelected,
  onKeep,
  onToggleReport,
}: {
  operation: SpatialOperationResult;
  saved: boolean;
  reportSelected: boolean;
  onKeep: () => void;
  onToggleReport: () => void;
}) {
  const [open, setOpen] = useState(true);
  if (!open) return null;
  return <div className="operation-result-card" role="status">
    <div>
      <span>{operation.operation === "query_scope" ? "SQL 조회 범위" : "공간 연산 결과"}</span>
      <button
        type="button"
        className="operation-result-dismiss"
        aria-label="조회 결과 팝업 닫기"
        onClick={() => setOpen(false)}
      ><X size={14} /></button>
    </div>
    <strong>{operation.name}</strong>
    <p>{operation.summary}</p>
    <div>
      <button disabled={saved} onClick={onKeep}>
        <BookmarkPlus size={12} /> {saved ? "임시 레이어 보관됨" : "임시 레이어 보관"}
      </button>
      <button className={reportSelected ? "selected" : ""} onClick={onToggleReport}>
        <BookMarked size={12} /> {reportSelected ? "보고서에 담김" : "보고서에 추가"}
      </button>
    </div>
  </div>;
}

export function buildSelectionGeometry(points: SelectionPoint[]): GeoJSONPolygon {
  if (points.length < 3) throw new Error("영역을 만들려면 지도에 점을 3개 이상 지정해 주세요.");
  const coordinates = points.map(([lat, lng]) => [lng, lat]);
  return { type: "Polygon", coordinates: [[...coordinates, coordinates[0]]] };
}

export function selectionPositions(geometry: GeoJSONPolygon): SelectionPoint[] {
  const ring = geometry.coordinates[0] || [];
  const points = ring.map(([lng, lat]) => [lat, lng] as SelectionPoint);
  if (points.length > 1) {
    const first = points[0];
    const last = points[points.length - 1];
    if (first[0] === last[0] && first[1] === last[1]) points.pop();
  }
  return points;
}

export function scenarioWorkspaceState(
  scenario: Pick<SpatialScenario, "region" | "metric" | "grades" | "geometry">,
) {
  return {
    region: scenario.region,
    metric: scenario.metric,
    grades: scenario.grades,
    points: selectionPositions(scenario.geometry),
  };
}

export function boxSelectionPoints(start: SelectionPoint, end: SelectionPoint): SelectionPoint[] {
  const south = Math.min(start[0], end[0]);
  const north = Math.max(start[0], end[0]);
  const west = Math.min(start[1], end[1]);
  const east = Math.max(start[1], end[1]);
  return [[south, west], [south, east], [north, east], [north, west]];
}

export function boundsGeometry(bounds: { south: number; west: number; north: number; east: number }): GeoJSONPolygon {
  return {
    type: "Polygon",
    coordinates: [[
      [bounds.west, bounds.south], [bounds.east, bounds.south],
      [bounds.east, bounds.north], [bounds.west, bounds.north],
      [bounds.west, bounds.south],
    ]],
  };
}

type Props = {
  region: string | null;
  context: string;
  focusGrades: string[];
  focusNames: string[];
  focusMetric: string;
  reportMaterialIds: string[];
  onClose: () => void;
  onAsk: (question: string) => void;
  onShareSelection: (analysis: SpatialSelectionAnalysis) => void;
  onAddReportMaterial: (material: ReportMaterial) => void;
  onRemoveReportMaterial: (sourceId: string) => void;
  operationLayers: SpatialOperationResult[];
  temporaryLayerIds: string[];
  onKeepOperationLayer: (layer: SpatialOperationResult) => void;
  onRemoveOperationLayer: (operationId: string) => void;
  onSpatialOperation: (operation: SpatialOperationResult) => void;
  onRegionChange: (region: string) => void;
};

function SpatialStudio({
  region,
  context,
  focusGrades,
  focusNames,
  focusMetric,
  reportMaterialIds,
  onClose,
  onAsk,
  onShareSelection,
  onAddReportMaterial,
  onRemoveReportMaterial,
  operationLayers,
  temporaryLayerIds,
  onKeepOperationLayer,
  onRemoveOperationLayer,
  onSpatialOperation,
  onRegionChange,
}: Props) {
  const [layer, setLayer] = useState<SpatialLayer | null>(null);
  const [collection, setCollection] = useState<SpatialFeatureCollection | null>(null);
  const [grades, setGrades] = useState<string[]>(focusGrades);
  const [metricId, setMetricId] = useState(focusMetric);
  const [visible, setVisible] = useState(true);
  const [opacity, setOpacity] = useState(68);
  const [selected, setSelected] = useState<Properties | null>(null);
  const [tableOpen, setTableOpen] = useState(true);
  const [tableHeight, setTableHeight] = useState(155);
  const [layerCollapsed, setLayerCollapsed] = useState(false);
  const [layerWidth, setLayerWidth] = useState(260);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState<SpatialMapExport | null>(null);
  const [exportError, setExportError] = useState("");
  const [baseMap, setBaseMap] = useState<"street" | "satellite">("street");
  const [annotation, setAnnotation] = useState<SpatialAnnotationLayer | null>(null);
  const [annotationVisible, setAnnotationVisible] = useState(true);
  const [annotationField, setAnnotationField] = useState("");
  const [annotationLoading, setAnnotationLoading] = useState(false);
  const [annotationError, setAnnotationError] = useState("");
  const [drawing, setDrawing] = useState(false);
  const [boxSelecting, setBoxSelecting] = useState(false);
  const [selectionMcpLoading, setSelectionMcpLoading] = useState(false);
  const [selectionMcpError, setSelectionMcpError] = useState("");
  const [boxDrag, setBoxDrag] = useState<{ start: SelectionPoint; end: SelectionPoint } | null>(null);
  const [drawCursor, setDrawCursor] = useState<SelectionPoint | null>(null);
  const [selectionPoints, setSelectionPoints] = useState<SelectionPoint[]>([]);
  const [selection, setSelection] = useState<SpatialSelectionAnalysis | null>(null);
  const [comparisonBase, setComparisonBase] = useState<SpatialSelectionAnalysis | null>(null);
  const [selectionComparison, setSelectionComparison] = useState<SpatialSelectionComparison | null>(null);
  const [selectionLoading, setSelectionLoading] = useState(false);
  const [selectionError, setSelectionError] = useState("");
  const [scenarios, setScenarios] = useState<SpatialScenario[]>([]);
  const [scenariosOpen, setScenariosOpen] = useState(false);
  const [scenarioName, setScenarioName] = useState("");
  const [scenarioLoading, setScenarioLoading] = useState(false);
  const [viewportGeometry, setViewportGeometry] = useState<GeoJSONPolygon | null>(null);
  const [exportOptionsOpen, setExportOptionsOpen] = useState(false);
  const [exportBackground, setExportBackground] = useState<ExportBackground>("composite");
  const [exportExtent, setExportExtent] = useState<ExportExtent>("region");
  const [sharingSelection, setSharingSelection] = useState(false);
  const [hiddenOperationIds, setHiddenOperationIds] = useState<string[]>([]);
  const [operationLoading, setOperationLoading] = useState(false);
  const sharedFeatureTooltip = useRef<LeafletTooltip | null>(null);

  useEffect(() => () => {
    sharedFeatureTooltip.current?.remove();
  }, []);

  function startAttributeTableResize(event: ReactMouseEvent<HTMLDivElement>) {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = tableHeight;
    const onMove = (moveEvent: globalThis.MouseEvent) => {
      setTableHeight(clampAttributeTableHeight(
        startHeight + startY - moveEvent.clientY,
        window.innerHeight,
      ));
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  useEffect(() => setGrades(focusGrades), [focusGrades]);
  useEffect(() => setMetricId(focusMetric), [focusMetric]);

  useEffect(() => {
    api.spatialScenarios().then(setScenarios).catch(() => undefined);
  }, []);

  useEffect(() => {
    setExported(null);
    setExportError("");
  }, [region, metricId, grades, focusNames]);

  useEffect(() => {
    if (!region) return;
    api.spatialLayer(region)
      .then(setLayer)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "레이어 정보를 조회하지 못했습니다."));
  }, [region]);

  useEffect(() => {
    if (!region) return;
    let active = true;
    setLoading(true);
    setCollection(null);
    setError("");
    setSelected(null);
    api.spatialFeatures(region, grades, focusNames, metricId)
      .then((result) => {
        if (active) setCollection(result);
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : "공간자료 조회에 실패했습니다.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [region, grades, focusNames, metricId]);

  const features = collection?.features || [];
  const metric = layer?.metrics?.find((item) => item.id === metricId) || DEFAULT_METRIC;
  const metricGroups = useMemo(() => {
    const groups = new Map<string, SpatialGradeMetric[]>();
    (layer?.metrics || [DEFAULT_METRIC]).forEach((item) => {
      const items = groups.get(item.group) || [];
      items.push(item);
      groups.set(item.group, items);
    });
    return [...groups.entries()];
  }, [layer]);
  const selectedId = String(selected?.FTR_IDN || "");
  const mapKey = `${region}-${metricId}-${grades.join("-")}-${focusNames.join("-")}-${opacity}-${selectedId}`;
  const rows = features.slice(0, 80);
  const materialKey = `spatial:${region || "national"}:${metricId}:${grades.join("-")}:${focusNames.join("-")}`;
  const materialSelected = reportMaterialIds.includes(materialKey);
  const activeCount = focusNames.length
    ? collection?.metadata.count || features.length
    : grades.length
      ? grades.reduce((total, grade) => total + (metric.grade_counts[grade] || 0), 0)
      : layer?.feature_count || 0;

  const toggleGrade = (grade: string) => {
    setGrades((current) => current.includes(grade)
      ? current.filter((item) => item !== grade)
      : [...current, grade].sort());
  };

  const resetSelection = () => {
    setDrawing(false);
    setBoxSelecting(false);
    setBoxDrag(null);
    setSelectionPoints([]);
    setSelection(null);
    setComparisonBase(null);
    setSelectionComparison(null);
    setSelectionError("");
    setSelectionMcpError("");
  };

  const analyzeArea = async (geometry?: GeoJSONPolygon) => {
    if (!region) return;
    setSelectionLoading(true);
    setSelectionError("");
    try {
      const area = geometry || buildSelectionGeometry(selectionPoints);
      const result = await api.spatialSelection({ region, metric: metricId, grades, geometry: area });
      setSelection(result);
      setSelectionMcpError("");
      // 분석 표는 지도 오버레이가 아니라 대화창 인라인 카드로 보여준다.
      onShareSelection(result);
      setSelectionPoints(selectionPositions(result.geometry));
      setDrawing(false);
    } catch (reason) {
      setSelectionError(reason instanceof Error ? reason.message : "선택 영역 분석에 실패했습니다.");
    } finally {
      setSelectionLoading(false);
    }
  };

  const runSelectionMcp = async () => {
    if (!selection || !region || selectionMcpLoading) return;
    setSelectionMcpLoading(true);
    setSelectionMcpError("");
    try {
      const analysis = await api.mcpAnalyze({
        question: `${region} 선택 영역 격자 시각화`,
        region,
        columns: ["항목", "값"],
        rows: [
          ["교차 격자", selection.stats.selected_count],
          ["4·5등급 격자", selection.stats.high_risk_count],
        ],
        selection: {
          id: selection.selection_id,
          metric: selection.metric.id,
          grades: selection.grades || [],
          geometry: selection.geometry,
        },
      });
      onShareSelection({ ...selection, mcp: analysis });
    } catch (reason) {
      setSelectionMcpError(reason instanceof Error ? reason.message : "MCP 시각화에 실패했습니다.");
    } finally {
      setSelectionMcpLoading(false);
    }
  };

  const finishBoxSelection = (start: SelectionPoint, end: SelectionPoint) => {
    setBoxDrag(null);
    setBoxSelecting(false);
    if (start[0] === end[0] && start[1] === end[1]) return;
    const points = boxSelectionPoints(start, end);
    setSelectionPoints(points);
    setSelection(null);
    setSelectionError("");
    void analyzeArea(buildSelectionGeometry(points));
  };

  const saveComparisonBase = () => {
    if (!selection) return;
    setComparisonBase(selection);
    setSelection(null);
    setSelectionPoints([]);
    setSelectionComparison(null);
    setDrawing(true);
  };

  const compareAreas = async () => {
    if (!region || !comparisonBase || !selection) return;
    setSelectionLoading(true);
    setSelectionError("");
    try {
      const compared = await api.compareSpatialSelections({
        region,
        metric: metricId,
        grades,
        geometry_a: comparisonBase.geometry,
        geometry_b: selection.geometry,
      });
      setSelectionComparison(compared);
    } catch (reason) {
      setSelectionError(reason instanceof Error ? reason.message : "A/B 영역 비교에 실패했습니다.");
    } finally {
      setSelectionLoading(false);
    }
  };

  const saveScenario = async () => {
    if (!region) return;
    setScenarioLoading(true);
    setSelectionError("");
    try {
      const saved = await api.saveSpatialScenario({
        name: scenarioName.trim() || `${displayRegionName(region)} 사용자 영역`,
        region,
        metric: metricId,
        grades,
        geometry: buildSelectionGeometry(selectionPoints),
      });
      setScenarios((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
      setScenarioName("");
      setScenariosOpen(true);
    } catch (reason) {
      setSelectionError(reason instanceof Error ? reason.message : "분석 시나리오를 저장하지 못했습니다.");
    } finally {
      setScenarioLoading(false);
    }
  };

  const runScenario = async (scenario: SpatialScenario) => {
    const workspace = scenarioWorkspaceState(scenario);
    setScenarioLoading(true);
    setSelectionError("");
    onRegionChange(workspace.region);
    setMetricId(workspace.metric);
    setGrades(workspace.grades);
    setSelectionPoints(workspace.points);
    try {
      const result = await api.runSpatialScenario(scenario.id);
      setSelection(result);
      setScenarios((current) => current.map((item) => item.id === scenario.id
        ? { ...item, latest_result: result, last_run_at: new Date().toISOString() }
        : item));
    } catch (reason) {
      setSelectionError(reason instanceof Error ? reason.message : "분석 시나리오를 재실행하지 못했습니다.");
    } finally {
      setScenarioLoading(false);
    }
  };

  const deleteScenario = async (scenarioId: string) => {
    setScenarioLoading(true);
    setSelectionError("");
    try {
      await api.deleteSpatialScenario(scenarioId);
      setScenarios((current) => current.filter((item) => item.id !== scenarioId));
    } catch (reason) {
      setSelectionError(reason instanceof Error ? reason.message : "분석 시나리오를 삭제하지 못했습니다.");
    } finally {
      setScenarioLoading(false);
    }
  };

  const selectionMaterialId = selection ? `selection:${selection.selection_id}` : "";
  const selectionMaterialSelected = selectionMaterialId
    ? reportMaterialIds.includes(selectionMaterialId)
    : false;

  const selectionWithImage = async (analysis: SpatialSelectionAnalysis) => {
    const exportedMap = await createMapImage({
      background: "transparent",
      extent: "selection",
      geometry: analysis.geometry,
    });
    return {
      ...analysis,
      report_material: {
        ...analysis.report_material,
        spatial_image: {
          image_id: exportedMap.image_id,
          filename: exportedMap.filename,
          caption: exportedMap.caption,
        },
      },
    };
  };

  const shareSelection = async () => {
    if (!selection) return;
    setSharingSelection(true);
    setExportError("");
    try {
      const enriched = await selectionWithImage(selection);
      setSelection(enriched);
      onShareSelection(enriched);
    } catch (reason) {
      setExportError(reason instanceof Error ? reason.message : "선택 격자 분석 지도를 만들지 못했습니다.");
      onShareSelection(selection);
    } finally {
      setSharingSelection(false);
    }
  };

  const toggleSelectionMaterial = async () => {
    if (!selection) return;
    if (selectionMaterialSelected) {
      onRemoveReportMaterial(selectionMaterialId);
      return;
    }
    setExporting(true);
    setExportError("");
    try {
      const enriched = selection.report_material.spatial_image
        ? selection
        : await selectionWithImage(selection);
      setSelection(enriched);
      onAddReportMaterial({ source_id: selectionMaterialId, ...enriched.report_material });
    } catch (reason) {
      setExportError(reason instanceof Error ? reason.message : "선택 격자 보고서 지도를 만들지 못했습니다.");
    } finally {
      setExporting(false);
    }
  };

  const askAboutSelection = () => {
    if (!selected) return;
    const place = selected.ADM_NM || selected.SGG_NM || region;
    onAsk(`${place} ${selected.FTR_IDN} 격자의 ${metric.label} 등급과 위험 요인을 실제 데이터로 분석해줘`);
  };

  const explainSelectedFeature = async () => {
    if (!region || !selected?.FTR_IDN) return;
    setOperationLoading(true);
    setSelectionError("");
    try {
      const result = await api.spatialFeatureExplanation(region, String(selected.FTR_IDN), metricId);
      onShareSelection(result);
    } catch (reason) {
      setSelectionError(reason instanceof Error ? reason.message : "선택 격자의 위험 원인을 분석하지 못했습니다.");
    } finally {
      setOperationLoading(false);
    }
  };

  const analyzeSelectedNeighborhood = async (distanceM: number) => {
    if (!region || !selected?.FTR_IDN) return;
    setOperationLoading(true);
    setSelectionError("");
    try {
      const result = await api.spatialNeighborhood({
        region,
        ftr_id: String(selected.FTR_IDN),
        distance_m: distanceM,
        metric: metricId,
        grades,
      });
      onSpatialOperation(result);
    } catch (reason) {
      setSelectionError(reason instanceof Error ? reason.message : "주변 격자를 분석하지 못했습니다.");
    } finally {
      setOperationLoading(false);
    }
  };

  const analyzeCurrentHotspots = async () => {
    if (!region) return;
    setOperationLoading(true);
    setSelectionError("");
    try {
      const result = await api.spatialHotspots({
        region,
        metric: metricId,
        grades: grades.length ? grades : ["4", "5"],
        min_cluster_size: 2,
      });
      onSpatialOperation(result);
    } catch (reason) {
      setSelectionError(reason instanceof Error ? reason.message : "핫스팟 군집을 분석하지 못했습니다.");
    } finally {
      setOperationLoading(false);
    }
  };

  const createMapImage = async (options: {
    background?: ExportBackground;
    extent?: ExportExtent;
    geometry?: GeoJSONPolygon;
  } = {}) => {
    if (!region) throw new Error("이미지를 만들 지역을 먼저 선택해주세요.");
    const background = options.background || (baseMap === "satellite" ? "satellite" : "composite");
    const extent = options.extent || "region";
    const geometry = options.geometry || (
      extent === "selection" ? selection?.geometry : extent === "viewport" ? viewportGeometry : undefined
    );
    if (extent !== "region" && !geometry) throw new Error("저장할 지도 범위를 확인해주세요.");
    const result = await api.spatialExport({
      region,
      metric: metricId,
      grades,
      focus_names: focusNames,
      background,
      extent,
      ...(geometry ? { geometry } : {}),
    });
    setExported(result);
    return result;
  };

  const saveMapImage = async () => {
    setExporting(true);
    setExportError("");
    try {
      const result = await createMapImage({ background: exportBackground, extent: exportExtent });
      downloadInBrowser(result.download_url, result.filename);
      setExportOptionsOpen(false);
    } catch (reason) {
      setExportError(reason instanceof Error ? reason.message : "지도 이미지를 만들지 못했습니다.");
    } finally {
      setExporting(false);
    }
  };

  const uploadAnnotation = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    setAnnotationLoading(true);
    setAnnotationError("");
    try {
      const imported = await api.spatialAnnotation(files);
      setAnnotation(imported);
      setAnnotationField(imported.suggested_label_field);
      setAnnotationVisible(true);
    } catch (reason) {
      setAnnotationError(reason instanceof Error ? reason.message : "annotation 레이어를 불러오지 못했습니다.");
    } finally {
      setAnnotationLoading(false);
    }
  };

  const toggleReportImage = async () => {
    if (materialSelected) {
      onRemoveReportMaterial(materialKey);
      return;
    }
    setExporting(true);
    setExportError("");
    try {
      const result = await createMapImage();
      const gradeText = grades.length ? `${grades.join("·")}등급` : "전체 등급";
      onAddReportMaterial({
        source_id: materialKey,
        question: `${metric.label} 공간분석 지도`,
        answer: `${result.region}의 ${metric.label} ${gradeText} 격자 ${result.feature_count.toLocaleString()}개를 실제 GPKG로 표시한 지도입니다.`,
        region: result.region,
        grounded: true,
        queries: [],
        results: [],
        spatial_image: {
          image_id: result.image_id,
          filename: result.filename,
          caption: result.caption,
        },
      });
    } catch (reason) {
      setExportError(reason instanceof Error ? reason.message : "보고서용 지도 이미지를 만들지 못했습니다.");
    } finally {
      setExporting(false);
    }
  };

  const startLayerResize = (event: ReactMouseEvent<HTMLElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = layerWidth;
    const move = (moveEvent: MouseEvent) => {
      setLayerWidth(Math.min(380, Math.max(220, startWidth + moveEvent.clientX - startX)));
    };
    const stop = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", stop);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);
  };

  const latestVisibleOperation = [...operationLayers]
    .reverse()
    .find((operation) => !hiddenOperationIds.includes(operation.operation_id));

  return <aside className="spatial-studio" aria-label="GPKG 공간분석">
    <header className="spatial-header">
      <div><h2>공간분석</h2></div>
      <div className="spatial-header-meta"><i /> {region ? displayRegionName(region) : "지역 미선택"}<b>EPSG:5179 → 4326</b></div>
      <button onClick={onClose} aria-label="공간분석 닫기">닫기</button>
    </header>

    <div
      className={`spatial-body ${layerCollapsed ? "layer-collapsed" : ""}`}
      style={{ "--layer-width": `${layerWidth}px` } as CSSProperties}
    >
      {!layerCollapsed && <section className="layer-panel" aria-label="레이어 창">
        <div className="panel-caption"><span>레이어</span><button onClick={() => setLayerCollapsed(true)} aria-label="레이어 창 접기">접기</button></div>
        <label className="layer-item">
          <input type="checkbox" checked={visible} onChange={(event) => setVisible(event.target.checked)} />
          <span className="layer-swatch" />
          <span><strong>{layer?.name || "연안재해 위험 격자"}</strong><small>{layer ? `${layer.feature_count.toLocaleString()} features` : "불러오는 중"}</small></span>
        </label>
        {operationLayers.length > 0 && <>
          <div className="layer-subtitle"><Layers3 size={13} /> 분석 결과 레이어</div>
          <div className="operation-layer-list">
            {operationLayers.map((operation) => {
              const visibleOperation = !hiddenOperationIds.includes(operation.operation_id);
              const saved = temporaryLayerIds.includes(operation.operation_id);
              return <div key={operation.operation_id}>
                <label>
                  <input
                    type="checkbox"
                    checked={visibleOperation}
                    onChange={() => setHiddenOperationIds((current) => visibleOperation
                      ? [...current, operation.operation_id]
                      : current.filter((id) => id !== operation.operation_id))}
                  />
                  <span><strong>{operation.name}</strong><small>{operation.stats.feature_count.toLocaleString()}개 격자</small></span>
                </label>
                {saved
                  ? <button aria-label={`${operation.name} 임시 레이어 삭제`} onClick={() => onRemoveOperationLayer(operation.operation_id)}><X size={12} /></button>
                  : <button aria-label={`${operation.name} 임시 레이어 저장`} onClick={() => onKeepOperationLayer(operation)}><BookmarkPlus size={12} /></button>}
              </div>;
            })}
          </div>
        </>}
        <div className="layer-subtitle"><Image size={13} /> 배경지도</div>
        <div className="basemap-switch" role="group" aria-label="배경지도 선택">
          <button
            className={baseMap === "street" ? "active" : ""}
            aria-label="일반지도 배경지도"
            aria-pressed={baseMap === "street"}
            onClick={() => setBaseMap("street")}
          >일반지도</button>
          <button
            className={baseMap === "satellite" ? "active" : ""}
            aria-label="위성영상 배경지도"
            aria-pressed={baseMap === "satellite"}
            onClick={() => setBaseMap("satellite")}
          >위성영상</button>
        </div>
        <div className="layer-subtitle"><BarChart3 size={13} /> 격자 표시 기준</div>
        <label className="metric-select">
          <span>평가항목</span>
          <select
            aria-label="지도 평가항목"
            value={metricId}
            onChange={(event) => setMetricId(event.target.value)}
          >
            {metricGroups.map(([group, items]) => <optgroup label={group} key={group}>
              {items.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}
            </optgroup>)}
          </select>
          <small>{metric.group} · GPKG {metric.grade_column}</small>
        </label>
        <div className="layer-subtitle"><SlidersHorizontal size={13} /> 위험 등급 필터</div>
        <div className="grade-filter">
          {["5", "4", "3", "2", "1"].map((grade) => <button
            className={grades.includes(grade) ? "active" : ""}
            key={grade}
            onClick={() => toggleGrade(grade)}
          >
            <i style={{ background: GRADE_COLORS[grade] }} />
            <span>{grade}등급</span>
            <small>{metric.grade_counts[grade] || 0}</small>
            {grades.includes(grade) && <Check size={11} />}
          </button>)}
        </div>
        <button
          type="button"
          className="hotspot-run"
          disabled={operationLoading || !region}
          onClick={analyzeCurrentHotspots}
        ><BarChart3 size={13} /> {operationLoading ? "공간 연산 중" : "현재 조건 핫스팟 분석"}</button>
        <div className="layer-subtitle"><MousePointer2 size={13} /> 사용자 지정 영역</div>
        <div className="selection-tools">
          <button
            className={drawing ? "active" : ""}
            aria-label="사용자 영역 그리기"
            aria-pressed={drawing}
            onClick={() => {
              if (!drawing) {
                setSelectionPoints([]);
                setSelection(null);
                setSelectionError("");
              }
              setDrawing((current) => !current);
            }}
          >{drawing ? "점 지정 중" : "영역 그리기"}</button>
          <button
            className={boxSelecting ? "active" : ""}
            aria-label="드래그로 영역 선택"
            aria-pressed={boxSelecting}
            onClick={() => {
              if (!boxSelecting) {
                setDrawing(false);
                setSelectionPoints([]);
                setSelection(null);
                setSelectionError("");
              }
              setBoxDrag(null);
              setBoxSelecting((current) => !current);
            }}
          >{boxSelecting ? "드래그 중" : "드래그 선택"}</button>
          <button
            aria-label="선택 영역 분석 실행"
            disabled={selectionPoints.length < 3 || selectionLoading}
            onClick={() => analyzeArea()}
          >{selectionLoading ? "분석 중" : "통계·중첩 분석"}</button>
          <button
            aria-label="마지막 꼭짓점 되돌리기"
            disabled={!selectionPoints.length || selectionLoading}
            onClick={() => setSelectionPoints((current) => current.slice(0, -1))}
          >되돌리기</button>
          <button
            aria-label="선택 영역 초기화"
            disabled={!selectionPoints.length && !selection}
            onClick={resetSelection}
          >초기화</button>
        </div>
        <small className="selection-help">
          {drawing
            ? `지도에서 꼭짓점을 클릭하세요 · 현재 ${selectionPoints.length}개`
            : boxSelecting
              ? "지도를 드래그하면 놓는 즉시 그 범위가 선택·분석됩니다."
              : "3개 이상의 꼭짓점으로 지정하거나, 드래그 선택으로 빠르게 훑어보세요."}
        </small>
        {selectionPoints.length >= 3 && <div className="scenario-save-row">
          <input
            aria-label="분석 시나리오 이름"
            value={scenarioName}
            placeholder="시나리오 이름"
            onChange={(event) => setScenarioName(event.target.value)}
          />
          <button disabled={scenarioLoading} onClick={saveScenario}>저장</button>
        </div>}
        <button
          className="scenario-list-toggle"
          aria-label="저장 시나리오 보기"
          aria-expanded={scenariosOpen}
          onClick={() => setScenariosOpen((current) => !current)}
        >저장 시나리오 <span>{scenarios.length}</span></button>
        {scenariosOpen && <div className="scenario-list">
          {scenarios.length === 0 && <small>저장된 시나리오가 없습니다.</small>}
          {scenarios.map((scenario) => <div key={scenario.id}>
            <button disabled={scenarioLoading} onClick={() => runScenario(scenario)}>
              <strong>{scenario.name}</strong>
              <small>{displayRegionName(scenario.region)} · {scenario.grades.length ? `${scenario.grades.join("·")}등급` : "전체 등급"}</small>
            </button>
            <button aria-label={`${scenario.name} 삭제`} disabled={scenarioLoading} onClick={() => deleteScenario(scenario.id)}><X size={12} /></button>
          </div>)}
        </div>}
        {selectionError && <small className="selection-error" role="alert">{selectionError}</small>}
        <label className="opacity-control">
          <span>레이어 불투명도 <b>{opacity}%</b></span>
          <input type="range" min="20" max="100" value={opacity} onChange={(event) => setOpacity(Number(event.target.value))} />
        </label>
        <div className="spatial-export-actions">
          <button
            aria-label="현재 지도 이미지 저장"
            disabled={exporting || !region}
            onClick={() => {
              setExportBackground(baseMap === "satellite" ? "satellite" : "composite");
              setExportOptionsOpen(true);
            }}
          ><Download size={13} /> {exporting ? "이미지 생성 중" : "이미지 저장"}</button>
          <button
            className={materialSelected ? "selected" : ""}
            aria-label={materialSelected ? "현재 지도를 보고서에서 제외" : "현재 지도를 보고서에 추가"}
            disabled={exporting || !region}
            onClick={toggleReportImage}
          >{materialSelected ? <BookMarked size={13} /> : <BookmarkPlus size={13} />}
            {materialSelected ? "보고서에 담김" : "보고서에 추가"}
          </button>
          {exported && <a
            href={exported.download_url}
            download={exported.filename}
            onClick={(event) => {
              event.preventDefault();
              downloadInBrowser(exported.download_url, exported.filename);
            }}
          >
            <Download size={12} /> PNG 다운로드
          </a>}
          {exportError && <small role="alert">{exportError}</small>}
        </div>
        {exportOptionsOpen && <div className="map-export-dialog" role="dialog" aria-label="지도 이미지 저장 옵션">
          <div className="map-export-dialog-head"><strong>이미지 저장 옵션</strong><button aria-label="지도 이미지 저장 옵션 닫기" onClick={() => setExportOptionsOpen(false)}><X size={13} /></button></div>
          <fieldset>
            <legend>백그라운드</legend>
            {([
              ["satellite", "위성영상"], ["composite", "종합지도"], ["transparent", "투명"],
            ] as Array<[ExportBackground, string]>).map(([value, label]) => <label key={value}>
              <input type="radio" name="export-background" value={value} checked={exportBackground === value} onChange={() => setExportBackground(value)} />
              <span>{label}</span>
            </label>)}
          </fieldset>
          <fieldset>
            <legend>대상지역</legend>
            {([
              ["region", "지역 전체"], ["viewport", "현재 화면"], ["selection", "선택 격자"],
            ] as Array<[ExportExtent, string]>).map(([value, label]) => <label key={value} className={value === "selection" && !selection ? "disabled" : ""}>
              <input
                type="radio"
                name="export-extent"
                value={value}
                disabled={value === "selection" && !selection}
                checked={exportExtent === value}
                onChange={() => setExportExtent(value)}
              />
              <span>{label}</span>
            </label>)}
          </fieldset>
          <button className="map-export-confirm" disabled={exporting} onClick={saveMapImage}>
            <Download size={13} /> {exporting ? "생성 중" : "옵션대로 이미지 생성"}
          </button>
        </div>}
        <div className="layer-subtitle"><Upload size={13} /> 지역 annotation</div>
        <label className="annotation-upload">
          <input
            type="file"
            multiple
            accept=".zip,.shp,.shx,.dbf,.prj,.cpg"
            aria-label="지역 annotation 파일 업로드"
            onChange={uploadAnnotation}
          />
          <Upload size={13} /> {annotationLoading ? "레이어 변환 중" : "Shapefile 불러오기"}
        </label>
        <small className="annotation-help">ZIP 또는 SHP·SHX·DBF·PRJ 파일을 함께 선택</small>
        {annotationError && <small className="annotation-error" role="alert">{annotationError}</small>}
        {annotation && <div className="annotation-layer-item">
          <div>
            <label>
              <input
                type="checkbox"
                checked={annotationVisible}
                onChange={(event) => setAnnotationVisible(event.target.checked)}
              />
              <span><strong>{annotation.name}</strong><small>{annotation.feature_count.toLocaleString()} features</small></span>
            </label>
            <button aria-label="annotation 레이어 제거" onClick={() => setAnnotation(null)}><X size={13} /> 제거</button>
          </div>
          <label className="annotation-field">
            <span>표시 필드</span>
            <select
              aria-label="annotation 표시 필드"
              value={annotationField}
              onChange={(event) => setAnnotationField(event.target.value)}
            >
              {annotation.columns.map((column) => <option key={column}>{column}</option>)}
            </select>
          </label>
        </div>}
        <div className="layer-source"><Database size={14} /><span><strong>GeoPackage</strong><small>본평가_평가완료_시각화</small></span></div>
      </section>}

      {!layerCollapsed && <div
        className="layer-resizer"
        role="separator"
        aria-label="레이어 창 너비 조절"
        aria-orientation="vertical"
        aria-valuemin={220}
        aria-valuemax={380}
        aria-valuenow={layerWidth}
        tabIndex={0}
        onMouseDown={startLayerResize}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") setLayerWidth((width) => Math.max(220, width - 16));
          if (event.key === "ArrowRight") setLayerWidth((width) => Math.min(380, width + 16));
        }}
      />}

      <section className="map-workspace">
        {layerCollapsed && <button className="layer-expand" onClick={() => setLayerCollapsed(false)} aria-label="레이어 창 펼치기">레이어 펼치기</button>}
        <div className="map-toolbar">
          <span><MousePointer2 size={14} /> 피처를 클릭해 속성 조회</span>
          {context && <span className="conversation-context"><MessageSquareText size={13} /> {context}</span>}
          {focusNames.length > 0 && <span className="map-focus-context">{focusNames.join(" · ")}</span>}
          <strong>{loading ? "조회 중" : `${activeCount.toLocaleString()}개 대상 · ${features.length.toLocaleString()}개 표시`}</strong>
        </div>
        <div className="map-canvas">
          <MapContainer center={[35.15, 129.11]} zoom={12} zoomControl preferCanvas className="leaflet-map">
            <MapResizeInvalidator />
            <MapViewportReporter onChange={setViewportGeometry} />
            <AreaDrawing
              enabled={drawing}
              onPoint={(point) => setSelectionPoints((current) => [...current, point])}
              onHover={setDrawCursor}
            />
            <BoxSelection
              enabled={boxSelecting}
              dragging={boxDrag !== null}
              onStart={(point) => setBoxDrag({ start: point, end: point })}
              onMove={(point) => setBoxDrag((current) => (current ? { ...current, end: point } : current))}
              onFinish={(point) => { if (boxDrag) finishBoxSelection(boxDrag.start, point); }}
            />
            {baseMap === "street" ? <TileLayer
              key="street"
              attribution="&copy; OpenStreetMap contributors"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            /> : <TileLayer
              key="satellite"
              attribution="Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community"
              url="https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            />}
            {visible && collection && features.length > 0 && <GeoJSON
              key={mapKey}
              data={collection as GeoJsonObject}
              style={(feature) => featureStyle(feature, opacity, selectedId, metric.grade_column)}
              onEachFeature={(feature, mapLayer) => {
                const properties = feature.properties as Properties;
                const content = `${properties.ADM_NM || "격자"} · ${metric.label} ${properties[metric.grade_column] || "-"}등급`;
                mapLayer.on("mouseover", (event) => {
                  const map = (event.target as unknown as { _map?: LeafletMap })._map;
                  const latlng = (event as unknown as { latlng: LatLngExpression }).latlng;
                  if (!map || !latlng) return;
                  const overlay = sharedFeatureTooltip.current || createTooltip({ direction: "auto", opacity: 0.9 });
                  sharedFeatureTooltip.current = overlay;
                  displaySharedFeatureTooltip(
                    overlay,
                    map,
                    content,
                    latlng,
                    document.body.classList.contains("leaflet-dragging"),
                  );
                });
                mapLayer.on("mouseout mousedown", () => sharedFeatureTooltip.current?.remove());
                mapLayer.on("click", () => setSelected(properties));
              }}
            />}
            {selectionPoints.length > 0 && (selectionPoints.length >= 3
              ? <Polygon
                positions={selectionPoints}
                pathOptions={{ color: "#075fcb", weight: 3, fillColor: "#1683ed", fillOpacity: 0.12 }}
              />
              : <Polyline positions={selectionPoints} pathOptions={{ color: "#075fcb", weight: 3, dashArray: "7 6" }} />)}
            {selectionPoints.map((point, index) => <CircleMarker
              key={`selection-vertex-${index}`}
              center={point}
              radius={5}
              interactive={false}
              pathOptions={{ color: "#075fcb", weight: 2, fillColor: "#ffffff", fillOpacity: 1 }}
            />)}
            {boxDrag && <Polygon
              positions={boxSelectionPoints(boxDrag.start, boxDrag.end)}
              pathOptions={{ color: "#075fcb", weight: 2, dashArray: "5 5", fillColor: "#1683ed", fillOpacity: 0.1 }}
            />}
            {drawing && drawCursor && <CircleMarker
              center={drawCursor}
              radius={5}
              interactive={false}
              pathOptions={{ color: "#075fcb", weight: 1.5, fillColor: "#1683ed", fillOpacity: 0.45 }}
            />}
            {comparisonBase && <Polygon
              positions={selectionPositions(comparisonBase.geometry)}
              pathOptions={{ color: "#075fcb", weight: 3, fillColor: "#2f80ed", fillOpacity: .12 }}
            />}
            {selection && <GeoJSON
              key={`selection-${selection.selection_id}`}
              data={selection.feature_collection as GeoJsonObject}
              style={() => ({ color: "#042f66", weight: 2.4, fillColor: "#00a7b5", fillOpacity: 0.48 })}
            />}
            {operationLayers.filter((operation) => !hiddenOperationIds.includes(operation.operation_id)).map((operation, index) => <GeoJSON
              key={`operation-${operation.operation_id}`}
              data={operation.feature_collection as GeoJsonObject}
              style={() => ({
                color: operation.operation === "query_scope" ? "#6d4ac7" : "#073c73",
                weight: operation.operation === "query_scope" ? 2.2 : 1.6,
                dashArray: operation.operation === "query_scope" ? "6 5" : undefined,
                fillColor: operation.operation === "hotspot" ? "#ff0000" : index % 2 ? "#00a7b5" : "#1683ed",
                fillOpacity: operation.operation === "query_scope" ? 0.12 : 0.42,
              })}
            />)}
            {annotationVisible && annotation && <GeoJSON
              key={`${annotation.id}-${annotationField}-${baseMap}`}
              data={annotation.geojson as GeoJsonObject}
              style={() => ({
                color: baseMap === "satellite" ? "#28d7ff" : "#0869ca",
                weight: 2,
                fillColor: "#2e92ee",
                fillOpacity: 0.08,
              })}
              onEachFeature={(feature, mapLayer) => {
                const value = feature.properties?.[annotationField];
                if (value !== null && value !== undefined && String(value).trim()) {
                  mapLayer.bindTooltip(String(value), {
                    permanent: true,
                    direction: "center",
                    className: "annotation-label",
                  });
                }
              }}
            />}
            {collection && features.length > 0 && <FitToFeatures collection={collection} />}
            {annotationVisible && annotation && <FitToFeatures collection={annotation.geojson} />}
            {selection && <FitToFeatures collection={selection.feature_collection} />}
            {latestVisibleOperation && latestVisibleOperation.feature_collection.features.length > 0
              && <FitToFeatures collection={latestVisibleOperation.feature_collection} />}
          </MapContainer>
          {loading && <div className="map-loading"><span /><p>GPKG 공간 레이어를 조회하고 있습니다.</p></div>}
          {error && <div className="map-error"><CircleAlert size={16} /> {error}</div>}
          <div className="map-legend">
            <strong>{metric.label} 등급</strong>
            {["1", "2", "3", "4", "5"].map((grade) => <span key={grade}><i style={{ background: GRADE_COLORS[grade] }} /> {grade}</span>)}
            {(metric.grade_counts[""] || 0) > 0 && <span><i style={{ background: "#9aa8b8" }} /> 미평가</span>}
          </div>
          {selected && <FeatureInspector
            properties={selected}
            metric={metric}
            loading={operationLoading}
            onAsk={askAboutSelection}
            onExplain={explainSelectedFeature}
            onNeighborhood={analyzeSelectedNeighborhood}
            onClose={() => setSelected(null)}
          />}
          {operationLayers.length > 0 && (() => {
            const operation = operationLayers[operationLayers.length - 1];
            const saved = temporaryLayerIds.includes(operation.operation_id);
            const reportId = `spatial-operation:${operation.operation_id}`;
            const reportSelected = reportMaterialIds.includes(reportId);
            return <OperationResultCard
              key={operation.operation_id}
              operation={operation}
              saved={saved}
              reportSelected={reportSelected}
              onKeep={() => onKeepOperationLayer(operation)}
              onToggleReport={() => reportSelected
                ? onRemoveReportMaterial(reportId)
                : onAddReportMaterial({ source_id: reportId, ...operation.report_material })}
            />;
          })()}
          {selection && <div className="selection-result-card">
            <div><span>선택 영역 분석</span><button aria-label="선택 영역 분석 닫기" onClick={() => setSelection(null)}><X size={13} /></button></div>
            <strong>{selection.summary}</strong>
            <dl className="selection-metrics">
              <div><dt>선택 격자</dt><dd>{selection.stats.selected_count.toLocaleString()}개</dd></div>
              <div><dt>평균 등급</dt><dd>{selection.stats.average_grade ?? "-"}</dd></div>
              <div><dt>4·5등급</dt><dd>{selection.stats.high_risk_count.toLocaleString()}개 · {selection.stats.high_risk_pct}%</dd></div>
            </dl>
            <p className="selection-inline-note">상세 표(항목별 중첩·원인 요인)는 대화창 카드에 표시됩니다.</p>
            <div className="selection-result-actions">
              <button disabled={sharingSelection} onClick={shareSelection}><MessageSquareText size={13} /> {sharingSelection ? "분석 정리 중" : "채팅에 분석 표시"}</button>
              <button disabled={exporting} className={selectionMaterialSelected ? "selected" : ""} onClick={toggleSelectionMaterial}>
                {selectionMaterialSelected ? <BookMarked size={13} /> : <BookmarkPlus size={13} />}
                {selectionMaterialSelected ? "보고서 자료에 포함됨" : "보고서 자료에 추가"}
              </button>
              {!comparisonBase ? <button type="button" onClick={saveComparisonBase}>
                A 영역으로 저장
              </button> : <button type="button" disabled={selectionLoading} onClick={compareAreas}>
                {selectionLoading ? "비교 중" : "A/B 비교 실행"}
              </button>}
              <button type="button" disabled={selectionMcpLoading} onClick={() => void runSelectionMcp()}>
                <Sparkles size={13} /> {selectionMcpLoading ? "시각화 생성 중" : "MCP 시각화"}
              </button>
            </div>
            {selectionMcpError && <small className="selection-error" role="alert">{selectionMcpError}</small>}
          </div>}
          {selectionComparison && <div className="selection-comparison-card">
            <div>
              <span>선택 영역 A/B 비교</span>
              <button aria-label="A/B 영역 비교 닫기" onClick={() => setSelectionComparison(null)}><X size={13} /></button>
            </div>
            <strong>{selectionComparison.summary}</strong>
            <dl>
              <div><dt>A 영역</dt><dd>{selectionComparison.area_a.stats.selected_count.toLocaleString()}개 · {selectionComparison.area_a.stats.high_risk_pct}%</dd></div>
              <div><dt>B 영역</dt><dd>{selectionComparison.area_b.stats.selected_count.toLocaleString()}개 · {selectionComparison.area_b.stats.high_risk_pct}%</dd></div>
              <div><dt>고위험 격차</dt><dd>{selectionComparison.difference.high_risk_pct_point > 0 ? "+" : ""}{selectionComparison.difference.high_risk_pct_point}%p</dd></div>
            </dl>
            <button
              type="button"
              onClick={() => onAddReportMaterial({
                source_id: `selection-compare:${selectionComparison.area_a.selection_id}:${selectionComparison.area_b.selection_id}`,
                ...selectionComparison.report_material,
              })}
            ><BookmarkPlus size={13} /> 비교 결과를 보고서에 추가</button>
          </div>}
        </div>

        <div
          className={`attribute-dock ${tableOpen ? "open" : ""}`}
          style={{ "--attribute-table-height": `${tableHeight}px` } as CSSProperties}
        >
          {tableOpen && <div
            className="attribute-resizer"
            role="separator"
            aria-label="지도와 속성 테이블 높이 조절"
            aria-orientation="horizontal"
            aria-valuemin={ATTRIBUTE_TABLE_MIN_HEIGHT}
            aria-valuemax={attributeTableMaxHeight(window.innerHeight)}
            aria-valuenow={tableHeight}
            tabIndex={0}
            title="드래그하여 지도와 속성 테이블 비율 조절"
            onMouseDown={startAttributeTableResize}
            onKeyDown={(event) => {
              if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
              event.preventDefault();
              const delta = event.key === "ArrowUp" ? 16 : -16;
              setTableHeight((height) => clampAttributeTableHeight(
                height + delta,
                window.innerHeight,
              ));
            }}
          ><span /></div>}
          <button className="attribute-toggle" onClick={() => setTableOpen(!tableOpen)}>
            <PanelBottom size={14} /><strong>속성 테이블</strong><span>{features.length.toLocaleString()}개 피처</span><ChevronDown size={14} />
          </button>
          {tableOpen && <div className="attribute-table"><table><thead><tr>
            <th>격자 ID</th><th>읍·면·동</th><th>위해성</th><th>노출성</th><th>취약성</th><th>{metric.label} 등급</th>
          </tr></thead><tbody>
            {rows.map((feature, index) => {
              const properties = feature.properties as Properties;
              const id = String(properties.FTR_IDN || index);
              return <tr className={id === selectedId ? "selected" : ""} key={id} onClick={() => setSelected(properties)}>
                <td>{properties.FTR_IDN}</td><td>{properties.ADM_NM}</td><td>{properties["위해성지수_등급"]}</td><td>{properties["노출성지수_등급"]}</td><td>{properties["취약성지수(가중)_등급"]}</td><td><Grade grade={properties[metric.grade_column]} /></td>
              </tr>;
            })}
          </tbody></table></div>}
        </div>
      </section>
    </div>
  </aside>;
}

function BoxSelection({ enabled, dragging, onStart, onMove, onFinish }: {
  enabled: boolean;
  dragging: boolean;
  onStart: (point: SelectionPoint) => void;
  onMove: (point: SelectionPoint) => void;
  onFinish: (point: SelectionPoint) => void;
}) {
  const map = useMapEvents({
    mousedown(event) {
      if (enabled) onStart([event.latlng.lat, event.latlng.lng]);
    },
    mousemove(event) {
      if (enabled && dragging) onMove([event.latlng.lat, event.latlng.lng]);
    },
    mouseup(event) {
      if (enabled && dragging) onFinish([event.latlng.lat, event.latlng.lng]);
    },
  });
  useEffect(() => {
    if (!enabled) return undefined;
    const container = map.getContainer();
    container.style.cursor = "crosshair";
    map.dragging.disable();
    map.boxZoom.disable();
    return () => {
      container.style.cursor = "";
      map.dragging.enable();
      map.boxZoom.enable();
    };
  }, [enabled, map]);
  return null;
}

function AreaDrawing({ enabled, onPoint, onHover }: {
  enabled: boolean;
  onPoint: (point: SelectionPoint) => void;
  onHover: (point: SelectionPoint | null) => void;
}) {
  const map = useMapEvents({
    click(event) {
      if (enabled) onPoint([event.latlng.lat, event.latlng.lng]);
    },
    mousemove(event) {
      if (enabled) onHover([event.latlng.lat, event.latlng.lng]);
    },
    mouseout() {
      onHover(null);
    },
  });
  useEffect(() => {
    const container = map.getContainer();
    container.style.cursor = enabled ? "crosshair" : "";
    if (!enabled) onHover(null);
    return () => {
      container.style.cursor = "";
    };
  }, [enabled, map, onHover]);
  return null;
}

function featureStyle(feature: Feature | undefined, opacity: number, selectedId: string, gradeColumn: string) {
  const properties = (feature?.properties || {}) as Properties;
  const grade = String(properties[gradeColumn] || "-");
  const selected = String(properties.FTR_IDN || "") === selectedId;
  return {
    color: selected ? "#0b2147" : "#ffffff",
    weight: selected ? 3 : 0.7,
    fillColor: GRADE_COLORS[grade] || "#9aa8b8",
    fillOpacity: opacity / 100,
  };
}

function FitToFeatures({ collection }: { collection: FeatureCollection }) {
  const map = useMap();
  const bounds = useMemo(() => geoJSON(collection as GeoJsonObject).getBounds(), [collection]);
  useEffect(() => {
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [18, 18], maxZoom: 16 });
  }, [bounds, map]);
  return null;
}

function MapResizeInvalidator() {
  const map = useMap();
  useEffect(() => {
    if (typeof ResizeObserver === "undefined") {
      map.invalidateSize({ animate: false });
      return;
    }
    return watchMapResize(map, ResizeObserver);
  }, [map]);
  return null;
}

function MapViewportReporter({ onChange }: { onChange: (geometry: GeoJSONPolygon) => void }) {
  const map = useMapEvents({
    moveend() {
      report();
    },
    zoomend() {
      report();
    },
  });
  const report = () => {
    const bounds = map.getBounds();
    onChange(boundsGeometry({
      south: bounds.getSouth(), west: bounds.getWest(),
      north: bounds.getNorth(), east: bounds.getEast(),
    }));
  };
  useEffect(report, [map, onChange]);
  return null;
}

function FeatureInspector({
  properties,
  metric,
  loading,
  onAsk,
  onExplain,
  onNeighborhood,
  onClose,
}: {
  properties: Properties;
  metric: SpatialGradeMetric;
  loading: boolean;
  onAsk: () => void;
  onExplain: () => void;
  onNeighborhood: (distanceM: number) => void;
  onClose: () => void;
}) {
  const labels = metric.grade_column === DEFAULT_METRIC.grade_column
    ? PROPERTY_LABELS
    : { ...PROPERTY_LABELS, [metric.grade_column]: metric.label };
  return <div className="feature-inspector">
    <div className="inspector-head"><span>선택 피처</span><button onClick={onClose} aria-label="선택 피처 닫기">닫기</button></div>
    <strong>{properties.ADM_NM || properties.SGG_NM}</strong>
    <small>{properties.FTR_IDN}</small>
    <dl>{Object.entries(labels).map(([key, label]) => properties[key] != null && <div className={key === metric.grade_column ? "active-metric" : ""} key={key}><dt>{label}</dt><dd>{key.endsWith("등급") ? <Grade grade={properties[key]} /> : properties[key]}</dd></div>)}</dl>
    <div className="feature-spatial-actions">
      <button disabled={loading} onClick={onExplain}><MessageSquareText size={14} /> 왜 위험한지 분석</button>
      <button disabled={loading} onClick={() => onNeighborhood(0)}>인접 격자</button>
      <button disabled={loading} onClick={() => onNeighborhood(500)}>500m 주변</button>
      <button disabled={loading} onClick={onAsk}>질문으로 이어가기</button>
    </div>
  </div>;
}

function Grade({ grade }: { grade: string | number | null }) {
  const value = String(grade || "-");
  return <span className="grade-value"><i style={{ background: GRADE_COLORS[value] || "#9aa8b8" }} /> {value}등급</span>;
}

export default SpatialStudio;
