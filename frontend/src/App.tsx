import { CSSProperties, FormEvent, isValidElement, KeyboardEvent, lazy, MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent, ReactNode, RefObject, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import { downloadInBrowser } from "./download";
import {
  ArrowDownToLine,
  ArrowUp,
  BookMarked,
  BookmarkPlus,
  Check,
  ChevronDown,
  CircleAlert,
  CircleHelp,
  Code2,
  Copy,
  Database,
  FileChartColumn,
  FileText,
  FilePenLine,
  GitCompareArrows,
  History,
  Layers3,
  Link2,
  Map,
  MapPinned,
  Maximize2,
  MessageSquare,
  PanelLeft,
  Plus,
  Radar,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Square,
  X,
} from "lucide-react";

import {
  AnalysisContext,
  AdminReportJob,
  AdminUser,
  AuditLog,
  ApiError,
  api,
  AuthUser,
  ChatHistoryItem,
  ComparisonResult,
  ConversationSession,
  ConversationSummary,
  DataQualityReport,
  McpAnalysisResult,
  McpChartSpec,
  QueryResult,
  Region,
  ReportJob,
  ReportMaterial,
  ProvenanceEntry,
  SpatialSelectionAnalysis,
  SpatialOperationResult,
  UserSession,
} from "./api";
import {
  conversationTitle,
  displayRegionName,
  displayRegionText,
  gradesFromPrompt,
  isExplicitReportCommand,
  isRegionSelectionRequest,
  isReportRequest,
  isRevisionRequest,
  resolveRegionFromPrompt,
  resolveRegionsFromPrompt,
  resolveRevisionSection,
  spatialOperationFromPrompt,
} from "./conversation";
import { spatialStateFromOperation, upsertTemporaryLayer } from "./spatial-layers";
import { GRADE_COLORS } from "./theme";
import UsageGuideContent from "./UsageGuide";
import "./styles.css";

const SpatialStudio = lazy(() => import("./SpatialStudio"));

const STAGES = [
  ["ingest", "데이터"],
  ["analyze", "분석"],
  ["visualize", "시각화"],
  ["narrate", "서술"],
  ["verify", "검증"],
  ["compose", "조립"],
  ["convert", "변환"],
] as const;

const STARTERS = [
  "고위험 비율이 가장 높은 읍면동 5곳을 알려줘",
  "노출성과 취약성 요인을 비교해줘",
  "/보고서작성",
  "/공간분석",
];

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  kind: "text" | "loading" | "query" | "comparison" | "spatial" | "report" | "error";
  text?: string;
  query?: QueryResult;
  comparison?: ComparisonResult;
  spatial?: SpatialSelectionAnalysis;
  spatialOperations?: SpatialOperationResult[];
  report?: ReportJob;
  preview?: string;
  provenance?: ProvenanceEntry[];
  region?: string | null;
  analysisContext?: AnalysisContext;
  startedAt?: number;
  queryRequest?: {
    question: string;
    region: string | null;
    history: ChatHistoryItem[];
    context: AnalysisContext;
  };
};

type PendingMetricClarification = {
  question: string;
  region: string | null;
  history: ChatHistoryItem[];
  context: AnalysisContext;
};

let messageSequence = 0;
const messageId = () => `message-${++messageSequence}`;
const newConversationId = () => `session-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
const conversationStorageKey = (userId: string) => `coastal:last-conversation:${userId}`;
const regionStorageKey = (userId: string) => `coastal:last-region:${userId}`;
const SPATIAL_WIDTH_STORAGE_KEY = "coastal:spatial-width";
const SPATIAL_MIN_WIDTH = 520;
const DESKTOP_SIDEBAR_WIDTH = 280;
const EVIDENCE_MIN_HEIGHT = 360;
const EVIDENCE_MAX_HEIGHT = 1600;

export function spatialMaxWidth(viewportWidth: number) {
  if (!Number.isFinite(viewportWidth)) return 900;
  return Math.max(SPATIAL_MIN_WIDTH, Math.floor(viewportWidth - DESKTOP_SIDEBAR_WIDTH));
}

export type ChatLayoutDensity = "full" | "compact" | "minimal" | "hidden";

export function chatDensityForLayout(
  viewportWidth: number,
  spatialWidth: number,
): ChatLayoutDensity {
  const remainingWidth = viewportWidth - DESKTOP_SIDEBAR_WIDTH - spatialWidth;
  if (remainingWidth <= 48) return "hidden";
  if (remainingWidth < 420) return "minimal";
  if (remainingWidth < 720) return "compact";
  return "full";
}

function clampSpatialWidth(width: number, viewportWidth: number) {
  return Math.min(spatialMaxWidth(viewportWidth), Math.max(SPATIAL_MIN_WIDTH, width));
}

function readStorage(key: string) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // The workspace remains usable when browser storage is unavailable.
  }
}

function removeStorage(key: string) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // The server-side conversation remains authoritative.
  }
}

function useDialogKeyboard(onClose: () => void, active = true) {
  const dialogRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!active) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const focusable = () => Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]',
    ) || []);
    focusable()[0]?.focus();
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus();
    };
  }, [active]);

  return dialogRef;
}

type DialogDragState = {
  pointerId: number;
  startX: number;
  startY: number;
  originX: number;
  originY: number;
  minDeltaX: number;
  maxDeltaX: number;
  minDeltaY: number;
  maxDeltaY: number;
};

const DIALOG_VIEWPORT_MARGIN = 8;

function useDraggableDialog(dialogRef: RefObject<HTMLElement | null>) {
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragState = useRef<DialogDragState | null>(null);

  useEffect(() => {
    const move = (event: globalThis.PointerEvent) => {
      const drag = dragState.current;
      if (!drag || event.pointerId !== drag.pointerId) return;
      const deltaX = Math.min(
        drag.maxDeltaX,
        Math.max(drag.minDeltaX, event.clientX - drag.startX),
      );
      const deltaY = Math.min(
        drag.maxDeltaY,
        Math.max(drag.minDeltaY, event.clientY - drag.startY),
      );
      setOffset({ x: drag.originX + deltaX, y: drag.originY + deltaY });
    };
    const stop = (event: globalThis.PointerEvent) => {
      if (!dragState.current || event.pointerId !== dragState.current.pointerId) return;
      dragState.current = null;
      setDragging(false);
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
  }, []);

  const start = (event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    if ((event.target as Element).closest("button, input, select, textarea, a")) return;
    const rect = dialogRef.current?.getBoundingClientRect();
    if (!rect) return;

    event.preventDefault();
    dragState.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: offset.x,
      originY: offset.y,
      minDeltaX: DIALOG_VIEWPORT_MARGIN - rect.left,
      maxDeltaX: window.innerWidth - DIALOG_VIEWPORT_MARGIN - rect.right,
      minDeltaY: DIALOG_VIEWPORT_MARGIN - rect.top,
      maxDeltaY: window.innerHeight - DIALOG_VIEWPORT_MARGIN - rect.bottom,
    };
    setDragging(true);
  };

  return { dragging, offset, start };
}

function storedSpatialWidth() {
  const stored = readStorage(SPATIAL_WIDTH_STORAGE_KEY);
  if (stored === null) return 640;
  const value = Number(stored);
  return Number.isFinite(value) ? clampSpatialWidth(value, window.innerWidth) : 640;
}

function isSpatialDisplayRequest(prompt: string) {
  return /(지도|공간분석|공간\s*분석|위치|시각화|격자.{0,8}(보여|표시)|분포.{0,8}(보여|표시))/.test(prompt);
}

function metricDefinitionFromPrompt(prompt: string) {
  const compact = prompt.replace(/\s+/g, "");
  if (!compact.includes("고위험")) return null;
  if (/(구성비|차지하는비중|전체고위험중)/.test(compact)) return "high_risk_share" as const;
  if (/(전체격자대비|자체대비|해당지역전체)/.test(compact)) return "high_risk_ratio" as const;
  if (compact.includes("비율") && /(읍면동|동별|지역별|시군구별)/.test(compact)) return "ambiguous" as const;
  return null;
}

function isChatMessage(value: unknown): value is ChatMessage {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ChatMessage>;
  return typeof candidate.id === "string"
    && ["user", "assistant"].includes(candidate.role || "")
    && ["text", "loading", "query", "comparison", "spatial", "report", "error"].includes(candidate.kind || "");
}

function queryContextPayload(context: AnalysisContext): AnalysisContext {
  if (!context.selection?.ftr_ids) return context;
  const { ftr_ids: _ftrIds, ...selection } = context.selection;
  return { ...context, selection };
}

function queryMapSelection(result: QueryResult, fallbackGrades: string[]) {
  const focusNames: string[] = [];
  const resultGrades: string[] = [];
  for (const table of result.results) {
    const placeIndexes = table.columns.flatMap((column, index) => (
      /^(ADM_NM|읍면동|읍·면·동|행정동|지역|지역명)$/i.test(column) ? [index] : []
    ));
    const gradeIndexes = table.columns.flatMap((column, index) => (
      /(위험성지수.*등급|종합.*등급|risk.*grade|^등급$)/i.test(column) ? [index] : []
    ));
    for (const row of table.rows) {
      for (const index of placeIndexes) {
        const value = row[index];
        if (typeof value !== "string") continue;
        const name = value.trim();
        if (name && /(동|읍|면)$/.test(name) && !focusNames.includes(name)) focusNames.push(name);
      }
      for (const index of gradeIndexes) {
        const grade = String(row[index] ?? "");
        if (/^[1-5]$/.test(grade) && !resultGrades.includes(grade)) resultGrades.push(grade);
      }
    }
  }
  return {
    focusNames: focusNames.slice(0, 30),
    grades: fallbackGrades.length ? fallbackGrades : resultGrades.sort(),
  };
}

function mcpChartTable(table: QueryResult["results"][number]) {
  const populatedIndexes = table.columns.flatMap((_, index) => (
    table.rows.some((row) => row[index] !== null && row[index] !== undefined && row[index] !== "")
      ? [index]
      : []
  ));
  const numericIndexes = table.columns.flatMap((column, index) => (
    table.rows.some((row) => typeof row[index] === "number" && Number.isFinite(row[index]))
      ? [index]
      : []
  ));
  const priority = (index: number) => {
    const column = table.columns[index];
    if (/^(ADM_NM|읍면동|읍·면·동|행정동|지역|지역명|region)$/i.test(column)) return 4;
    if (/(위험성지수.*등급|risk.*grade|비율|pct|ratio|지수|등급|score|grade)/i.test(column)) {
      return 3;
    }
    if (!numericIndexes.includes(index) && !/(^|_)(id|idn)($|_)/i.test(column)) return 2;
    return numericIndexes.includes(index) ? 1 : 0;
  };
  const selectedIndexes = populatedIndexes
    .sort((left, right) => priority(right) - priority(left) || left - right)
    .slice(0, 50)
    .sort((left, right) => left - right);
  const indexes = selectedIndexes.length ? selectedIndexes : [0];
  return {
    columns: indexes.map((index) => table.columns[index]),
    rows: table.rows.map((row) => indexes.map((index) => row[index])),
  };
}

const MCP_COLUMN_UNITS: Record<string, string> = {
  강우: "mm/h",
  강풍: "m/s",
  파랑: "m",
  해일: "m",
  "해수면 상승": "mm/yr",
  인구: "명",
  고령인구: "명",
  건물: "m²",
  도로: "m²",
  농경지: "m²",
  시설재배: "m²",
  양식장: "m²",
  "어항·항만": "m²",
  위험시설물: "개",
  문화재: "개",
  대피소: "명",
};

type ReportOptions = {
  use_llm: boolean;
  use_judge: boolean;
  make_hwpx: boolean;
};

function mcpAxisLabel(column?: string) {
  if (!column) return undefined;
  const exactUnit = MCP_COLUMN_UNITS[column];
  if (exactUnit) return `${column} (${exactUnit})`;
  if (/(비율|pct|ratio)/i.test(column)) return `${column} (%)`;
  if (/(격자.*수|^cnt|count)/i.test(column)) return `${column} (개)`;
  if (/(등급|grade)/i.test(column)) return `${column} (등급)`;
  return column;
}

function mcpCustomTable(
  table: QueryResult["results"][number],
  spec: McpChartSpec,
) {
  const selected = [
    spec.x_column,
    spec.y_column,
    spec.group_column,
    spec.stack_column,
    ...(spec.columns || []),
  ].filter((column, index, items): column is string => (
    Boolean(column) && items.indexOf(column) === index
  ));
  const indexes = selected.map((column) => table.columns.indexOf(column));
  return {
    columns: selected,
    rows: table.rows.map((row) => indexes.map((index) => row[index])),
  };
}

function mcpChartLabel(chart: string) {
  const labels: Record<string, string> = {
    bar: "막대 차트",
    stacked_bar: "누적 막대 차트",
    line: "선 차트",
    area: "영역 차트",
    scatter: "산점도",
    histogram: "히스토그램",
    boxplot: "상자수염 차트",
    correlation_heatmap: "상관관계 히트맵",
    crosstab_heatmap: "교차표 히트맵",
    missingness: "결측치 차트",
    small_multiples: "소형 다중 차트",
  };
  return labels[chart] || "추천 차트";
}

function App() {
  const [authRequired, setAuthRequired] = useState(false);
  const [authUser, setAuthUser] = useState<AuthUser | null>(api.authState());
  const [accountOpen, setAccountOpen] = useState(false);
  const [accountSettingsOpen, setAccountSettingsOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [metricClarification, setMetricClarification] = useState<PendingMetricClarification | null>(null);
  const [regions, setRegions] = useState<Region[]>([]);
  const [sido, setSido] = useState("");
  const [district, setDistrict] = useState("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [toast, setToast] = useState<{
    message: string;
    tone: "success" | "error" | "info";
  } | null>(null);
  const [spatialOpen, setSpatialOpen] = useState(false);
  const [spatialRegion, setSpatialRegion] = useState<string | null>(null);
  const [spatialContext, setSpatialContext] = useState("");
  const [spatialGrades, setSpatialGrades] = useState<string[]>([]);
  const [spatialFocusNames, setSpatialFocusNames] = useState<string[]>([]);
  const [spatialMetric, setSpatialMetric] = useState("overall");
  const [activeSpatialOperations, setActiveSpatialOperations] = useState<SpatialOperationResult[]>([]);
  const [temporarySpatialLayers, setTemporarySpatialLayers] = useState<SpatialOperationResult[]>([]);
  const [analysisContext, setAnalysisContext] = useState<AnalysisContext>({
    region: null,
    grades: [],
    comparison_regions: [],
  });
  const [materials, setMaterials] = useState<ReportMaterial[]>([]);
  const [reportSetupOpen, setReportSetupOpen] = useState(false);
  const [reportSetupRegion, setReportSetupRegion] = useState<string | null>(null);
  const [reportOptions, setReportOptions] = useState<ReportOptions>({
    use_llm: true,
    use_judge: true,
    make_hwpx: true,
  });
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyEntries, setHistoryEntries] = useState<ConversationSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [conversationId, setConversationId] = useState(newConversationId);
  const [spatialWidth, setSpatialWidth] = useState(storedSpatialWidth);
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const streamEnd = useRef<HTMLDivElement | null>(null);
  const eventSources = useRef<EventSource[]>([]);
  const reportPollers = useRef<globalThis.Map<string, number>>(new globalThis.Map());
  const activeQueries = useRef<globalThis.Map<string, AbortController>>(new globalThis.Map());
  const conversationSaveActive = useRef(false);
  const pendingConversationSave = useRef<{
    id: string;
    payload: Parameters<typeof api.saveConversation>[1];
  } | null>(null);
  const resumeAttemptedForUser = useRef<string | null>(null);
  const previousRegion = useRef<string | null>(null);

  const notify = (
    message: string,
    tone: "success" | "error" | "info" = "info",
  ) => setToast({ message, tone });

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const loadRegions = async () => {
    try {
      const items = await api.regions();
      setRegions(items);
      const authenticated = api.authState();
      setAuthUser(authenticated);
      setAuthRequired(false);
      setLoadError("");
      if (!items.length) return;
      const savedRegion = authenticated
        ? readStorage(regionStorageKey(authenticated.id))
        : null;
      if (authenticated && !savedRegion) {
        setSido("");
        setDistrict("");
        return;
      }
      const [savedSido, ...savedDistrictParts] = savedRegion?.split(" ") || [];
      const savedDistrict = savedDistrictParts.join(" ");
      const initial = items.find((item) => (
        item.name === savedSido && item.districts.includes(savedDistrict)
      )) || items.find((item) => item.name === "부산광역시") || items[0];
      setSido(initial.name);
      setDistrict(
        initial.name === savedSido && initial.districts.includes(savedDistrict)
          ? savedDistrict
          : initial.districts.includes("수영구") ? "수영구" : initial.districts[0],
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setAuthRequired(true);
        return;
      }
      setLoadError(error instanceof Error ? error.message : "지역 정보를 불러오지 못했습니다.");
    }
  };

  useEffect(() => {
    loadRegions();
  }, []);

  useEffect(() => {
    const requireLogin = () => setAuthRequired(true);
    window.addEventListener("coastal:unauthorized", requireLogin);
    return () => window.removeEventListener("coastal:unauthorized", requireLogin);
  }, []);

  useEffect(() => {
    streamEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  useEffect(() => () => {
    eventSources.current.forEach((source) => source.close());
    reportPollers.current.forEach((timer) => window.clearTimeout(timer));
    reportPollers.current.clear();
  }, []);

  const selected = regions.find((item) => item.name === sido);
  const region = [sido, district].filter(Boolean).join(" ") || null;

  const queueConversationSave = (
    id: string,
    payload: Parameters<typeof api.saveConversation>[1],
  ) => {
    pendingConversationSave.current = { id, payload };
    if (conversationSaveActive.current) return;
    conversationSaveActive.current = true;

    void (async () => {
      try {
        while (pendingConversationSave.current) {
          const pending = pendingConversationSave.current;
          pendingConversationSave.current = null;
          try {
            await api.saveConversation(pending.id, pending.payload);
            setLoadError((current) => (
              current.startsWith("대화 자동 저장 실패:") ? "" : current
            ));
          } catch (error) {
            const message = `대화 자동 저장 실패: ${error instanceof Error ? error.message : "알 수 없는 오류"}`;
            setLoadError(message);
            notify(message, "error");
          }
        }
      } finally {
        conversationSaveActive.current = false;
      }
    })();
  };

  useEffect(() => {
    setAnalysisContext((current) => ({
      ...current,
      region,
      selection: current.region && current.region !== region ? null : current.selection,
    }));
    if (authUser && region) writeStorage(regionStorageKey(authUser.id), region);
  }, [authUser, region]);

  useEffect(() => {
    const changed = previousRegion.current !== null && previousRegion.current !== region;
    previousRegion.current = region;
    if (!changed || !spatialOpen) return;
    setSpatialRegion(region);
    setSpatialContext(region ? `${region} 공간자료` : "전국 공간자료");
    setSpatialGrades([]);
    setSpatialFocusNames([]);
    setSpatialMetric("overall");
    setActiveSpatialOperations([]);
  }, [region, spatialOpen]);

  useEffect(() => {
    writeStorage(SPATIAL_WIDTH_STORAGE_KEY, String(spatialWidth));
  }, [spatialWidth]);

  useEffect(() => {
    const resize = () => {
      const nextViewportWidth = window.innerWidth;
      setViewportWidth(nextViewportWidth);
      setSpatialWidth((width) => clampSpatialWidth(width, nextViewportWidth));
    };
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  useEffect(() => {
    const savedMessages = messages.filter((message) => message.kind !== "loading");
    const firstQuestion = savedMessages.find((message) => message.role === "user" && message.text)?.text;
    if (!firstQuestion) return;
    if (authUser) writeStorage(conversationStorageKey(authUser.id), conversationId);
    const timer = window.setTimeout(() => {
      queueConversationSave(conversationId, {
        title: conversationTitle(displayRegionText(firstQuestion, region ? [region] : [])),
        region,
        messages: savedMessages,
        analysis_context: analysisContext,
        materials,
      });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [analysisContext, authUser, conversationId, materials, messages, region]);

  const patchMessage = (id: string, patch: Partial<ChatMessage>) => {
    setMessages((current) => current.map((message) => (
      message.id === id ? { ...message, ...patch } : message
    )));
  };

  const openSpatial = (
    targetRegion: string | null,
    context = "",
    grades: string[] = [],
    focusNames: string[] = [],
    metricId = "overall",
  ) => {
    setSpatialRegion(targetRegion);
    setSpatialContext(context);
    setSpatialGrades(grades);
    setSpatialFocusNames(focusNames);
    setSpatialMetric(metricId);
    setSpatialOpen(true);
  };

  const openHistory = async () => {
    setHistoryOpen(true);
    setHistoryLoading(true);
    setHistoryError("");
    try {
      setHistoryEntries(await api.conversations());
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : "작업 이력을 불러오지 못했습니다.");
    } finally {
      setHistoryLoading(false);
    }
  };

  const deleteConversation = async (id: string) => {
    setHistoryError("");
    try {
      await api.deleteConversation(id);
      setHistoryEntries((current) => current.filter((entry) => entry.id !== id));
      if (id === conversationId) {
        if (authUser) removeStorage(conversationStorageKey(authUser.id));
        setConversationId(newConversationId());
        setMessages([]);
        setMaterials([]);
        setAnalysisContext({ region, grades: [], comparison_regions: [] });
        setSpatialOpen(false);
      }
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : "대화 세션을 삭제하지 못했습니다.");
      throw error;
    }
  };

  const refreshReport = async (jobId: string, id: string) => {
    const report = await api.report(jobId);
    let preview = "";
    let provenance: ProvenanceEntry[] = [];
    if (report.status === "completed") {
      const [previewResult, provenanceResult] = await Promise.all([
        api.preview(jobId).catch(() => ({ markdown: "" })),
        api.provenance(jobId).catch(() => []),
      ]);
      preview = previewResult.markdown;
      provenance = provenanceResult;
    }
    patchMessage(id, { kind: "report", report, preview, provenance });
    return report;
  };

  const subscribeReport = (jobId: string, id: string) => {
    const source = new EventSource(`/api/reports/${jobId}/events`);
    eventSources.current.push(source);
    const stopPolling = () => {
      const timer = reportPollers.current.get(jobId);
      if (timer !== undefined) window.clearTimeout(timer);
      reportPollers.current.delete(jobId);
    };
    const poll = async () => {
      try {
        const report = await refreshReport(jobId, id);
        if (["completed", "failed", "cancelled"].includes(report.status)) {
          stopPolling();
          source.close();
          return;
        }
      } catch {
        // Keep the report card recoverable through the next bounded poll.
      }
      const timer = window.setTimeout(poll, 3000);
      reportPollers.current.set(jobId, timer);
    };
    const startPolling = () => {
      if (reportPollers.current.has(jobId)) return;
      void poll();
    };
    const finish = (
      message: string,
      tone: "success" | "error" | "info",
    ) => {
      stopPolling();
      void refreshReport(jobId, id);
      source.close();
      notify(message, tone);
    };
    source.addEventListener("stage_completed", () => void refreshReport(jobId, id));
    source.addEventListener(
      "job_completed",
      () => finish("보고서 작성이 완료되었습니다.", "success"),
    );
    source.addEventListener(
      "job_failed",
      () => finish("보고서 작업이 실패했습니다.", "error"),
    );
    source.addEventListener(
      "job_cancelled",
      () => finish("보고서 작업이 취소되었습니다.", "info"),
    );
    source.addEventListener("error", startPolling);
  };

  const restoreConversation = async (id: string, automatic = false) => {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const session: ConversationSession = await api.conversation(id);
      const restoredMessages = session.messages.filter(isChatMessage);
      setConversationId(session.id);
      setMessages(restoredMessages);
      setAnalysisContext(session.analysis_context);
      setMaterials(session.materials.filter((material) => material.grounded === true));
      if (session.region) {
        const [restoredSido, ...districtParts] = session.region.split(" ");
        setSido(restoredSido);
        setDistrict(districtParts.join(" "));
      } else {
        setSido("");
        setDistrict("");
      }
      setSpatialOpen(false);
      setHistoryOpen(false);

      for (const message of restoredMessages) {
        if (message.kind !== "report" || !message.report?.job_id) continue;
        try {
          const report = await refreshReport(message.report.job_id, message.id);
          if (["queued", "running", "cancel_requested"].includes(report.status)) {
            subscribeReport(report.job_id, message.id);
          }
        } catch {
          patchMessage(message.id, {
            kind: "error",
            text: "저장된 보고서 작업의 현재 상태를 불러오지 못했습니다.",
          });
        }
      }
    } catch (error) {
      if (automatic && authUser) {
        removeStorage(conversationStorageKey(authUser.id));
        setLoadError(`마지막 대화를 불러오지 못했습니다: ${error instanceof Error ? error.message : "알 수 없는 오류"}`);
      } else {
        setHistoryError(error instanceof Error ? error.message : "대화 세션을 불러오지 못했습니다.");
      }
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    if (!authUser || resumeAttemptedForUser.current === authUser.id) return;
    resumeAttemptedForUser.current = authUser.id;
    const savedConversationId = readStorage(conversationStorageKey(authUser.id));
    if (savedConversationId) void restoreConversation(savedConversationId, true);
  }, [authUser?.id]);

  const cancelReport = async (message: ChatMessage) => {
    if (!message.report) return;
    await api.cancelReport(message.report.job_id);
    await refreshReport(message.report.job_id, message.id);
  };

  const retryReport = async (message: ChatMessage) => {
    if (!message.report) return;
    const retried = await api.retryReport(message.report.job_id);
    await refreshReport(retried.job_id, message.id);
    subscribeReport(retried.job_id, message.id);
  };

  const startReport = async (
    reportRegion: string | null,
    options: ReportOptions = reportOptions,
  ) => {
    const id = messageId();
    setMessages((current) => [...current, {
      id,
      role: "assistant",
      kind: "loading",
      text: "보고서 작업을 준비하고 있습니다.",
      region: reportRegion,
    }]);
    try {
      const created = await api.createReport({
        region: reportRegion,
        ...options,
        ...(materials.length ? { materials } : {}),
      });
      await refreshReport(created.job_id, id);
      subscribeReport(created.job_id, id);
    } catch (error) {
      patchMessage(id, {
        kind: "error",
        text: error instanceof Error ? error.message : "보고서 작업을 시작하지 못했습니다.",
      });
    }
  };

  const askData = async (
    question: string,
    queryRegion: string | null,
    history: ChatHistoryItem[],
    queryContext: AnalysisContext,
  ) => {
    const id = messageId();
    const queryRequest = {
      question,
      region: queryRegion,
      history,
      context: queryContext,
    };
    setMessages((current) => [...current, {
      id,
      role: "assistant",
      kind: "loading",
      text: "DuckDB에서 근거 데이터를 조회하고 있습니다.",
      analysisContext: queryContext,
      startedAt: Date.now(),
      queryRequest,
    }]);
    await executeDataQuery(id, queryRequest);
  };

  const executeDataQuery = async (
    id: string,
    queryRequest: NonNullable<ChatMessage["queryRequest"]>,
  ) => {
    const controller = new AbortController();
    activeQueries.current.set(id, controller);
    patchMessage(id, {
      kind: "loading",
      text: "DuckDB에서 근거 데이터를 조회하고 있습니다.",
      startedAt: Date.now(),
      queryRequest,
    });
    const spatialIntent = spatialOperationFromPrompt(queryRequest.question);
    const primarySpatialRequest: Promise<SpatialOperationResult | null> = (() => {
      if (!queryRequest.region || !spatialIntent) return Promise.resolve(null);
      if (spatialIntent.kind === "filter") {
        return api.spatialFilter({
          region: queryRequest.region,
          question: queryRequest.question,
        });
      }
      if (spatialIntent.kind === "neighborhood") {
        return api.spatialNeighborhood({
          region: queryRequest.region,
          ftr_id: spatialIntent.ftrId,
          distance_m: spatialIntent.distanceM,
          metric: spatialMetric,
          grades: queryRequest.context.grades,
        });
      }
      return api.spatialHotspots({
        region: queryRequest.region,
        metric: spatialMetric,
        grades: queryRequest.context.grades.length ? queryRequest.context.grades : ["4", "5"],
        min_cluster_size: 2,
      });
    })().catch(() => null);
    try {
      const query = await api.query({
        question: queryRequest.question,
        region: queryRequest.region,
        scope: queryRequest.region ? "selected_region" : "national",
        history: queryRequest.history,
        analysis_context: queryContextPayload(queryRequest.context),
      }, {
        signal: controller.signal,
        onStatus: (message) => patchMessage(id, { text: message }),
      });
      const spatialRequests: Array<Promise<SpatialOperationResult>> = [];
      const primarySpatialOperation = await primarySpatialRequest;
      if (primarySpatialOperation) spatialRequests.push(Promise.resolve(primarySpatialOperation));
      if (
        queryRequest.region
        && query.queries.length
        && (spatialIntent || isSpatialDisplayRequest(queryRequest.question))
      ) {
        spatialRequests.push(api.spatialQueryScope({
          region: queryRequest.region,
          queries: query.queries,
        }));
      }
      const spatialSettled = await Promise.allSettled(spatialRequests);
      const spatialOperations = spatialSettled.flatMap((item) => (
        item.status === "fulfilled" ? [item.value] : []
      ));
      patchMessage(id, { kind: "query", query, spatialOperations });
      const mapSelection = queryMapSelection(query, queryRequest.context.grades);
      const shouldSyncMap = spatialOpen
        || isSpatialDisplayRequest(queryRequest.question)
        || spatialOperations.length > 0;
      if (shouldSyncMap) {
        const operationState = primarySpatialOperation
          ? spatialStateFromOperation(primarySpatialOperation)
          : null;
        setSpatialRegion(operationState?.region || query.region || queryRequest.region);
        setSpatialContext(operationState?.context || queryRequest.question);
        setSpatialGrades(operationState?.grades.length ? operationState.grades : mapSelection.grades);
        setSpatialFocusNames(operationState?.focusNames || mapSelection.focusNames);
        setSpatialMetric(operationState?.metric || "overall");
        setActiveSpatialOperations(spatialOperations);
        setSpatialOpen(true);
      }
    } catch (error) {
      const aborted = error instanceof DOMException && error.name === "AbortError";
      const fallbackOperation = aborted ? null : await primarySpatialRequest;
      if (fallbackOperation) {
        const query = {
          question: queryRequest.question,
          region: queryRequest.region,
          answer: fallbackOperation.summary,
          queries: fallbackOperation.evidence.queries,
          results: fallbackOperation.report_material.results,
          grounded: true,
        };
        patchMessage(id, { kind: "query", query, spatialOperations: [fallbackOperation] });
        const operationState = spatialStateFromOperation(fallbackOperation);
        setSpatialRegion(operationState.region);
        setSpatialContext(operationState.context);
        setSpatialGrades(operationState.grades);
        setSpatialFocusNames(operationState.focusNames);
        setSpatialMetric(operationState.metric);
        setActiveSpatialOperations([fallbackOperation]);
        setSpatialOpen(true);
        return;
      }
      patchMessage(id, {
        kind: "error",
        text: aborted
          ? "질의를 중단했습니다."
          : error instanceof Error ? error.message : "데이터 질의에 실패했습니다.",
      });
      if (!aborted) notify(
        error instanceof Error ? error.message : "데이터 질의에 실패했습니다.",
        "error",
      );
    } finally {
      activeQueries.current.delete(id);
    }
  };

  const cancelDataQuery = (message: ChatMessage) => {
    activeQueries.current.get(message.id)?.abort();
  };

  const retryDataQuery = async (message: ChatMessage) => {
    if (!message.queryRequest) return;
    await executeDataQuery(message.id, message.queryRequest);
  };

  const copyQuery = async (message: ChatMessage) => {
    if (!message.query) return;
    const sql = message.query.queries.length
      ? `\n\nSQL\n${message.query.queries.join("\n\n")}`
      : "";
    try {
      await navigator.clipboard.writeText(`${message.query.answer}${sql}`);
      notify("답변과 SQL을 복사했습니다.", "success");
    } catch {
      notify("클립보드에 복사하지 못했습니다.", "error");
    }
  };

  const compareData = async (question: string, comparisonRegions: string[]) => {
    const id = messageId();
    setMessages((current) => [...current, {
      id,
      role: "assistant",
      kind: "loading",
      text: "두 지역을 동일한 DuckDB 지표로 비교하고 있습니다.",
    }]);
    try {
      const comparison = await api.compare(comparisonRegions);
      patchMessage(id, { kind: "comparison", comparison, text: question });
    } catch (error) {
      patchMessage(id, {
        kind: "error",
        text: error instanceof Error ? error.message : "지역 비교에 실패했습니다.",
      });
    }
  };

  const toggleMaterial = (message: ChatMessage) => {
    if (!message.query && !message.comparison && !message.spatial) return;
    if (message.query && !message.query.grounded) return;
    setMaterials((current) => {
      if (current.some((item) => item.source_id === message.id)) {
        return current.filter((item) => item.source_id !== message.id);
      }
      if (message.comparison) {
        return [...current, {
          source_id: message.id,
          question: message.text || "지역 비교 분석",
          answer: message.comparison.answer,
          region: message.comparison.regions.join(" ↔ "),
          queries: message.comparison.queries,
          results: message.comparison.results,
          grounded: true,
        }];
      }
      if (message.spatial) {
        return [...current, {
          source_id: message.id,
          ...message.spatial.report_material,
        }];
      }
      return [...current, {
        source_id: message.id,
        question: message.query!.question,
        answer: message.query!.answer,
        region: message.query!.region,
        queries: message.query!.queries,
        results: message.query!.results,
        grounded: true,
        scope: message.query!.scope,
      }];
    });
  };

  const addSpatialMaterial = (material: ReportMaterial) => {
    setMaterials((current) => [
      ...current.filter((item) => item.source_id !== material.source_id),
      material,
    ]);
  };

  const keepTemporarySpatialLayer = (layer: SpatialOperationResult) => {
    setTemporarySpatialLayers((current) => upsertTemporaryLayer(current, layer));
    notify(`${layer.name} 레이어를 임시 보관했습니다.`, "success");
  };

  const removeTemporarySpatialLayer = (operationId: string) => {
    setTemporarySpatialLayers((current) => current.filter((item) => item.operation_id !== operationId));
    setActiveSpatialOperations((current) => current.filter((item) => item.operation_id !== operationId));
  };

  const receiveSpatialOperation = (operation: SpatialOperationResult) => {
    const state = spatialStateFromOperation(operation);
    setActiveSpatialOperations([operation]);
    setSpatialRegion(state.region);
    setSpatialContext(state.context);
    setSpatialMetric(state.metric);
    setSpatialGrades(state.grades);
    setSpatialFocusNames(state.focusNames);
    setSpatialOpen(true);
  };

  const toggleMcpMaterial = (material: ReportMaterial) => {
    setMaterials((current) => (
      current.some((item) => item.source_id === material.source_id)
        ? current.filter((item) => item.source_id !== material.source_id)
        : [...current, material]
    ));
  };

  const shareSpatialSelection = (analysis: SpatialSelectionAnalysis) => {
    const id = `selection:${analysis.selection_id}`;
    setAnalysisContext((current) => ({
      ...current,
      region: analysis.region,
      selection: {
        id: analysis.selection_id,
        metric: analysis.metric.id,
        grades: analysis.grades || [],
        geometry: analysis.geometry,
      },
    }));
    setMessages((current) => [
      ...current.filter((message) => message.id !== id),
      {
        id,
        role: "assistant",
        kind: "spatial",
        text: "사용자 지정 영역 통계와 공간 중첩 분석",
        spatial: analysis,
        region: analysis.region,
      },
    ]);
  };

  const removeSpatialMaterial = (sourceId: string) => {
    setMaterials((current) => current.filter((item) => item.source_id !== sourceId));
  };

  const reviseReport = async (
    reportMessage: ChatMessage,
    section: string,
    instruction: string,
  ) => {
    if (!reportMessage.report) return;
    const id = messageId();
    setMessages((current) => [...current, {
      id,
      role: "assistant",
      kind: "loading",
      text: `${section} 섹션을 근거 수치와 대조하며 수정하고 있습니다.`,
    }]);
    try {
      const revision = await api.revise(reportMessage.report.job_id, { section, instruction });
      if (!("revision" in revision)) {
        const report = await refreshReport(reportMessage.report.job_id, reportMessage.id);
        if (["queued", "running"].includes(report.status)) {
          subscribeReport(report.job_id, reportMessage.id);
        }
        patchMessage(id, {
          kind: "text",
          text: "보고서 수정 작업을 큐에 등록했습니다.",
        });
        return;
      }
      const report = await api.report(reportMessage.report.job_id);
      const preview = (await api.preview(reportMessage.report.job_id)).markdown;
      const provenance = await api.provenance(reportMessage.report.job_id).catch(() => []);
      patchMessage(reportMessage.id, { report, preview, provenance });
      patchMessage(id, {
        kind: "text",
        text: `${revision.section} 수정본을 저장했습니다. 원본은 그대로 보존됩니다.`,
      });
    } catch (error) {
      patchMessage(id, {
        kind: "error",
        text: error instanceof Error ? error.message : "보고서 부분 수정에 실패했습니다.",
      });
    }
  };

  const saveDirectReport = async (reportMessage: ChatMessage, markdown: string) => {
    if (!reportMessage.report) return;
    const jobId = reportMessage.report.job_id;
    const saved = await api.saveReportContent(jobId, markdown);
    if (!("revision" in saved)) {
      const report = await refreshReport(jobId, reportMessage.id);
      if (["queued", "running"].includes(report.status)) {
        subscribeReport(jobId, reportMessage.id);
      }
      return;
    }
    const [report, previewResult, provenance] = await Promise.all([
      api.report(jobId),
      api.preview(jobId),
      api.provenance(jobId).catch(() => []),
    ]);
    patchMessage(reportMessage.id, {
      report,
      preview: previewResult.markdown,
      provenance,
    });
  };

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    const prompt = input.trim();
    if (!prompt || sending) return;
    const history = messages.flatMap<ChatHistoryItem>((message) => {
      if (message.role === "user" && message.text) {
        return [{ role: "user", content: message.text }];
      }
      if (message.role === "assistant" && message.kind === "query" && message.query?.answer) {
        return [{ role: "assistant", content: message.query.answer }];
      }
      if (message.role === "assistant" && message.kind === "text" && message.text) {
        return [{ role: "assistant", content: message.text }];
      }
      return [];
    }).map((item) => ({ ...item, content: item.content.slice(0, 2000) })).slice(-6);
    const resolvedRegion = resolveRegionFromPrompt(prompt, regions, sido);
    const comparisonRequest = /(비교|대비)/.test(prompt);
    const mentionedRegions = resolveRegionsFromPrompt(prompt, regions);
    const comparisonTargets = comparisonRequest
      ? mentionedRegions.length >= 2
        ? mentionedRegions.map((item) => item.label)
        : mentionedRegions.length === 1 && mentionedRegions[0].label !== region
          ? [region, mentionedRegions[0].label].filter((item): item is string => Boolean(item))
          : []
      : [];
    const changesPrimaryRegion = Boolean(resolvedRegion && !comparisonRequest);
    const targetRegion = changesPrimaryRegion ? resolvedRegion!.label : region;
    const regionChanged = Boolean(changesPrimaryRegion && resolvedRegion!.label !== region);
    const nextComparisonRegions = comparisonTargets.length >= 2
      ? comparisonTargets.filter((item) => item !== targetRegion)
      : changesPrimaryRegion
        ? []
        : analysisContext.comparison_regions;
    const nextAnalysisContext: AnalysisContext = {
      region: targetRegion,
      grades: gradesFromPrompt(prompt, analysisContext.grades),
      comparison_regions: nextComparisonRegions,
      selection: changesPrimaryRegion ? null : analysisContext.selection,
    };
    const latestReport = [...messages].reverse().find((message) => (
      message.kind === "report" && message.report?.status === "completed" && message.preview
    ));
    const revisionSection = latestReport
      ? resolveRevisionSection(prompt, latestReport.preview || "")
      : null;
    setSending(true);
    setInput("");
    setMessages((current) => [...current, {
      id: messageId(),
      role: "user",
      kind: "text",
      text: prompt,
    }]);
    setAnalysisContext(nextAnalysisContext);
    if (changesPrimaryRegion && resolvedRegion) {
      setSido(resolvedRegion.sido);
      setDistrict(resolvedRegion.district);
      if (regionChanged) {
        setMessages((current) => [...current, {
          id: messageId(),
          role: "assistant",
          kind: "text",
          text: `분석 지역을 ${resolvedRegion.label}로 변경했습니다.`,
        }]);
      }
    }
    if (latestReport && revisionSection) {
      await reviseReport(latestReport, revisionSection, prompt);
    } else if (latestReport && isRevisionRequest(prompt)) {
      setMessages((current) => [...current, {
        id: messageId(),
        role: "assistant",
        kind: "error",
        text: "수정할 섹션명을 찾지 못했습니다. 보고서의 장 제목을 포함해 요청해 주세요.",
      }]);
    } else if (isReportRequest(prompt)) {
      if (isExplicitReportCommand(prompt)) {
        await startReport(targetRegion);
      } else {
        setReportSetupRegion(targetRegion);
        setReportSetupOpen(true);
      }
    } else if (comparisonRequest && comparisonTargets.length >= 2) {
      await compareData(prompt, comparisonTargets);
    } else if (resolvedRegion && isRegionSelectionRequest(prompt)) {
      if (!regionChanged) {
        setMessages((current) => [...current, {
          id: messageId(),
          role: "assistant",
          kind: "text",
          text: `현재 분석 지역이 이미 ${resolvedRegion.label}로 설정되어 있습니다.`,
        }]);
      }
    } else if (prompt.startsWith("/공간분석") || prompt.startsWith("/공간 작업실")) {
      setSpatialContext("선택 지역 공간자료");
      setSpatialOpen(true);
      setMessages((current) => [...current, {
        id: messageId(),
        role: "assistant",
        kind: "text",
        text: "선택 지역의 GPKG 공간분석을 열었습니다.",
      }]);
    } else {
      const metricDefinition = metricDefinitionFromPrompt(prompt);
      if (metricDefinition === "ambiguous") {
        setMetricClarification({
          question: prompt,
          region: targetRegion,
          history,
          context: nextAnalysisContext,
        });
        setSending(false);
        return;
      }
      const resolvedContext: AnalysisContext = metricDefinition
        ? { ...nextAnalysisContext, metric_definition: metricDefinition }
        : nextAnalysisContext;
      setAnalysisContext(resolvedContext);
      await askData(prompt, targetRegion, history, resolvedContext);
    }
    setSending(false);
  };

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  const changeSido = (value: string) => {
    setSido(value);
    setDistrict("");
  };

  const resolveMetricClarification = async (
    metricDefinition: "high_risk_ratio" | "high_risk_share",
  ) => {
    const pending = metricClarification;
    if (!pending) return;
    const context = { ...pending.context, metric_definition: metricDefinition };
    setMetricClarification(null);
    setAnalysisContext(context);
    setSending(true);
    await askData(pending.question, pending.region, pending.history, context);
    setSending(false);
  };

  const startSpatialResize = (event: ReactMouseEvent<HTMLElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = spatialWidth;
    const move = (moveEvent: MouseEvent) => {
      setSpatialWidth(clampSpatialWidth(
        startWidth + startX - moveEvent.clientX,
        window.innerWidth,
      ));
    };
    const stop = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", stop);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);
  };

  const handleAuthenticated = async (user: AuthUser) => {
    setAuthUser(user);
    await loadRegions();
  };

  const chatDensity = spatialOpen
    ? chatDensityForLayout(viewportWidth, spatialWidth)
    : "full";

  if (authRequired && !authUser) {
    return <LoginScreen onAuthenticated={async (user) => {
      await handleAuthenticated(user);
    }} />;
  }

  return (
    <div
      className="chat-app"
      style={{
        "--spatial-width": `${spatialWidth}px`,
      } as CSSProperties}
    >
      <aside className={`chat-sidebar ${sidebarOpen ? "mobile-open" : ""}`} aria-label="주요 탐색">
        {sidebarOpen && <button
          className="sidebar-close"
          type="button"
          aria-label="탐색 닫기"
          onClick={() => setSidebarOpen(false)}
        >닫기</button>}
        <a className="product-mark" href="/" aria-label="연안재해 에이전트 새로고침">
          <img src={new URL("./assets/coastal-wordmark.svg", import.meta.url).href} alt="Coastal" />
        </a>
        <button className="new-chat" onClick={() => {
          setConversationId(newConversationId());
          setMessages([]);
          setMaterials([]);
          setAnalysisContext({ region, grades: [], comparison_regions: [] });
          setSidebarOpen(false);
        }}>
          <Plus size={17} /> 새 대화
        </button>
        <div className="sidebar-section">
          <small>현재 대화</small>
          <div className="thread-item active"><MessageSquare size={16} /> 연안재해 에이전트</div>
          <button className="spatial-launch" aria-label="공간분석 열기" onClick={() => {
            openSpatial(region);
            setSidebarOpen(false);
          }}>
            <Map size={16} /><span><strong>공간분석</strong><small>GPKG 실시간 조회</small></span>
          </button>
          <button className="history-launch" aria-label="분석 작업 이력 열기" onClick={() => {
            openHistory();
            setSidebarOpen(false);
          }}>
            <History size={16} /><span><strong>분석 작업 이력</strong><small>질의·분석·보고서 기록</small></span>
          </button>
          <button className="history-launch" aria-label="사용 방법 열기" onClick={() => {
            setHelpOpen(true);
            setSidebarOpen(false);
          }}>
            <CircleHelp size={16} /><span><strong>사용 방법</strong><small>질문·공간분석·보고서 안내</small></span>
          </button>
        </div>
        <div className="source-card">
          <div><Database size={16} /><strong>원자료 연결됨</strong></div>
          <p>DuckDB 분석 테이블</p>
          <p>GPKG 공간 레이어</p>
        </div>
        <div className="sidebar-foot"><ShieldCheck size={15} /> 수치 근거 자동 대조</div>
      </aside>
      {sidebarOpen && <button
        className="sidebar-scrim"
        type="button"
        aria-label="탐색 메뉴 배경 닫기"
        onClick={() => setSidebarOpen(false)}
      />}

      <main
        className={`chat-main ${spatialOpen ? "spatial-active" : ""} chat-density-${chatDensity}`}
        data-chat-density={chatDensity}
      >
        <header className="chat-header">
          <button
            className="mobile-menu"
            aria-label={sidebarOpen ? "메뉴 닫기" : "메뉴 열기"}
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen((current) => !current)}
          >
            {sidebarOpen ? "닫기" : "메뉴"}
          </button>
          <div className="chat-title">
            <div><h1>연안재해 에이전트</h1></div>
          </div>
          <button className="header-map-button header-control" aria-label="공간분석 표시" onClick={() => openSpatial(region)}>
            <Layers3 size={15} /> 공간분석
          </button>
          <div className={`region-picker header-control ${sido ? "equal-columns" : "national"}`}>
            <label>
              <span className="sr-only">시·도</span>
              <select className="region-select" value={sido} onChange={(event) => changeSido(event.target.value)}>
                <option value="">전국</option>
                {regions.map((item) => <option key={item.name}>{item.name}</option>)}
              </select>
              <ChevronDown size={13} />
            </label>
            {sido && <label>
              <span className="sr-only">시·군·구</span>
              <select className="region-select" value={district} onChange={(event) => setDistrict(event.target.value)}>
                <option value="">전체</option>
                {(selected?.districts || []).map((name) => <option value={name} key={name}>{displayRegionName(name)}</option>)}
              </select>
              <ChevronDown size={13} />
            </label>}
          </div>
          {authUser && <div className="account-menu">
            <button className="account-summary header-control" type="button" aria-label="계정 메뉴 열기" onClick={() => setAccountOpen((current) => !current)}>
              <span>{authUser.username.slice(0, 1).toUpperCase()}</span>
              <div><strong>{authUser.username}</strong><small>{authUser.role === "admin" ? "관리자" : "사용자"}</small></div>
              <ChevronDown size={13} />
            </button>
            {accountOpen && <div className="account-popover">
              <button type="button" onClick={() => {
                setAccountSettingsOpen(true);
                setAccountOpen(false);
              }}>계정 설정</button>
              {authUser.role === "admin" && <button type="button" onClick={() => {
                setAdminOpen(true);
                setAccountOpen(false);
              }}>사용자 관리</button>}
              <button type="button" onClick={async () => {
                await api.logout();
                setAccountOpen(false);
                setAuthUser(null);
                setAuthRequired(true);
              }}>로그아웃</button>
            </div>}
          </div>}
        </header>

        <div className="chat-minimized-summary" aria-hidden="true">
          <strong>대화</strong>
          <span>{messages.length}</span>
          <small>공간분석 확장</small>
        </div>

        <section className="chat-scroll" aria-label="대화 내용">
          <div className="chat-column">
            {loadError && <div className="notice error"><CircleAlert size={16} /> {loadError}</div>}
            {messages.length === 0 && <Welcome region={region ? displayRegionName(region) : null} onSelect={setInput} />}
            {messages.map((message) => (
              <ChatTurn
                key={message.id}
                message={message}
                region={message.region ?? region}
                materialSelected={materials.some((item) => item.source_id === message.id)}
                selectedMaterialIds={materials.map((item) => item.source_id)}
                onToggleMaterial={() => toggleMaterial(message)}
                onToggleMcpMaterial={toggleMcpMaterial}
                onOpenMap={openSpatial}
                onSaveReport={(markdown) => saveDirectReport(message, markdown)}
                onCancelReport={() => cancelReport(message)}
                onRetryReport={() => retryReport(message)}
                onCancelQuery={() => cancelDataQuery(message)}
                onRetryQuery={() => retryDataQuery(message)}
                onCopyQuery={() => copyQuery(message)}
                onOpenSpatialOperation={(operation) => {
                  setActiveSpatialOperations([operation]);
                  setSpatialRegion(operation.region);
                  setSpatialOpen(true);
                }}
                onKeepSpatialLayer={keepTemporarySpatialLayer}
              />
            ))}
            <div ref={streamEnd} />
          </div>
        </section>

        <div className={`composer-dock ${spatialOpen ? "spatial-active" : ""}`}>
          <div className="chat-column">
            <div className="command-strip">
              <span>빠른 명령</span>
              {STARTERS.map((starter) => (
                <button key={starter} onClick={() => setInput(starter)}>{starter}</button>
              ))}
            </div>
            {(analysisContext.grades.length > 0
              || analysisContext.comparison_regions.length > 0
              || materials.length > 0) && <div className="analysis-memory">
              <span><Radar size={12} /> 분석 메모리</span>
              {analysisContext.grades.length > 0 && <b>{analysisContext.grades.join("·")}등급</b>}
              {analysisContext.comparison_regions.map((name) => <b key={name}>비교 · {displayRegionName(name)}</b>)}
              {materials.length > 0 && <button
                type="button"
                className="material-memory"
                aria-label="보고서 자료 바구니 열기"
                onClick={() => {
                  setReportSetupRegion(region);
                  setReportSetupOpen(true);
                }}
              ><BookMarked size={11} /> 보고서 자료 {materials.length}</button>}
            </div>}
            <form className="chat-composer" onSubmit={submit}>
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={onComposerKeyDown}
                placeholder="연안 데이터에 대해 질문하거나 명령어를 입력하세요"
                rows={1}
              />
              <div className="composer-line">
                <div className="composer-sources">
                  <span><Database size={13} /> DuckDB</span>
                  <span><Layers3 size={13} /> GPKG</span>
                  <span className="current-region">{region ? displayRegionName(region) : "전국"}</span>
                </div>
                <button className="send-button" aria-label="메시지 보내기" disabled={!input.trim() || sending}>
                  전송
                </button>
              </div>
            </form>
            <p className="composer-note">답변은 실제 조회 결과를 기반으로 하며, 중요한 수치는 원본 SQL과 함께 확인하세요.</p>
          </div>
        </div>
      </main>
      {spatialOpen && <>
        <div
          className="pane-resizer spatial-resizer"
          role="separator"
          aria-label="공간분석 너비 조절"
          aria-orientation="vertical"
          aria-valuemin={SPATIAL_MIN_WIDTH}
          aria-valuemax={spatialMaxWidth(window.innerWidth)}
          aria-valuenow={spatialWidth}
          tabIndex={0}
          onMouseDown={startSpatialResize}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") setSpatialWidth((width) => clampSpatialWidth(
              width - 16,
              window.innerWidth,
            ));
            if (event.key === "ArrowRight") setSpatialWidth((width) => clampSpatialWidth(
              width + 16,
              window.innerWidth,
            ));
          }}
        />
        <Suspense fallback={<div className="spatial-loading-shell">공간분석을 여는 중입니다.</div>}>
          <SpatialStudio
            region={spatialRegion || region}
            context={spatialContext}
            focusGrades={spatialGrades}
            focusNames={spatialFocusNames}
            focusMetric={spatialMetric}
            reportMaterialIds={materials.map((item) => item.source_id)}
            onClose={() => {
              setSpatialOpen(false);
              setSpatialRegion(null);
              setSpatialFocusNames([]);
            }}
            onAsk={(question) => setInput(question)}
            onShareSelection={shareSpatialSelection}
            onAddReportMaterial={addSpatialMaterial}
            onRemoveReportMaterial={removeSpatialMaterial}
            operationLayers={[
              ...temporarySpatialLayers,
              ...activeSpatialOperations.filter((item) => !temporarySpatialLayers.some(
                (saved) => saved.operation_id === item.operation_id,
              )),
            ]}
            temporaryLayerIds={temporarySpatialLayers.map((item) => item.operation_id)}
            onKeepOperationLayer={keepTemporarySpatialLayer}
            onRemoveOperationLayer={removeTemporarySpatialLayer}
            onSpatialOperation={receiveSpatialOperation}
            onRegionChange={(scenarioRegion) => {
              const [scenarioSido, ...scenarioDistrictParts] = scenarioRegion.split(" ");
              setSido(scenarioSido);
              setDistrict(scenarioDistrictParts.join(" "));
              setSpatialRegion(scenarioRegion);
              setAnalysisContext((current) => ({
                ...current,
                region: scenarioRegion,
                comparison_regions: [],
                selection: null,
              }));
            }}
          />
        </Suspense>
      </>}
      {historyOpen && <AnalysisHistoryPanel
        entries={historyEntries}
        loading={historyLoading}
        error={historyError}
        onClose={() => setHistoryOpen(false)}
        onRestore={restoreConversation}
        onDelete={deleteConversation}
      />}
      {helpOpen && <UsageGuideDialog onClose={() => setHelpOpen(false)} />}
      {metricClarification && <MetricClarificationDialog
        onClose={() => setMetricClarification(null)}
        onSelect={(metricDefinition) => void resolveMetricClarification(metricDefinition)}
      />}
      {adminOpen && <AdminUserPanel region={region} onClose={() => setAdminOpen(false)} />}
      {accountSettingsOpen && authUser && <AccountSettingsPanel
        user={authUser}
        onClose={() => setAccountSettingsOpen(false)}
        onNotify={notify}
      />}
      {reportSetupOpen && <ReportSetupDialog
        region={reportSetupRegion}
        materials={materials}
        options={reportOptions}
        onMaterialsChange={setMaterials}
        onOptionsChange={setReportOptions}
        onClose={() => setReportSetupOpen(false)}
        onGenerate={() => {
          setReportSetupOpen(false);
          startReport(reportSetupRegion, reportOptions);
        }}
      />}
      {authRequired && authUser && <LoginScreen reauth onAuthenticated={handleAuthenticated} />}
      {toast && <div className={`toast ${toast.tone}`} role="status" aria-live="polite">
        {toast.tone === "error" ? <CircleAlert size={17} /> : <Check size={17} />}
        <span>{toast.message}</span>
        <button type="button" aria-label="알림 닫기" onClick={() => setToast(null)}><X size={14} /></button>
      </div>}
    </div>
  );
}

function ReportSetupDialog({
  region,
  materials,
  options,
  onMaterialsChange,
  onOptionsChange,
  onClose,
  onGenerate,
}: {
  region: string | null;
  materials: ReportMaterial[];
  options: ReportOptions;
  onMaterialsChange: (materials: ReportMaterial[]) => void;
  onOptionsChange: (options: ReportOptions) => void;
  onClose: () => void;
  onGenerate: () => void;
}) {
  const dialogRef = useDialogKeyboard(onClose);
  const dialogDrag = useDraggableDialog(dialogRef);

  const move = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= materials.length) return;
    const next = [...materials];
    [next[index], next[target]] = [next[target], next[index]];
    onMaterialsChange(next);
  };
  const toggleOption = (key: keyof ReportOptions) => {
    onOptionsChange({ ...options, [key]: !options[key] });
  };

  return <div className="report-setup-overlay" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section
      ref={dialogRef}
      className={`report-setup-dialog${dialogDrag.dragging ? " is-dragging" : ""}`}
      style={{ transform: `translate3d(${dialogDrag.offset.x}px, ${dialogDrag.offset.y}px, 0)` }}
      role="dialog"
      aria-modal="true"
      aria-label="보고서 작성 설정"
    >
      <header onPointerDown={dialogDrag.start}>
        <div>
          <small>REPORT COMPOSER</small>
          <h2>보고서를 생성할까요?</h2>
          <p>{region ? displayRegionName(region) : "전국"} · 자료 {materials.length}건</p>
        </div>
        <button type="button" aria-label="보고서 작성 설정 닫기" onClick={onClose}><X size={17} /></button>
      </header>
      <div className="report-setup-content">
        <section className="report-material-basket" aria-label="보고서 자료 목록">
          <div className="report-setup-section-title">
            <strong>포함 자료</strong>
            <span>{materials.length}/10</span>
          </div>
          {materials.length === 0
            ? <p className="report-material-empty">별도로 담은 자료가 없습니다. 지역 전체 분석을 기준으로 작성합니다.</p>
            : materials.map((material, index) => <article key={material.source_id}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div><strong>{material.question}</strong><p>{material.answer}</p></div>
              <div className="report-material-actions">
                <button
                  type="button"
                  aria-label={`${material.question} 위로 이동`}
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                ><ArrowUp size={14} /></button>
                <button
                  type="button"
                  aria-label={`${material.question} 아래로 이동`}
                  disabled={index === materials.length - 1}
                  onClick={() => move(index, 1)}
                ><ChevronDown size={14} /></button>
                <button
                  type="button"
                  aria-label={`${material.question} 삭제`}
                  onClick={() => onMaterialsChange(materials.filter((_, itemIndex) => itemIndex !== index))}
                ><X size={14} /></button>
              </div>
            </article>)}
        </section>
        <fieldset className="report-options">
          <legend>작성 옵션</legend>
          <label>
            <input type="checkbox" checked={options.use_llm} onChange={() => toggleOption("use_llm")} />
            <span><strong>LLM 서술</strong><small>조회된 수치를 자연스러운 설명문으로 구성</small></span>
          </label>
          <label>
            <input type="checkbox" checked={options.use_judge} onChange={() => toggleOption("use_judge")} />
            <span><strong>수치 검증</strong><small>서술의 수치를 실제 분석 결과와 대조</small></span>
          </label>
          <label>
            <input aria-label="HWPX 생성" type="checkbox" checked={options.make_hwpx} onChange={() => toggleOption("make_hwpx")} />
            <span><strong>HWPX 생성</strong><small>Markdown과 함께 한글 문서 생성</small></span>
          </label>
        </fieldset>
      </div>
      <footer>
        <button type="button" onClick={onClose}>취소</button>
        <button type="button" className="primary" onClick={onGenerate}>보고서 생성</button>
      </footer>
    </section>
  </div>;
}

function LoginScreen({
  onAuthenticated,
  reauth = false,
}: {
  onAuthenticated: (user: AuthUser) => Promise<void>;
  reauth?: boolean;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const authenticated = await api.login(username, password);
      await onAuthenticated(authenticated.user);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "로그인에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  const form = <form onSubmit={submit}>
    <div className="login-kicker">{reauth ? "SESSION EXPIRED" : "SECURE WORKSPACE"}</div>
    <h2>{reauth ? "세션을 다시 연결해 주세요" : "관리자 로그인"}</h2>
    <p>{reauth
      ? "작성 중인 내용은 그대로 유지됩니다. 다시 로그인하면 현재 작업을 이어갈 수 있습니다."
      : "승인된 계정으로 연안재해 에이전트에 접속하세요."}</p>
    <label>
      <span>아이디</span>
      <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required />
    </label>
    <label>
      <span>비밀번호</span>
      <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
    </label>
    {error && <div className="login-error" role="alert">{error}</div>}
    <button type="submit" disabled={submitting}>{submitting ? "확인 중…" : reauth ? "다시 로그인" : "로그인"}</button>
    <small>{reauth
      ? "재인증하는 동안 현재 대화와 분석 화면은 닫히지 않습니다."
      : "접속 기록과 분석 작업은 계정별로 안전하게 분리·저장됩니다."}</small>
  </form>;

  if (reauth) {
    return <div className="reauth-overlay">
      <section className="login-panel reauth-dialog" role="dialog" aria-modal="true" aria-label="세션 재인증">
        {form}
      </section>
    </div>;
  }

  return <main className="login-shell">
    <section className="login-brand" aria-label="서비스 소개">
      <img src={new URL("./assets/coastal-wordmark.svg", import.meta.url).href} alt="Coastal" />
      <div>
        <p>COASTAL RISK INTELLIGENCE</p>
        <h1>데이터에 근거한<br />연안재해 의사결정</h1>
        <span>공간자료 조회부터 분석, 검증, 보고서 작성까지 하나의 작업 공간에서 수행합니다.</span>
      </div>
    </section>
    <section className="login-panel">
      {form}
    </section>
  </main>;
}

const AUDIT_ACTION_LABELS: Record<string, string> = {
  "auth.login.succeeded": "로그인 성공",
  "auth.login.failed": "로그인 실패",
  "auth.logout": "로그아웃",
  "auth.password.change": "비밀번호 변경",
  "admin.user.create": "사용자 생성",
  "admin.user.password.reset": "사용자 비밀번호 재설정",
  "admin.user.status.update": "사용자 상태 변경",
};

function auditActionLabel(action: string) {
  return AUDIT_ACTION_LABELS[action] || action;
}

function AccountSettingsPanel({
  user,
  onClose,
  onNotify,
}: {
  user: AuthUser;
  onClose: () => void;
  onNotify: (message: string, tone?: "success" | "error" | "info") => void;
}) {
  const [sessions, setSessions] = useState<UserSession[]>([]);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const dialogRef = useDialogKeyboard(onClose);

  useEffect(() => {
    api.sessions()
      .then(setSessions)
      .catch((caught) => setError(
        caught instanceof Error ? caught.message : "세션 목록을 불러오지 못했습니다.",
      ));
  }, []);

  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await api.changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      onNotify("비밀번호를 변경했습니다.", "success");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "비밀번호를 변경하지 못했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  const revoke = async (session: UserSession) => {
    setError("");
    try {
      await api.revokeSession(session.id);
      setSessions((current) => current.filter((item) => item.id !== session.id));
      onNotify("선택한 세션을 종료했습니다.", "success");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "세션을 종료하지 못했습니다.");
    }
  };

  return <div className="account-settings-overlay" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section ref={dialogRef} className="account-settings-dialog" role="dialog" aria-modal="true" aria-label="계정 설정">
      <header>
        <div><small>ACCOUNT SECURITY</small><h2>계정 설정</h2><p>{user.username}</p></div>
        <button type="button" onClick={onClose}>닫기</button>
      </header>
      <form onSubmit={changePassword}>
        <h3>비밀번호 변경</h3>
        <label><span>현재 비밀번호</span><input aria-label="현재 비밀번호" type="password" minLength={8} value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required /></label>
        <label><span>새 비밀번호</span><input aria-label="새 비밀번호" type="password" minLength={8} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required /></label>
        <button type="submit" disabled={submitting}>{submitting ? "변경 중" : "비밀번호 변경"}</button>
      </form>
      <section className="account-sessions" aria-label="로그인 세션">
        <h3>로그인 세션</h3>
        {sessions.map((session) => <article key={session.id}>
          <div>
            <strong>{session.created_ip || "내부 네트워크"} {session.current && <b>현재</b>}</strong>
            <small>{formatHistoryTime(session.created_at)} 접속 · {formatHistoryTime(session.expires_at)} 만료</small>
          </div>
          {!session.current && <button type="button" aria-label={`${session.created_ip || "알 수 없는 위치"} 세션 종료`} onClick={() => revoke(session)}>종료</button>}
        </article>)}
      </section>
      {error && <div className="admin-error" role="alert">{error}</div>}
    </section>
  </div>;
}

function MetricClarificationDialog({
  onClose,
  onSelect,
}: {
  onClose: () => void;
  onSelect: (metric: "high_risk_ratio" | "high_risk_share") => void;
}) {
  const dialogRef = useDialogKeyboard(onClose);
  return <div className="metric-overlay" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section ref={dialogRef} className="metric-clarification" role="dialog" aria-modal="true" aria-label="고위험 비율 기준 선택">
      <header><div><small>METRIC CHECK</small><h2>어떤 비율을 계산할까요?</h2></div><button type="button" onClick={onClose}>닫기</button></header>
      <p>두 지표는 분모가 달라 순위가 바뀔 수 있습니다. 분석 목적에 맞는 기준을 선택해 주세요.</p>
      <div className="metric-choice-grid">
        <button type="button" onClick={() => onSelect("high_risk_ratio")}>
          <span>권장</span><strong>읍면동 자체 대비 고위험 비율</strong>
          <small>해당 읍면동의 4·5등급 격자 ÷ 해당 읍면동 전체 격자</small>
          <code>단위 %</code>
        </button>
        <button type="button" onClick={() => onSelect("high_risk_share")}>
          <span>구성비</span><strong>지역 전체 고위험 격자 구성비</strong>
          <small>해당 읍면동의 4·5등급 격자 ÷ 상위 지역 전체 4·5등급 격자</small>
          <code>단위 %</code>
        </button>
      </div>
    </section>
  </div>;
}

function UsageGuideDialog({ onClose }: { onClose: () => void }) {
  const dialogRef = useDialogKeyboard(onClose);
  return <div className="metric-overlay" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section ref={dialogRef} className="metric-catalog usage-guide detailed" role="dialog" aria-modal="true" aria-label="연안재해 에이전트 사용 방법">
      <UsageGuideContent onClose={onClose} />
    </section>
  </div>;
}

function AdminUserPanel({ region, onClose }: { region: string | null; onClose: () => void }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [reportJobs, setReportJobs] = useState<AdminReportJob[]>([]);
  const [dataQuality, setDataQuality] = useState<DataQualityReport | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "user">("user");
  const [resetUserId, setResetUserId] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const dialogRef = useDialogKeyboard(onClose);

  const refreshAuditLogs = () => api.adminAuditLogs()
    .then(setAuditLogs)
    .catch(() => undefined);

  useEffect(() => {
    api.adminUsers()
      .then(setUsers)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "사용자 목록을 불러오지 못했습니다."))
      .finally(() => setLoading(false));
    void refreshAuditLogs();
    api.adminReportJobs().then(setReportJobs).catch(() => undefined);
    api.dataQuality(region).then(setDataQuality).catch(() => undefined);
  }, [region]);

  const createUser = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      const created = await api.createUser({ username, password, role });
      setUsers((current) => [...current, {
        ...created,
        is_active: true,
        created_at: new Date().toISOString(),
      }]);
      setUsername("");
      setPassword("");
      setRole("user");
      void refreshAuditLogs();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "계정을 추가하지 못했습니다.");
    }
  };

  const toggleUser = async (user: AdminUser) => {
    setError("");
    try {
      const updated = await api.setUserActive(user.id, !user.is_active);
      setUsers((current) => current.map((item) => item.id === user.id ? updated : item));
      void refreshAuditLogs();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "계정 상태를 변경하지 못했습니다.");
    }
  };

  const resetSelectedPassword = async (event: FormEvent) => {
    event.preventDefault();
    if (!resetUserId) return;
    setError("");
    try {
      await api.resetUserPassword(resetUserId, resetPassword);
      setResetUserId("");
      setResetPassword("");
      void refreshAuditLogs();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "비밀번호를 재설정하지 못했습니다.");
    }
  };

  const latestDataSource = dataQuality?.sources.reduce((latest, source) => (
    !latest || new Date(source.modified_at) > new Date(latest.modified_at) ? source : latest
  ), null as DataQualityReport["sources"][number] | null) || null;

  return <div className="admin-overlay" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section ref={dialogRef} className="admin-panel" role="dialog" aria-modal="true" aria-label="사용자 관리">
      <header><div><small>ACCESS CONTROL</small><h2>사용자 관리</h2></div><button type="button" onClick={onClose}>닫기</button></header>
      <form className="admin-create" onSubmit={createUser}>
        <label><span>새 사용자 아이디</span><input value={username} onChange={(event) => setUsername(event.target.value)} minLength={3} required /></label>
        <label><span>임시 비밀번호</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={8} required /></label>
        <label><span>권한</span><select value={role} onChange={(event) => setRole(event.target.value as "admin" | "user")}><option value="user">사용자</option><option value="admin">관리자</option></select></label>
        <button type="submit">계정 추가</button>
      </form>
      {error && <div className="admin-error" role="alert">{error}</div>}
      <div className="admin-users">
        {loading && <p>사용자 목록을 불러오는 중입니다.</p>}
        {!loading && users.map((user) => <article key={user.id}>
          <span className="admin-user-avatar">{user.username.slice(0, 1).toUpperCase()}</span>
          <div><strong>{user.username}</strong><small>{user.role === "admin" ? "관리자" : "사용자"}</small></div>
          <b className={`admin-user-status ${user.is_active ? "active" : "inactive"}`}>{user.is_active ? "활성" : "비활성"}</b>
          <button type="button" onClick={() => setResetUserId(user.id)}>비밀번호 재설정</button>
          <button type="button" aria-label={`${user.username} 계정 ${user.is_active ? "비활성화" : "활성화"}`} onClick={() => toggleUser(user)}>{user.is_active ? "비활성화" : "활성화"}</button>
        </article>)}
      </div>
      {resetUserId && <form className="admin-password-reset" onSubmit={resetSelectedPassword}>
        <label><span>새 임시 비밀번호</span><input type="password" minLength={8} value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} required /></label>
        <button type="submit">재설정 적용</button>
        <button type="button" onClick={() => setResetUserId("")}>취소</button>
      </form>}
      {dataQuality && <section className="admin-quality" aria-label="데이터 품질 진단">
        <header><div><small>DATA QUALITY</small><h3>데이터 품질 진단</h3></div><b>{dataQuality.dataset_version || "버전 미확인"}</b></header>
        <div className="quality-summary-grid">
          <article><span>조회 격자</span><strong>{dataQuality.row_count.toLocaleString()}</strong><small>개</small></article>
          <article><span>스키마</span><strong>{dataQuality.schema_column_count}</strong><small>개 컬럼</small></article>
          <article><span>범위 오류</span><strong>{dataQuality.summary.invalid_grade_cells.toLocaleString()}</strong><small>건</small></article>
          <article className="quality-source-update"><span>최근 자료 갱신</span><strong>{latestDataSource
            ? new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "numeric", day: "numeric" }).format(new Date(latestDataSource.modified_at))
            : "미확인"}</strong><small>{latestDataSource?.name || "원본 파일 정보 없음"}</small></article>
        </div>
        <div className="quality-missing-list">
          <h4>결측률 상위 항목</h4>
          {dataQuality.columns.filter((item) => item.missing_count > 0).sort((a, b) => b.missing_pct - a.missing_pct).slice(0, 6).map((item) => <div key={item.name}>
            <span>{item.name.replace("_원자료", "")}</span><i><b style={{ width: `${Math.min(100, item.missing_pct)}%` }} /></i><strong>{item.missing_pct}%</strong><small>{item.missing_count.toLocaleString()}건</small>
          </div>)}
          {dataQuality.columns.every((item) => item.missing_count === 0) && <p>확인한 핵심 컬럼에는 결측값이 없습니다.</p>}
        </div>
        <div className="quality-capabilities">
          {Object.entries(dataQuality.capabilities).map(([key, capability]) => <article className={capability.supported ? "ready" : "blocked"} key={key}>
            <span>{capability.supported ? "사용 가능" : "데이터 필요"}</span>
            <strong>{{ time_series: "시계열·버전 비교", spatial_impact: "공간 영향권 분석", scheduled_monitoring: "정기 모니터링" }[key] || key}</strong>
            <p>{capability.reason}</p>
          </article>)}
        </div>
      </section>}
      <section className="admin-jobs" aria-label="보고서 작업 현황">
        <header><div><small>REPORT QUEUE</small><h3>보고서 작업 현황</h3></div><b>최근 {reportJobs.length}건</b></header>
        {reportJobs.length === 0 && <p>표시할 보고서 작업이 없습니다.</p>}
        {reportJobs.map((job) => <article key={job.job_id}>
          <code>{job.job_id}</code>
          <div><strong>{job.username}</strong><small>{job.region ? displayRegionName(job.region) : "전국"}</small></div>
          <span>{job.stage || job.status} · {job.progress}/7</span>
        </article>)}
      </section>
      <section className="admin-audit" aria-label="접속 및 계정 변경 이력">
        <header><div><small>AUDIT TRAIL</small><h3>접속·변경 이력</h3></div><b>최근 {auditLogs.length}건</b></header>
        {auditLogs.length === 0 && <p>기록된 관리자 활동이 없습니다.</p>}
        {auditLogs.map((entry) => <article key={entry.id}>
          <span className={`audit-mark ${entry.action.endsWith("failed") ? "failed" : ""}`} />
          <div><strong>{auditActionLabel(entry.action)}</strong><small>{entry.ip_address || "내부 시스템"}</small></div>
          <time>{formatHistoryTime(entry.created_at)}</time>
        </article>)}
      </section>
    </section>
  </div>;
}

function AnalysisHistoryPanel({
  entries,
  loading,
  error,
  onClose,
  onRestore,
  onDelete,
}: {
  entries: ConversationSummary[];
  loading: boolean;
  error: string;
  onClose: () => void;
  onRestore: (id: string) => void;
  onDelete: (id: string) => Promise<void>;
}) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const dialogRef = useDialogKeyboard(onClose);

  const handleDelete = async (id: string) => {
    setDeletingId(id);
    try {
      await onDelete(id);
      setConfirmDeleteId(null);
    } finally {
      setDeletingId(null);
    }
  };

  return <div className="history-overlay" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <aside ref={dialogRef} className="history-panel left-drawer" role="dialog" aria-label="분석 작업 이력" aria-modal="true">
      <header>
        <div><span><History size={18} /></span><div><small>ANALYSIS LEDGER</small><h2>분석 작업 이력</h2></div></div>
        <button type="button" aria-label="분석 작업 이력 닫기" onClick={onClose}>닫기</button>
      </header>
      <div className="history-summary"><strong>{entries.length}</strong><span>개의 대화 세션이 저장되어 있습니다.</span></div>
      <div className="history-list">
        {loading && <div className="history-state"><span className="status-spinner" /> 대화 세션을 불러오는 중입니다.</div>}
        {error && <div className="history-state error"><CircleAlert size={15} /> {error}</div>}
        {!loading && !error && entries.length === 0 && <div className="history-state">아직 저장된 대화 세션이 없습니다.</div>}
        {!loading && entries.map((entry) => <article className="history-entry conversation" key={entry.id}>
          <div className="history-entry-top">
            <time>{formatHistoryTime(entry.updated_at)}</time>
          </div>
          <h3>{displayRegionText(entry.title, entry.region ? [entry.region] : [])}</h3>
          {entry.region && <p className="history-region"><MapPinned size={12} /> {displayRegionName(entry.region)}</p>}
          {entry.summary && <p className="history-copy">{entry.summary}</p>}
          <footer>
            <span>메시지 {entry.message_count}개</span>
            {confirmDeleteId === entry.id ? <>
              <button type="button" className="history-cancel" onClick={() => setConfirmDeleteId(null)}>취소</button>
              <button
                type="button"
                className="history-delete confirm"
                aria-label="대화 삭제 확인"
                disabled={deletingId === entry.id}
                onClick={() => handleDelete(entry.id)}
              >{deletingId === entry.id ? "삭제 중" : "삭제 확인"}</button>
            </> : <button
              type="button"
              className="history-delete"
              aria-label="대화 삭제"
              onClick={() => setConfirmDeleteId(entry.id)}
            >삭제</button>}
            <button type="button" className="history-continue" aria-label="대화 이어서 열기" onClick={() => onRestore(entry.id)}>이어서 대화</button>
          </footer>
        </article>)}
      </div>
    </aside>
  </div>;
}

function formatHistoryTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "시간 정보 없음" : date.toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function Welcome({ region, onSelect }: { region: string | null; onSelect: (value: string) => void }) {
  return <div className="welcome">
    <div className="welcome-status">
      <span><i /> ANALYSIS READY</span>
      <b><MapPinned size={12} /> {region || "전국"}</b>
      <em>DuckDB + GPKG</em>
    </div>
    <div className="welcome-hero">
      <div className="welcome-copy">
        <span className="welcome-kicker">COASTAL ANALYSIS COPILOT</span>
        <h2>질문에서 근거 있는<br />보고서까지.</h2>
        <p><strong>{region || "전국"}</strong>의 원자료를 대화로 조회하고, 지도와 수치 근거를 한 흐름에서 확인하세요.</p>
      </div>
    </div>
    <div className="starter-grid">
      <button onClick={() => onSelect(STARTERS[0])}><span className="starter-number">01</span><Database size={19} /><span><strong>데이터 질의</strong><small>고위험 지역 순위를 실제 값으로 비교</small></span><ArrowUp size={14} /></button>
      <button onClick={() => onSelect(STARTERS[1])}><span className="starter-number">02</span><FileChartColumn size={19} /><span><strong>요인 분석</strong><small>위험성·노출성·취약성 근거 탐색</small></span><ArrowUp size={14} /></button>
      <button onClick={() => onSelect(STARTERS[2])}><span className="starter-number">03</span><Sparkles size={19} /><span><strong>/보고서작성</strong><small>지도·그래프·검증 보고서 자동 생성</small></span><ArrowUp size={14} /></button>
    </div>
  </div>;
}

function ChatTurn({
  message,
  region,
  materialSelected,
  selectedMaterialIds,
  onToggleMaterial,
  onToggleMcpMaterial,
  onOpenMap,
  onSaveReport,
  onCancelReport,
  onRetryReport,
  onCancelQuery,
  onRetryQuery,
  onCopyQuery,
  onOpenSpatialOperation,
  onKeepSpatialLayer,
}: {
  message: ChatMessage;
  region: string | null;
  materialSelected: boolean;
  selectedMaterialIds: string[];
  onToggleMaterial: () => void;
  onToggleMcpMaterial: (material: ReportMaterial) => void;
  onOpenMap: (
    region: string | null,
    context?: string,
    grades?: string[],
    focusNames?: string[],
    metricId?: string,
  ) => void;
  onSaveReport: (markdown: string) => Promise<void>;
  onCancelReport: () => Promise<void>;
  onRetryReport: () => Promise<void>;
  onCancelQuery: () => void;
  onRetryQuery: () => Promise<void>;
  onCopyQuery: () => Promise<void>;
  onOpenSpatialOperation: (operation: SpatialOperationResult) => void;
  onKeepSpatialLayer: (operation: SpatialOperationResult) => void;
}) {
  const user = message.role === "user";
  return <article className={`chat-turn ${user ? "user-turn" : "assistant-turn"}`}>
    <div className="turn-body">
      <div className="turn-meta"><strong>{user ? "나" : "연안재해 에이전트"}</strong></div>
      {message.kind === "text" && <p className="plain-message">{message.text}</p>}
      {message.kind === "loading" && <LoadingMessage
        text={message.text || "처리 중입니다."}
        startedAt={message.startedAt}
        onCancel={message.queryRequest ? onCancelQuery : undefined}
      />}
      {message.kind === "error" && <div className="message-error">
        <CircleAlert size={17} /> <span>{message.text}</span>
        {message.queryRequest && <button type="button" onClick={() => void onRetryQuery()}>
          <RotateCcw size={14} /> 질의 다시 시도
        </button>}
      </div>}
      {message.kind === "query" && message.query && <QueryMessage
        result={message.query}
        analysisContext={message.analysisContext}
        materialSelected={materialSelected}
        onToggleMaterial={onToggleMaterial}
        selectedMaterialIds={selectedMaterialIds}
        onToggleMcpMaterial={onToggleMcpMaterial}
        onRetry={() => void onRetryQuery()}
        onCopy={() => void onCopyQuery()}
        spatialOperations={message.spatialOperations || []}
        onOpenSpatialOperation={onOpenSpatialOperation}
        onKeepSpatialLayer={onKeepSpatialLayer}
      />}
      {message.kind === "comparison" && message.comparison && <ComparisonMessage
        result={message.comparison}
        materialSelected={materialSelected}
        onToggleMaterial={onToggleMaterial}
        onOpenMap={onOpenMap}
      />}
      {message.kind === "spatial" && message.spatial && <SpatialSelectionMessage
        result={message.spatial}
        materialSelected={materialSelected}
        onToggleMaterial={onToggleMaterial}
        onOpenMap={onOpenMap}
      />}
      {message.kind === "report" && message.report && (
        <ReportMessage
          job={message.report}
          preview={message.preview || ""}
          provenance={message.provenance || []}
          region={region}
          onOpenMap={onOpenMap}
          onSave={onSaveReport}
          onCancel={onCancelReport}
          onRetry={onRetryReport}
        />
      )}
    </div>
  </article>;
}

function LoadingMessage({
  text,
  startedAt,
  onCancel,
}: {
  text: string;
  startedAt?: number;
  onCancel?: () => void;
}) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!startedAt) return;
    const update = () => setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);
  return <div className="thinking">
    <span><i /><i /><i /></span>
    <p>{text}{startedAt ? ` · ${elapsed}초` : ""}</p>
    {onCancel && <button type="button" aria-label="질의 중단" onClick={onCancel}>
      <Square size={12} /> 중단
    </button>}
  </div>;
}

export function SpatialSelectionMessage({
  result,
  materialSelected,
  onToggleMaterial,
  onOpenMap,
}: {
  result: SpatialSelectionAnalysis;
  materialSelected: boolean;
  onToggleMaterial: () => void;
  onOpenMap: (region: string | null, context?: string, grades?: string[], focusNames?: string[], metricId?: string) => void;
}) {
  const mcpCharts = result.mcp
    ? (result.mcp.charts?.length ? result.mcp.charts : [result.mcp])
    : [];
  const [selectionChart, setSelectionChart] = useState(0);
  const activeChart = mcpCharts[selectionChart] || mcpCharts[0];
  return <div className="spatial-selection-message">
    <div className="grounding-line"><Check size={14} /> GPKG 공간 교차 결과</div>
    <h3>사용자 지정 영역 분석</h3>
    <p>{result.summary}</p>
    {result.analysis?.narrative && <p className="selection-analysis-copy">{result.analysis.narrative}</p>}
    <div className="spatial-selection-stats">
      <div><span>선택 격자</span><strong>{result.stats.selected_count.toLocaleString()}개</strong></div>
      <div><span>평균 등급</span><strong>{result.stats.average_grade ?? "-"}</strong></div>
      <div><span>4·5등급</span><strong>{result.stats.high_risk_count.toLocaleString()}개 · {result.stats.high_risk_pct}%</strong></div>
    </div>
    {result.overlaps.length > 0 && <div className="spatial-selection-overlaps">
      {result.overlaps.slice(0, 5).map((item) => <span key={item.metric_id}>{item.label} <b>{item.high_risk_pct}%</b></span>)}
    </div>}
    {result.analysis?.drivers.length > 0 && <div className="selection-driver-table">
      <div><span>주요 원인</span><span>선택 평균</span><span>비교 기준</span><span>격차</span></div>
      {result.analysis.drivers.map((driver) => <div key={driver.factor}>
        <strong>{driver.factor}<small>{driver.group}</small></strong>
        <b>{driver.selected_mean}{driver.unit}</b>
        <span>지역 평균 {driver.region_mean}{driver.unit}</span>
        <em>{driver.difference_pct_point >= 0 ? "+" : ""}{driver.difference_pct_point}%p</em>
      </div>)}
    </div>}
    {result.mcp && <div className="selection-mcp-result">
      <small className="mcp-dataset-scope">
        <Sparkles size={12} /> 선택 영역 {(
          result.mcp.dataset?.selection?.selected_count
          ?? result.stats.selected_count
        ).toLocaleString()}개 격자 원자료 기반 MCP 시각화
      </small>
      {mcpCharts.length > 1 && <div className="mcp-chart-tabs" role="tablist" aria-label="선택 영역 MCP 시각화">
        {mcpCharts.map((chart, index) => <button
          key={`${chart.chart}-${chart.chart_url}`}
          type="button"
          role="tab"
          aria-selected={selectionChart === index}
          onClick={() => setSelectionChart(index)}
        >{mcpChartLabel(chart.chart)}</button>)}
      </div>}
      {activeChart && <img src={activeChart.chart_url} alt={`선택 영역 MCP ${mcpChartLabel(activeChart.chart)}`} />}
      {activeChart?.reason && <p className="mcp-chart-reason">{activeChart.reason}</p>}
    </div>}
    <div className="message-actions">
      <button onClick={() => onOpenMap(result.region, "저장된 사용자 영역 분석", [], [], result.metric.id)}><MapPinned size={14} /> 공간분석 열기</button>
      <button className={materialSelected ? "selected" : ""} onClick={onToggleMaterial}>
        {materialSelected ? <BookMarked size={14} /> : <BookmarkPlus size={14} />}
        {materialSelected ? "보고서 자료에서 제외" : "보고서 자료에 추가"}
      </button>
    </div>
  </div>;
}

function QueryMessage({
  result,
  analysisContext,
  materialSelected,
  onToggleMaterial,
  selectedMaterialIds,
  onToggleMcpMaterial,
  onRetry,
  onCopy,
  spatialOperations,
  onOpenSpatialOperation,
  onKeepSpatialLayer,
}: {
  result: QueryResult;
  analysisContext?: AnalysisContext;
  materialSelected: boolean;
  onToggleMaterial: () => void;
  selectedMaterialIds: string[];
  onToggleMcpMaterial: (material: ReportMaterial) => void;
  onRetry: () => void;
  onCopy: () => void;
  spatialOperations: SpatialOperationResult[];
  onOpenSpatialOperation: (operation: SpatialOperationResult) => void;
  onKeepSpatialLayer: (operation: SpatialOperationResult) => void;
}) {
  const table = result.results.find((item) => item.columns.length && item.rows.length);
  const [mcpAnalysis, setMcpAnalysis] = useState<McpAnalysisResult | null>(null);
  const [selectedMcpChart, setSelectedMcpChart] = useState(0);
  const [mcpLoading, setMcpLoading] = useState(false);
  const [mcpError, setMcpError] = useState("");
  const [mcpSettingsOpen, setMcpSettingsOpen] = useState(false);
  const tableColumns = table?.columns || [];
  const numericColumns = table
    ? table.columns.filter((_, index) => table.rows.some((row) => (
      typeof row[index] === "number" && Number.isFinite(row[index])
    )))
    : [];
  const categoryColumns = tableColumns.filter((column) => !numericColumns.includes(column));
  const [customChart, setCustomChart] = useState<McpChartSpec["chart"]>("bar");
  const [customX, setCustomX] = useState(categoryColumns[0] || tableColumns[0] || "");
  const [customY, setCustomY] = useState(numericColumns[0] || "");
  const [customGroup, setCustomGroup] = useState("");
  const [customAggregation, setCustomAggregation] = useState<
    NonNullable<McpChartSpec["aggregation"]>
  >("mean");
  const [useGridData, setUseGridData] = useState(false);
  const [gridColumns, setGridColumns] = useState<string[] | null>(null);
  const [gridColumnsError, setGridColumnsError] = useState("");
  const gridNumericColumns = (gridColumns || []).filter((column) => column !== "지역");
  const activeColumns = useGridData && gridColumns ? gridColumns : tableColumns;
  const activeNumericColumns = useGridData && gridColumns ? gridNumericColumns : numericColumns;
  const numericXRequired = ["scatter", "histogram", "correlation_heatmap"].includes(
    customChart,
  );
  const customXOptions = numericXRequired ? activeNumericColumns : activeColumns;
  const customGroupRequired = ["stacked_bar", "pivot_heatmap"].includes(customChart);

  const toggleGridData = async () => {
    if (useGridData) {
      setUseGridData(false);
      setCustomX(categoryColumns[0] || tableColumns[0] || "");
      setCustomY(numericColumns[0] || "");
      setCustomGroup("");
      return;
    }
    if (!result.region) return;
    try {
      let columns = gridColumns;
      if (!columns) {
        const payload = await api.mcpGridColumns(result.region);
        columns = payload.columns;
        setGridColumns(columns);
      }
      setGridColumnsError("");
      setUseGridData(true);
      setCustomX(columns[0] || "");
      setCustomY(columns.find((column) => column !== "지역") || "");
      setCustomGroup("");
    } catch (error) {
      setGridColumnsError(
        error instanceof Error ? error.message : "평가항목 목록을 불러오지 못했습니다.",
      );
    }
  };

  const runMcpAnalysis = async (chartSpec?: McpChartSpec) => {
    if (!table || mcpLoading) return;
    setMcpLoading(true);
    setMcpError("");
    try {
      const chartTable = chartSpec && !useGridData
        ? mcpCustomTable(table, chartSpec)
        : chartSpec
          ? { columns: table.columns, rows: table.rows }
          : mcpChartTable(table);
      const contextSelection = analysisContext?.selection;
      const scopedSelection = (
        result.scope?.selection_id
        && contextSelection
        && contextSelection.id === result.scope.selection_id
      ) ? {
          id: contextSelection.id,
          metric: contextSelection.metric,
          grades: contextSelection.grades,
          geometry: contextSelection.geometry,
        } : undefined;
      const analysis = await api.mcpAnalyze({
        question: result.question,
        region: result.region || undefined,
        columns: chartTable.columns,
        rows: chartTable.rows,
        ...(chartSpec ? { chart_spec: chartSpec } : {}),
        ...(chartSpec && useGridData ? { use_grid_data: true } : {}),
        ...(scopedSelection ? { selection: scopedSelection } : {}),
      });
      setMcpAnalysis(analysis);
      setSelectedMcpChart(0);
      if (chartSpec) setMcpSettingsOpen(false);
    } catch (error) {
      setMcpError(error instanceof Error ? error.message : "MCP 분석에 실패했습니다.");
    } finally {
      setMcpLoading(false);
    }
  };

  const runCustomMcpAnalysis = () => {
    const groupColumn = customGroup || undefined;
    const spec: McpChartSpec = {
      chart: customChart,
      aggregation: customAggregation,
      top_n: 20,
      bins: 10,
      normalize: false,
    };
    if (customChart === "correlation_heatmap") {
      spec.columns = [customX, customY].filter(Boolean);
    } else if (customChart === "histogram") {
      spec.x_column = customX;
    } else {
      spec.x_column = customX || undefined;
      spec.y_column = customY || undefined;
      if (customChart === "stacked_bar") spec.stack_column = groupColumn;
      else if (["line", "area", "scatter", "pivot_heatmap"].includes(customChart)) {
        spec.group_column = groupColumn;
      }
    }
    spec.x_label = mcpAxisLabel(spec.x_column);
    spec.y_label = mcpAxisLabel(spec.y_column);
    void runMcpAnalysis(spec);
  };

  const mcpCharts = mcpAnalysis
    ? mcpAnalysis.charts?.length ? mcpAnalysis.charts : [mcpAnalysis]
    : [];
  const activeMcpChart = mcpCharts[selectedMcpChart] || mcpCharts[0];
  const activeMcpSourceId = activeMcpChart?.asset_name && mcpAnalysis
    ? `mcp:${mcpAnalysis.analysis_id}:${activeMcpChart.asset_name}`
    : "";
  const activeMcpSelected = selectedMaterialIds.includes(activeMcpSourceId);

  const toggleActiveMcpMaterial = () => {
    if (
      !mcpAnalysis
      || !activeMcpChart?.asset_name
      || !activeMcpChart.analysis
      || !activeMcpChart.evidence
      || activeMcpChart.grounded !== true
    ) return;
    const chartLabel = mcpChartLabel(activeMcpChart.chart);
    onToggleMcpMaterial({
      source_id: activeMcpSourceId,
      question: result.question,
      answer: activeMcpChart.analysis,
      region: result.region,
      grounded: true,
      scope: result.scope,
      queries: mcpAnalysis.dataset?.query
        ? [mcpAnalysis.dataset.query]
        : result.queries.slice(0, 1),
      results: [activeMcpChart.evidence],
      mcp_chart: {
        analysis_id: mcpAnalysis.analysis_id,
        asset_name: activeMcpChart.asset_name,
        caption: `${result.region ? `${result.region} ` : ""}${chartLabel}`,
        chart: activeMcpChart.chart as McpChartSpec["chart"],
      },
    });
  };

  return <div className="query-message">
    <div className="grounding-line">
      {result.grounded ? <Check size={14} /> : <CircleAlert size={14} />}
      {result.grounded ? "조회 결과와 수치 대조 완료" : "수치 확인이 필요한 답변"}
    </div>
    <p className="answer-copy">{displayRegionText(result.answer, result.region ? [result.region] : [])}</p>
    <InlineQueryAnalysis results={result.results} />
    {spatialOperations.length > 0 && <section className="query-spatial-results" aria-label="질문 연계 공간 레이어">
      <header><MapPinned size={14} /><strong>질문 연계 공간 레이어</strong></header>
      {spatialOperations.map((operation) => <article key={operation.operation_id}>
        <div><strong>{operation.name}</strong><small>{operation.stats.feature_count.toLocaleString()}개 격자</small></div>
        <button type="button" onClick={() => onOpenSpatialOperation(operation)}>지도에서 보기</button>
        <button type="button" onClick={() => onKeepSpatialLayer(operation)}>임시 레이어 저장</button>
      </article>)}
    </section>}
    <div className="query-actions">
      <button type="button" aria-label="답변과 SQL 복사" onClick={onCopy}>
        <Copy size={14} /> 복사
      </button>
      <button type="button" aria-label="질의 다시 시도" onClick={onRetry}>
        <RotateCcw size={14} /> 다시 실행
      </button>
      <button
        className={`material-toggle ${materialSelected ? "selected" : ""}`}
        aria-label={
          !result.grounded
            ? "검증 실패 답변은 보고서에 추가할 수 없습니다"
            : materialSelected ? "보고서에서 제외" : "보고서에 추가"
        }
        disabled={!result.grounded}
        onClick={onToggleMaterial}
      >
        {materialSelected ? <BookMarked size={14} /> : <BookmarkPlus size={14} />}
        {!result.grounded
          ? "검증 실패"
          : materialSelected ? "보고서에 담김" : "보고서에 추가"}
      </button>
      {table && <button
        className="mcp-analysis-trigger"
        aria-label="MCP 고급 분석"
        disabled={mcpLoading}
        onClick={() => void runMcpAnalysis()}
      >
        <Sparkles size={14} />
        {mcpLoading ? "MCP 분석 중…" : "MCP 고급 분석"}
      </button>}
      {table && <button
        className={`mcp-settings-trigger ${mcpSettingsOpen ? "active" : ""}`}
        aria-label="MCP 시각화 직접 설정"
        disabled={mcpLoading}
        onClick={() => setMcpSettingsOpen((open) => !open)}
      >
        <FileChartColumn size={14} />
        직접 설정
      </button>}
    </div>
    {table && mcpSettingsOpen && <section
      className="mcp-chart-builder"
      role="group"
      aria-label="MCP 시각화 설정"
    >
      <header>
        <div>
          <small>CUSTOM VISUALIZATION</small>
          <strong>조회 열로 그래프 설계</strong>
        </div>
        <button
          type="button"
          aria-label="MCP 시각화 설정 닫기"
          onClick={() => setMcpSettingsOpen(false)}
        ><X size={16} /></button>
      </header>
      {result.region && <label className="mcp-grid-toggle">
        <input
          type="checkbox"
          aria-label="평가항목 원자료로 그리기"
          checked={useGridData}
          onChange={() => void toggleGridData()}
        />
        <span>평가항목 원자료로 그리기 — 강풍·강우·고령인구 등 25종을 X·Y축으로 사용</span>
      </label>}
      {gridColumnsError && <p className="mcp-analysis-error">{gridColumnsError}</p>}
      <div className="mcp-chart-fields">
        <label>
          <span>그래프 유형</span>
          <select
            aria-label="그래프 유형"
            value={customChart}
            onChange={(event) => {
              const nextChart = event.target.value as McpChartSpec["chart"];
              setCustomChart(nextChart);
              if (
                ["scatter", "histogram", "correlation_heatmap"].includes(nextChart)
                && !activeNumericColumns.includes(customX)
              ) {
                setCustomX(activeNumericColumns[0] || "");
              }
            }}
          >
            <option value="bar">막대</option>
            <option value="stacked_bar">누적 막대</option>
            <option value="line">선</option>
            <option value="area">영역</option>
            <option value="scatter">산점도</option>
            <option value="histogram">히스토그램</option>
            <option value="boxplot">상자수염</option>
            <option value="violin">바이올린</option>
            <option value="correlation_heatmap">상관관계 히트맵</option>
            <option value="pivot_heatmap">피벗 히트맵</option>
          </select>
        </label>
        <label>
          <span>X축</span>
          <select
            aria-label="X축"
            value={customX}
            onChange={(event) => setCustomX(event.target.value)}
          >
            {customXOptions.map((column) => (
              <option key={column} value={column}>{column}</option>
            ))}
          </select>
        </label>
        {customChart !== "histogram" && <label>
          <span>Y축</span>
          <select
            aria-label="Y축"
            value={customY}
            onChange={(event) => setCustomY(event.target.value)}
          >
            {activeNumericColumns.map((column) => <option key={column} value={column}>{column}</option>)}
          </select>
        </label>}
        {["stacked_bar", "line", "area", "scatter", "pivot_heatmap"].includes(customChart) && <label>
          <span>그룹</span>
          <select
            aria-label="그룹"
            value={customGroup}
            onChange={(event) => setCustomGroup(event.target.value)}
          >
            <option value="">선택 안 함</option>
            {activeColumns.map((column) => <option key={column} value={column}>{column}</option>)}
          </select>
        </label>}
        {["bar", "stacked_bar", "line", "area", "pivot_heatmap"].includes(customChart) && <label>
          <span>집계</span>
          <select
            aria-label="집계"
            value={customAggregation}
            onChange={(event) => setCustomAggregation(
              event.target.value as NonNullable<McpChartSpec["aggregation"]>,
            )}
          >
            <option value="mean">평균</option>
            <option value="sum">합계</option>
            <option value="count">개수</option>
            <option value="min">최솟값</option>
            <option value="max">최댓값</option>
            <option value="median">중앙값</option>
          </select>
        </label>}
      </div>
      <footer>
        <p>축 제목에는 원자료 단위가 자동으로 함께 표기됩니다.</p>
        <button
          type="button"
          disabled={mcpLoading || !customX || (
            customChart !== "histogram" && customChart !== "correlation_heatmap" && !customY
          ) || (customGroupRequired && !customGroup)}
          onClick={runCustomMcpAnalysis}
        >
          <Sparkles size={14} />
          선택한 그래프 생성
        </button>
      </footer>
    </section>}
    {mcpError && <p className="mcp-analysis-error">{mcpError}</p>}
    {mcpAnalysis && <section className="mcp-analysis-result">
      <header>
        <span><Sparkles size={15} /></span>
        <div><small>DATA-ANALYZE MCP · {mcpAnalysis.tools_available} TOOLS</small><strong>MCP 추천 시각화</strong></div>
      </header>
      {mcpAnalysis.dataset && <p className="mcp-dataset-scope">
        <Database size={12} /> {mcpAnalysis.dataset.source === "duckdb_selected_grid"
          ? `선택 영역 ${(mcpAnalysis.dataset.selection?.selected_count ?? mcpAnalysis.dataset.row_count).toLocaleString()}개 격자 원자료 기반`
          : mcpAnalysis.dataset.source === "duckdb_grid_raw"
            ? `${result.region ? `${result.region} ` : ""}격자 원자료 ${mcpAnalysis.dataset.row_count.toLocaleString()}행 기반`
            : `답변 결과표 ${mcpAnalysis.dataset.row_count.toLocaleString()}행 기반`}
      </p>}
      {mcpCharts.length > 1 && <div className="mcp-chart-tabs" role="tablist" aria-label="MCP 시각화 선택">
        {mcpCharts.map((chart, index) => <button
          key={`${chart.chart}-${chart.chart_url}`}
          type="button"
          role="tab"
          aria-selected={selectedMcpChart === index}
          onClick={() => setSelectedMcpChart(index)}
        >{mcpChartLabel(chart.chart)}</button>)}
      </div>}
      {activeMcpChart && <>
        <img src={activeMcpChart.chart_url} alt={`MCP ${mcpChartLabel(activeMcpChart.chart)}`} />
        {activeMcpChart.analysis && <div className="mcp-grounded-analysis">
          <small><Check size={13} /> 실제 데이터 기반 분석</small>
          <p>{activeMcpChart.analysis}</p>
        </div>}
        <p className="mcp-chart-reason">{activeMcpChart.reason}</p>
        <div className="mcp-chart-actions">
          <button
            type="button"
            aria-label="현재 MCP 차트 다운로드"
            onClick={() => downloadInBrowser(
              activeMcpChart.chart_url,
              activeMcpChart.asset_name || `mcp-${activeMcpChart.chart}.png`,
            )}
          ><ArrowDownToLine size={14} /> PNG 다운로드</button>
          {activeMcpChart.grounded === true
          && activeMcpChart.asset_name
          && activeMcpChart.analysis
          && activeMcpChart.evidence
          && <button
            type="button"
            className={`mcp-report-toggle ${activeMcpSelected ? "selected" : ""}`}
            aria-label={
              activeMcpSelected
                ? "현재 MCP 차트를 보고서에서 제외"
                : "현재 MCP 차트를 보고서에 추가"
            }
            onClick={toggleActiveMcpMaterial}
          >
            {activeMcpSelected
              ? <BookMarked size={14} />
              : <BookmarkPlus size={14} />}
            {activeMcpSelected ? "보고서 자료에 담김" : "현재 그래프를 보고서에 추가"}
          </button>}
        </div>
      </>}
      <footer>
        {mcpAnalysis.dataset?.source === "duckdb_grid_raw" && <span className="mcp-dataset-scope">
          DuckDB 격자 원자료 {mcpAnalysis.dataset.row_count.toLocaleString()}행 ·{" "}
          {mcpAnalysis.dataset.column_count}열 확장 분석
        </span>}
        {mcpAnalysis.tool_calls.map((tool) => <code key={tool}>{tool}</code>)}
      </footer>
    </section>}
    {result.results.map((table, index) => <div className="inline-table" key={index}>
      <div className="card-title"><Database size={15} /> 원본 조회 결과</div>
      <div className="table-scroll"><table><thead><tr>
        {table.columns.map((column) => <th key={column}>{column}</th>)}
      </tr></thead><tbody>
        {table.rows.map((row, rowIndex) => <tr key={rowIndex}>
          {row.map((value, cellIndex) => <td key={cellIndex}>{value ?? "—"}</td>)}
        </tr>)}
      </tbody></table></div>
    </div>)}
    <details className="sql-evidence">
      <summary><Database size={14} /> 실행 SQL {result.queries.length}개 보기 <ChevronDown size={14} /></summary>
      {result.queries.map((sql, index) => <pre key={index}>{sql}</pre>)}
    </details>
  </div>;
}

function InlineQueryAnalysis({ results }: { results: QueryResult["results"] }) {
  const table = results.find((item) => item.columns.length > 0 && item.rows.length > 0);
  if (!table) return null;

  if (table.rows.length === 1) {
    const metrics = table.columns.flatMap((column, index) => {
      const value = table.rows[0][index];
      return typeof value === "number" && Number.isFinite(value) ? [{ column, value }] : [];
    }).slice(0, 4);
    if (!metrics.length) return null;
    return <section className="inline-analysis inline-metrics" role="group" aria-label="인라인 핵심 지표">
      <InlineAnalysisTitle label="핵심 수치" />
      <div>{metrics.map((metric) => <article key={metric.column}>
        <small>{metric.column}</small>
        <strong>{formatQueryNumber(metric.value)}</strong>
      </article>)}</div>
    </section>;
  }

  const numericColumns = table.columns.map((_, index) => index).filter((index) => (
    table.rows.some((row) => typeof row[index] === "number" && Number.isFinite(row[index]))
  ));
  if (!numericColumns.length) return null;
  const labelIndex = table.columns.findIndex((_, index) => (
    table.rows.some((row) => typeof row[index] === "string")
  ));
  const valueIndex = [...numericColumns].reverse().find((index) => index !== labelIndex)
    ?? numericColumns[numericColumns.length - 1];
  const bars = table.rows.flatMap((row, index) => {
    const value = row[valueIndex];
    if (typeof value !== "number" || !Number.isFinite(value)) return [];
    const label = labelIndex >= 0 ? row[labelIndex] : row[0] ?? index + 1;
    return [{ label: String(label), value }];
  }).slice(0, 8);
  if (bars.length < 2) return null;
  const maximum = Math.max(...bars.map((item) => Math.abs(item.value)), 1);
  const measure = table.columns[valueIndex];

  return <section className="inline-analysis inline-bars">
    <InlineAnalysisTitle label={`${measure} 비교`} />
    <div className="inline-bar-chart" role="img" aria-label={`${measure} 인라인 막대 차트`}>
      {bars.map((item) => <div className="inline-bar-row" key={`${item.label}-${item.value}`}>
        <span title={item.label}>{item.label}</span>
        <div><i style={{ width: `${Math.abs(item.value) / maximum * 100}%` }} /></div>
        <strong>{formatQueryNumber(item.value)}</strong>
      </div>)}
    </div>
  </section>;
}

function InlineAnalysisTitle({ label }: { label: string }) {
  return <header className="inline-analysis-title">
    <span><FileChartColumn size={14} /></span>
    <div><small>DUCKDB · INLINE VIEW</small><strong>{label}</strong></div>
  </header>;
}

function formatQueryNumber(value: number) {
  return value.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
}

function ComparisonMessage({
  result,
  materialSelected,
  onToggleMaterial,
  onOpenMap,
}: {
  result: ComparisonResult;
  materialSelected: boolean;
  onToggleMaterial: () => void;
  onOpenMap: (region: string, context?: string, grades?: string[]) => void;
}) {
  const maximum = Math.max(...result.summary.map((item) => item.high_risk_pct), 1);
  return <div className="comparison-message">
    <div className="comparison-head">
      <div><span><GitCompareArrows size={18} /></span><div><small>DUCKDB · SAME METRIC</small><h3>지역 비교 분석</h3></div></div>
      <b><ShieldCheck size={12} /> 검증된 비교</b>
    </div>
    <p className="comparison-answer">{displayRegionText(result.answer, result.regions)}</p>
    <div className="comparison-grid">{result.summary.map((item, index) => {
      const distribution = result.distribution[item.region] || [];
      return <article className={index === 0 ? "primary" : ""} key={item.region}>
        <div className="comparison-region"><span>{String(index + 1).padStart(2, "0")}</span><strong>{displayRegionName(item.region)}</strong></div>
        <div className="comparison-metrics">
          <div><small>격자 수</small><strong>{item.grid_count.toLocaleString()}</strong></div>
          <div><small>평균 등급</small><strong>{item.avg_grade?.toFixed(2) ?? "—"}</strong></div>
          <div className="risk"><small>4·5등급</small><strong>{item.high_risk_pct.toFixed(1)}%</strong><em>{item.high_risk_count.toLocaleString()}개</em></div>
        </div>
        <div className="risk-compare-track"><i style={{ width: `${item.high_risk_pct / maximum * 100}%` }} /></div>
        <div className="grade-composition" aria-label={`${displayRegionName(item.region)} 등급 분포`}>
          {distribution.map((grade) => <i
            key={grade.grade}
            title={`${grade.grade}등급 ${grade.pct}%`}
            style={{ width: `${grade.pct}%`, background: GRADE_COLORS[grade.grade] }}
          />)}
        </div>
        <button
          className="comparison-map"
          aria-label={`지도에서 보기: ${displayRegionName(item.region)}`}
          onClick={() => onOpenMap(item.region, `${displayRegionName(item.region)} 비교 결과`, ["4", "5"])}
        ><MapPinned size={13} /> 지도에서 보기</button>
      </article>;
    })}</div>
    <div className="comparison-footer">
      <button
        className={`material-toggle ${materialSelected ? "selected" : ""}`}
        aria-label={materialSelected ? "보고서에서 제외" : "보고서에 추가"}
        onClick={onToggleMaterial}
      >{materialSelected ? <BookMarked size={14} /> : <BookmarkPlus size={14} />}
        {materialSelected ? "보고서에 포함됨" : "보고서에 추가"}
      </button>
      <details className="comparison-sql"><summary><Database size={13} /> 비교 SQL {result.queries.length}개</summary>
        {result.queries.map((sql, index) => <pre key={index}>{sql}</pre>)}
      </details>
    </div>
  </div>;
}

function ReportMessage({
  job,
  preview,
  provenance,
  region,
  onOpenMap,
  onSave,
  onCancel,
  onRetry,
}: {
  job: ReportJob;
  preview: string;
  provenance: ProvenanceEntry[];
  region: string | null;
  onOpenMap: (
    region: string | null,
    context?: string,
    grades?: string[],
    focusNames?: string[],
    metricId?: string,
  ) => void;
  onSave: (markdown: string) => Promise<void>;
  onCancel: () => Promise<void>;
  onRetry: () => Promise<void>;
}) {
  const result = job.result || {};
  const figures = (result.figures || {}) as Record<string, string>;
  const completed = job.status === "completed";
  const failed = job.status === "failed";
  const cancelled = job.status === "cancelled";
  const cancelling = job.status === "cancel_requested";
  const canCancel = job.status === "queued" || job.status === "running";
  const canRetry = failed || cancelled;
  const [selectedEvidence, setSelectedEvidence] = useState<ProvenanceEntry | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceHeight, setEvidenceHeight] = useState(560);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [editLoading, setEditLoading] = useState(false);
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState("");
  const markdownPreview = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!selectedEvidence) return;
    markdownPreview.current
      ?.querySelector<HTMLElement>(`[data-evidence-id="${selectedEvidence.id}"]`)
      ?.scrollIntoView({ block: "center", inline: "nearest" });
  }, [selectedEvidence?.id]);
  const [jobActionLoading, setJobActionLoading] = useState(false);
  const [jobActionError, setJobActionError] = useState("");

  const startEvidenceResize = (event: ReactMouseEvent<HTMLElement>) => {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = evidenceHeight;
    const move = (moveEvent: MouseEvent) => {
      setEvidenceHeight(Math.min(
        EVIDENCE_MAX_HEIGHT,
        Math.max(EVIDENCE_MIN_HEIGHT, startHeight + moveEvent.clientY - startY),
      ));
    };
    const stop = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", stop);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);
  };

  const runJobAction = async (action: () => Promise<void>) => {
    if (jobActionLoading) return;
    setJobActionLoading(true);
    setJobActionError("");
    try {
      await action();
    } catch (error) {
      setJobActionError(error instanceof Error ? error.message : "보고서 작업 요청에 실패했습니다.");
    } finally {
      setJobActionLoading(false);
    }
  };

  const beginEditing = async () => {
    setEditLoading(true);
    setEditError("");
    try {
      const source = await api.reportContent(job.job_id);
      setDraft(source.markdown);
      setEditing(true);
    } catch (error) {
      setEditError(error instanceof Error ? error.message : "편집 원문을 불러오지 못했습니다.");
    } finally {
      setEditLoading(false);
    }
  };

  const cancelEditing = () => {
    setEditing(false);
    setDraft("");
    setEditError("");
  };

  const saveEditing = async () => {
    if (!draft.trim() || draft === preview || editSaving) return;
    setEditSaving(true);
    setEditError("");
    try {
      await onSave(draft);
      setEditing(false);
    } catch (error) {
      setEditError(error instanceof Error ? error.message : "보고서 저장에 실패했습니다.");
    } finally {
      setEditSaving(false);
    }
  };

  const showEvidence = async (entry: ProvenanceEntry) => {
    setSelectedEvidence(entry);
    if (!entry.grounded) return;
    setEvidenceLoading(true);
    try {
      setSelectedEvidence(await api.provenanceDetail(job.job_id, entry.id));
    } catch {
      setSelectedEvidence(entry);
    } finally {
      setEvidenceLoading(false);
    }
  };

  return <div className="report-message">
    <div className="report-intro">
      <div><span className="report-icon"><FileText size={19} /></span><div><strong>{region ? displayRegionName(region) : "전국"} 연안재해 위험평가</strong><p>{completed ? "보고서 작성이 완료되었습니다." : failed ? "보고서 작업이 중단되었습니다." : cancelled ? "보고서 작업을 취소했습니다." : cancelling ? "안전하게 취소하는 중입니다." : "보고서 작업을 준비하고 있습니다."}</p></div></div>
      <span className={`status-badge ${completed ? "complete" : failed ? "failed" : cancelled ? "cancelled" : "running"}`}>
        {completed ? <Check size={13} /> : failed || cancelled ? <X size={13} /> : <span className="status-spinner" />}
        {completed ? "완료" : failed ? "실패" : cancelled ? "취소됨" : cancelling ? "취소 중" : "작성 중"}
      </span>
    </div>
    <div className="stage-track" role="list" aria-label="보고서 작업 단계">
      {STAGES.map(([key, label], index) => {
        const done = job.progress > index;
        const active = job.stage === key && job.status === "running";
        return <div
          className={`${done ? "done" : ""} ${active ? "active" : ""}`}
          key={key}
          role="listitem"
          aria-current={active ? "step" : undefined}
        >
          <span className="stage-number">{done ? <Check size={14} /> : index + 1}</span>
          <small className="stage-label">{label}</small>
        </div>;
      })}
    </div>
    {result.analysis_trace && <div className="data-trace"><Database size={14} /> DuckDB 조회 <strong>{result.analysis_trace.query_count}회</strong><span />GPKG 공간 레이어 반영</div>}
    {Object.keys(figures).length > 0 && <InlineFigures figures={figures} jobId={job.job_id} />}
    {failed && <div className="message-error"><CircleAlert size={16} /> {job.errors.join(" · ")}</div>}
    {(canCancel || canRetry || jobActionError) && <div className="report-job-controls">
      {canCancel && <button
        type="button"
        aria-label="보고서 작업 취소"
        disabled={jobActionLoading}
        onClick={() => void runJobAction(onCancel)}
      ><X size={16} /> {jobActionLoading ? "취소 요청 중…" : "작업 취소"}</button>}
      {canRetry && <button
        type="button"
        className="primary"
        aria-label="보고서 작업 재시도"
        disabled={jobActionLoading}
        onClick={() => void runJobAction(onRetry)}
      ><Sparkles size={16} /> {jobActionLoading ? "재시도 준비 중…" : "다시 실행"}</button>}
      {jobActionError && <p><CircleAlert size={15} /> {jobActionError}</p>}
    </div>}
    {completed && <>
      <div className="report-actions">
        <div><ShieldCheck size={15} /><span>최종 수치 검증</span><strong>{result.verify_trace?.result === "passed" ? "통과" : "폴백 적용"}</strong></div>
        {preview && <button
          type="button"
          className="report-edit-button"
          aria-label="보고서 직접 편집"
          disabled={editing || editLoading}
          onClick={beginEditing}
        ><FilePenLine size={15} /> {editLoading ? "원문 불러오는 중…" : "직접 편집"}</button>}
        <a
          href={`/api/reports/${job.job_id}/download/md`}
          onClick={(event) => {
            event.preventDefault();
            downloadInBrowser(`/api/reports/${job.job_id}/download/md`);
          }}
        ><ArrowDownToLine size={15} /> Markdown</a>
        {result.report_hwpx_path && <a
          href={`/api/reports/${job.job_id}/download/hwpx`}
          onClick={(event) => {
            event.preventDefault();
            downloadInBrowser(`/api/reports/${job.job_id}/download/hwpx`);
          }}
        ><ArrowDownToLine size={15} /> HWPX</a>}
      </div>
      <div className="revision-hint"><FilePenLine size={14} /><span><strong>두 가지 편집</strong> 위 버튼으로 직접 수정하거나, “정책 제언을 더 짧게”처럼 대화로 요청하세요.</span>{Number(result.revision_count || 0) > 0 && <b>v{Number(result.revision_count) + 1}</b>}</div>
      {editError && !editing && <p className="report-editor-error standalone"><CircleAlert size={13} /> {editError}</p>}
      {editing && <section className="report-editor">
        <header>
          <div><span><FilePenLine size={16} /></span><div><small>MARKDOWN WORKSPACE</small><strong>보고서 원고 직접 편집</strong></div></div>
          <b>v{Number(result.revision_count || 0) + 2} 초안</b>
        </header>
        <div className="report-editor-note"><ShieldCheck size={13} /><span>새로 입력한 수치와 지역명은 저장 전에 원자료 근거와 자동 대조됩니다.</span></div>
        <label className="sr-only" htmlFor={`report-editor-${job.job_id}`}>보고서 Markdown 편집</label>
        <textarea
          id={`report-editor-${job.job_id}`}
          aria-label="보고서 Markdown 편집"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          spellCheck={false}
        />
        {editError && <p className="report-editor-error"><CircleAlert size={13} /> {editError}</p>}
        <footer>
          <span>{draft.length.toLocaleString()}자 · 원본은 별도 보존</span>
          <div>
            <button type="button" aria-label="직접 편집 취소" onClick={cancelEditing}>취소</button>
            <button
              type="button"
              className="primary"
              aria-label="편집 내용 저장"
              disabled={!draft.trim() || draft === preview || editSaving}
              onClick={saveEditing}
            >{editSaving ? "검증·저장 중…" : "새 버전으로 저장"}</button>
          </div>
        </footer>
      </section>}
      {preview && !editing && <details className="inline-report" open>
        <summary>보고서 본문 미리보기 <ChevronDown size={15} /></summary>
        <div className="provenance-legend">
          <Link2 size={13} />
          <span>밑줄 친 문장을 누르면 데이터 근거를 확인할 수 있습니다.</span>
          <strong>{provenance.filter((entry) => entry.grounded).length}개 연결</strong>
        </div>
        <div
          className={`evidence-layout ${selectedEvidence ? "with-panel" : ""}`}
          style={{ "--evidence-height": `${evidenceHeight}px` } as CSSProperties}
        >
          <div className="markdown-preview" ref={markdownPreview}><ReactMarkdown components={{
            p: ({ children }) => (
              <EvidenceParagraph entries={provenance} onSelect={showEvidence}>
                {children}
              </EvidenceParagraph>
            ),
            li: ({ children }) => (
              <EvidenceParagraph as="li" entries={provenance} onSelect={showEvidence}>
                {children}
              </EvidenceParagraph>
            ),
          }}>{preview}</ReactMarkdown></div>
          {selectedEvidence && <EvidencePanel
            entry={selectedEvidence}
            loading={evidenceLoading}
            onClose={() => setSelectedEvidence(null)}
            onOpenMap={onOpenMap}
          />}
        </div>
        <div
          className="evidence-resizer"
          role="separator"
          aria-label="문장 근거 높이 조절"
          aria-orientation="horizontal"
          aria-valuemin={EVIDENCE_MIN_HEIGHT}
          aria-valuemax={EVIDENCE_MAX_HEIGHT}
          aria-valuenow={evidenceHeight}
          tabIndex={0}
          onMouseDown={startEvidenceResize}
          onKeyDown={(event) => {
            if (event.key === "ArrowUp") {
              setEvidenceHeight((height) => Math.max(EVIDENCE_MIN_HEIGHT, height - 32));
            }
            if (event.key === "ArrowDown") {
              setEvidenceHeight((height) => Math.min(EVIDENCE_MAX_HEIGHT, height + 32));
            }
          }}
        ><span aria-hidden="true" /></div>
      </details>}
    </>}
  </div>;
}

function EvidenceParagraph({
  children,
  entries,
  onSelect,
  as = "p",
}: {
  children: ReactNode;
  entries: ProvenanceEntry[];
  onSelect: (entry: ProvenanceEntry) => void;
  as?: "p" | "li";
}) {
  const Tag = as;
  const plain = evidenceText(children);

  const parts = plain.split(/(?<=[.!?])\s+/);
  const matches = parts.map((part) => entries.find((candidate) => (
    normalizeEvidenceSentence(candidate.sentence) === normalizeEvidenceSentence(part.trim())
  )));
  if (!matches.some(Boolean)) return <Tag>{children}</Tag>;

  return <Tag>{parts.map((part, index) => {
    const sentence = part.trim();
    const entry = matches[index];
    if (!entry) return <span key={index}>{part}</span>;
    return <span key={entry.id}>
      <button
        type="button"
        className={`evidence-sentence ${entry.grounded ? "grounded" : "general"}`}
        data-evidence-id={entry.id}
        aria-label={`${entry.grounded ? "근거 보기" : "설명 보기"}: ${sentence}`}
        onClick={() => onSelect(entry)}
      >
        {sentence}
      </button>{index < parts.length - 1 ? " " : ""}
    </span>;
  })}</Tag>;
}

function evidenceText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(evidenceText).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return evidenceText(node.props.children);
  return "";
}

function normalizeEvidenceSentence(value: string) {
  return value
    .replace(/^\s*(?:[-*+]|\d+[.)])\s+/, "")
    .replace(/\s+/g, " ")
    .trim();
}

function EvidencePanel({
  entry,
  loading,
  onClose,
  onOpenMap,
}: {
  entry: ProvenanceEntry;
  loading: boolean;
  onClose: () => void;
  onOpenMap: (
    region: string | null,
    context?: string,
    grades?: string[],
    focusNames?: string[],
    metricId?: string,
  ) => void;
}) {
  return <aside className="evidence-panel" aria-live="polite">
    <header>
      <div><Link2 size={15} /><h3>문장 근거</h3></div>
      <button type="button" aria-label="근거 패널 닫기" onClick={onClose}>닫기</button>
    </header>
    <p className="evidence-quote">{entry.sentence}</p>
    <span className={`evidence-status ${entry.grounded ? "grounded" : "general"}`}>
      {entry.grounded ? <><ShieldCheck size={12} /> 데이터 근거 연결</> : "일반 서술"}
    </span>
    {entry.grounded && entry.map_context?.region && <button
      type="button"
      className="evidence-map-button"
      aria-label="지도에서 보기"
      onClick={() => onOpenMap(
        entry.map_context!.region,
        entry.sentence,
        entry.map_context!.grades,
        entry.map_context!.adm_names,
        entry.map_context!.metric_id,
      )}
    ><MapPinned size={13} /> 지도에서 보기</button>}
    {!entry.grounded && <p className="evidence-note">
      정량값을 주장하지 않는 배경·방법 설명으로, 특정 통계나 SQL에 연결하지 않았습니다.
    </p>}
    {entry.stats.length > 0 && <section>
      <h4>일치한 통계값</h4>
      {entry.stats.map((stat) => <div className="evidence-stat" key={stat.path}>
        <span>{stat.path}</span><strong>{String(stat.value)}</strong>
      </div>)}
    </section>}
    {entry.gpkg_fields.length > 0 && <section>
      <h4>GPKG 원천 필드</h4>
      <div className="field-chips">{entry.gpkg_fields.map((field) => <code key={field}>{field}</code>)}</div>
    </section>}
    {loading && <div className="evidence-loading"><span className="status-spinner" /> 원본 행 조회 중</div>}
    {!loading && entry.queries.map((query, index) => <section className="evidence-query" key={`${query.sql}-${index}`}>
      <h4><Code2 size={13} /> 실행 SQL</h4>
      <pre>{query.sql}</pre>
      {query.error && <p className="evidence-error">조회 실패: {query.error}</p>}
      {query.columns && <div className="evidence-result"><table><thead><tr>
        {query.columns.map((column) => <th key={column}>{column}</th>)}
      </tr></thead><tbody>
        {(query.rows || []).map((row, rowIndex) => <tr key={rowIndex}>
          {row.map((value, cellIndex) => <td key={cellIndex}>{String(value ?? "—")}</td>)}
        </tr>)}
      </tbody></table></div>}
    </section>)}
  </aside>;
}

const FIGURE_LABELS: Record<string, string> = {
  factor_lift: "요인별 고위험 격자 비교",
  factor_grid_map: "평가항목별 격자 분포",
  grade_dist: "위험등급 분포",
  grade_stack: "요인별 등급 구성",
  region_ranking: "지역별 고위험 비율",
};

function InlineFigures({ figures, jobId }: { figures: Record<string, string>; jobId: string }) {
  const entries = Object.entries(figures);
  const riskMap = entries.find(([key]) => key === "risk_map");
  const charts = entries.filter(([key]) => key !== "risk_map");
  const assetUrl = (path: string) => `/api/reports/${jobId}/assets/${path.replaceAll("\\", "/").split("/").pop()}`;
  const [expanded, setExpanded] = useState<{ label: string; url: string } | null>(null);
  const dialogRef = useDialogKeyboard(() => setExpanded(null), Boolean(expanded));

  return <>
    <div className="inline-visuals">
      {riskMap && <figure className="spatial-figure">
        <img src={assetUrl(riskMap[1])} alt="GPKG 기반 연안재해 위험지도" />
        <figcaption><span><Layers3 size={14} /> GPKG SPATIAL LAYER</span><strong>연안재해 위험도 공간 분포</strong></figcaption>
      </figure>}
      {charts.length > 0 && <div className="chart-strip">{charts.map(([key, path]) => {
        const label = FIGURE_LABELS[key] || key.replaceAll("_", " ");
        const url = assetUrl(path);
        return <figure key={key}>
          <button
            type="button"
            className="chart-preview"
            aria-label={`${label} 크게 보기`}
            onClick={() => setExpanded({ label, url })}
          >
            <img src={url} alt={`${label} 미리보기`} />
            <span className="chart-zoom-hint" aria-hidden="true"><Maximize2 size={14} /> 크게 보기</span>
          </button>
          <figcaption>{label}</figcaption>
        </figure>;
      })}</div>}
    </div>
    {expanded && createPortal(<div
      className="figure-lightbox"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) setExpanded(null);
      }}
    >
      <section ref={dialogRef} className="figure-dialog" role="dialog" aria-modal="true" aria-label={expanded.label}>
        <header>
          <div><small>REPORT VISUAL</small><strong>{expanded.label}</strong></div>
          <button type="button" autoFocus aria-label="확대 그래프 닫기" onClick={() => setExpanded(null)}>
            닫기
          </button>
        </header>
        <div className="figure-dialog-canvas">
          <img src={expanded.url} alt={`${expanded.label} 확대 이미지`} />
        </div>
        <footer><Maximize2 size={15} /> 그래프를 원본 비율로 확대해 표시합니다.</footer>
      </section>
    </div>, document.body)}
  </>;
}

export default App;
