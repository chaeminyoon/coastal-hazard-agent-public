import type { FeatureCollection, Polygon } from "geojson";

export type Region = { name: string; districts: string[] };
export type AuthUser = { id: string; username: string; role: "admin" | "user" };
export type AdminUser = AuthUser & { is_active: boolean; created_at: string };
export type UserSession = {
  id: string;
  current: boolean;
  created_ip: string | null;
  created_at: string;
  expires_at: string;
};
export type AdminReportJob = {
  job_id: string;
  username: string;
  region: string | null;
  status: string;
  stage: string | null;
  progress: number;
  created_at: string;
  updated_at: string;
};
export type AuditLog = {
  id: string;
  user_id: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  details: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
};
export type ChatHistoryItem = { role: "user" | "assistant"; content: string };
export type AnalysisContext = {
  region: string | null;
  grades: string[];
  comparison_regions: string[];
  metric_definition?: "high_risk_ratio" | "high_risk_share" | "average_risk_grade" | "high_risk_concentration";
  selection?: {
    id: string;
    metric: string;
    grades: string[];
    geometry: Polygon;
    ftr_ids?: string[];
  } | null;
};

export type AnalysisHistoryEntry = {
  id: string;
  kind: "query" | "comparison" | "mcp" | "report" | "report_edit";
  title: string;
  region: string | null;
  status: "running" | "completed" | "failed";
  summary: string;
  query_count: number;
  grounded?: boolean | null;
  job_id: string | null;
  created_at: string;
};

export type ConversationSummary = {
  id: string;
  title: string;
  region: string | null;
  summary: string;
  message_count: number;
  created_at: string;
  updated_at: string;
};

export type ConversationSession = {
  id: string;
  title: string;
  region: string | null;
  messages: any[];
  analysis_context: AnalysisContext;
  materials: ReportMaterial[];
  created_at: string;
  updated_at: string;
};

export type QueryResult = {
  question: string;
  region: string | null;
  answer: string;
  queries: string[];
  results: Array<{ columns: string[]; rows: Array<Array<string | number | null>> }>;
  grounded: boolean;
  scope?: {
    type: "spatial_selection";
    selection_id: string;
    selected_count: number;
  } | null;
};

export type MetricDefinition = {
  id: string;
  label: string;
  description: string;
  numerator: string;
  denominator: string;
  unit: string;
  sql: string;
};

export type MetricResolution = {
  ambiguous: boolean;
  selected_metric_id: string | null;
  question?: string;
  choices: MetricDefinition[];
};

export type DataQualityReport = {
  region: string | null;
  row_count: number;
  schema_column_count: number;
  dataset_version: string | null;
  sources: Array<{ name: string; size: number; modified_at: string }>;
  columns: Array<{
    name: string;
    total_count: number;
    missing_count: number;
    missing_pct: number;
    invalid_count: number;
    unit: string | null;
  }>;
  summary: {
    missing_cells: number;
    invalid_grade_cells: number;
    unit_missing_columns: string[];
  };
  capabilities: Record<string, { supported: boolean; reason: string; columns?: string[] }>;
};

export type QueryRequestPayload = {
  question: string;
  region: string | null;
  scope: string;
  history: ChatHistoryItem[];
  analysis_context: AnalysisContext;
};

export type McpChart = {
  chart: string;
  columns: string[];
  reason: string;
  chart_url: string;
  asset_name?: string;
  analysis?: string;
  grounded?: boolean;
  evidence?: QueryResult["results"][number];
};

export type McpAnalysisResult = McpChart & {
  analysis_id: string;
  charts?: McpChart[];
  tool_calls: string[];
  tools_available: number;
  dataset?: {
    source: "query_result" | "duckdb_grid_raw" | "duckdb_selected_grid";
    row_count: number;
    column_count: number;
    query?: string;
    columns?: string[];
    selection?: { id: string; selected_count: number };
  };
};

export type McpChartSpec = {
  chart:
    | "bar"
    | "stacked_bar"
    | "line"
    | "area"
    | "scatter"
    | "histogram"
    | "boxplot"
    | "violin"
    | "correlation_heatmap"
    | "pivot_heatmap";
  x_column?: string;
  y_column?: string;
  group_column?: string;
  stack_column?: string;
  columns?: string[];
  aggregation?: "mean" | "sum" | "count" | "min" | "max" | "median";
  top_n?: number;
  bins?: number;
  normalize?: boolean;
  x_label?: string;
  y_label?: string;
};

export type ComparisonSummary = {
  region: string;
  grid_count: number;
  avg_grade: number | null;
  high_risk_count: number;
  high_risk_pct: number;
};

export type ComparisonResult = {
  regions: string[];
  summary: ComparisonSummary[];
  distribution: Record<string, Array<{ grade: string; count: number; pct: number }>>;
  queries: string[];
  results: QueryResult["results"];
  answer: string;
  grounded: boolean;
};

export type ReportMaterial = Pick<
  QueryResult,
  "question" | "region" | "answer" | "queries" | "results"
> & {
  source_id: string;
  grounded: boolean;
  scope?: QueryResult["scope"];
  spatial_image?: SpatialImageReference;
  mcp_chart?: {
    analysis_id: string;
    asset_name: string;
    caption: string;
    chart: McpChartSpec["chart"];
  };
};

export type SpatialImageReference = {
  image_id: string;
  filename: string;
  caption: string;
};

export type SpatialMapExport = SpatialImageReference & {
  region: string;
  metric: string;
  grades: string[];
  feature_count: number;
  background: "satellite" | "composite" | "transparent";
  extent: "region" | "viewport" | "selection";
  image_url: string;
  download_url: string;
};

export type SpatialAnnotationLayer = {
  id: string;
  name: string;
  feature_count: number;
  geometry_type: string;
  source_crs: string;
  display_crs: string;
  columns: string[];
  suggested_label_field: string;
  geojson: FeatureCollection;
};

export type ReportRevision = {
  revision: number;
  section: string;
  mode?: "direct_edit";
  instruction?: string;
  report_md_path?: string;
};

export type ReportEditQueued = {
  job_id: string;
  task_id: string;
  status: "queued";
};

export type ReportJob = {
  job_id: string;
  status: "queued" | "running" | "cancel_requested" | "cancelled" | "completed" | "failed";
  stage: string | null;
  progress: number;
  result: Record<string, any>;
  errors: string[];
};

export type EvidenceStat = {
  path: string;
  value: string | number | boolean | null;
};

export type EvidenceQuery = {
  sql: string;
  status?: string;
  row_count?: number;
  columns?: string[];
  rows?: Array<Array<string | number | boolean | null>>;
  error?: string;
};

export type ProvenanceEntry = {
  id: string;
  sentence: string;
  grounded: boolean;
  stats: EvidenceStat[];
  gpkg_fields: string[];
  queries: EvidenceQuery[];
  map_context?: {
    region: string | null;
    adm_names: string[];
    grades: string[];
    metric_id: string;
  };
};

export type SpatialLayer = {
  id: string;
  name: string;
  feature_count: number;
  geometry_type: string;
  source_crs: string;
  grade_counts: Record<string, number>;
  metrics: SpatialGradeMetric[];
};

export type SpatialGradeMetric = {
  id: string;
  label: string;
  group: string;
  grade_column: string;
  grade_counts: Record<string, number>;
};

export type SpatialFeatureCollection = FeatureCollection & {
  metadata: {
    count: number;
    truncated: boolean;
    source_crs?: string;
    display_crs?: string;
    metric?: Omit<SpatialGradeMetric, "grade_counts">;
  };
};

export type SpatialSelectionAnalysis = {
  selection_id: string;
  /** 지도에서 실행한 MCP 시각화 결과 — 대화창 카드에 함께 표시 (프런트 전용) */
  mcp?: McpAnalysisResult;
  region: string;
  grades?: string[];
  selected_ftr_ids?: string[];
  metric: Omit<SpatialGradeMetric, "grade_counts">;
  geometry: Polygon;
  stats: {
    selected_count: number;
    average_grade: number | null;
    high_risk_count: number;
    high_risk_pct: number;
    grade_counts: Record<string, number>;
  };
  overlaps: Array<{
    metric_id: string;
    label: string;
    high_risk_count: number;
    high_risk_pct: number;
  }>;
  feature_collection: SpatialFeatureCollection;
  summary: string;
  analysis: {
    narrative: string;
    drivers: Array<{
      factor: string;
      group: string;
      unit: string;
      selected_mean: number;
      region_mean: number;
      selected_high_risk_pct: number;
      region_high_risk_pct: number;
      difference_pct_point: number;
      high_risk_range: [number, number] | null;
    }>;
  };
  report_material: Omit<ReportMaterial, "source_id">;
};

export type SpatialSelectionComparison = {
  region: string;
  metric: Omit<SpatialGradeMetric, "grade_counts">;
  grades: string[];
  area_a: SpatialSelectionAnalysis;
  area_b: SpatialSelectionAnalysis;
  difference: {
    average_grade: number | null;
    high_risk_pct_point: number;
  };
  summary: string;
  report_material: Omit<ReportMaterial, "source_id">;
};

export type SpatialOperationResult = {
  operation_id: string;
  operation: "filter" | "buffer" | "adjacent" | "hotspot" | "query_scope";
  name: string;
  region: string;
  conditions: Array<{
    metric_id: string;
    label: string;
    grade_column: string;
    grades: string[];
  }>;
  stats: {
    feature_count: number;
    cluster_count?: number;
    largest_cluster?: number;
  };
  summary: string;
  feature_collection: SpatialFeatureCollection;
  evidence: { source: string; queries: string[] };
  report_material: Omit<ReportMaterial, "source_id">;
  source_ftr_id?: string;
  distance_m?: number;
  analysis_geometry?: Polygon;
};

export type SpatialScenario = {
  id: string;
  name: string;
  region: string;
  metric: string;
  grades: string[];
  geometry: Polygon;
  latest_result: SpatialSelectionAnalysis | null;
  created_at: string;
  updated_at: string;
  last_run_at: string | null;
};

let csrfToken = "";
let authenticatedUser: AuthUser | null = null;

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

function apiErrorMessage(body: { detail?: unknown }, status: number) {
  const detail = body.detail;
  const messages = Array.isArray(detail)
    ? detail.flatMap((item) => (
      typeof item === "string"
        ? [item]
        : item && typeof item === "object" && "msg" in item && typeof item.msg === "string"
          ? [item.msg]
          : []
    ))
    : [];
  return typeof detail === "string"
    ? detail
    : messages.length
      ? messages.join(" · ")
      : detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string"
        ? detail.message
        : `요청에 실패했습니다. (${status})`;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const multipart = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const headers = new Headers(init?.headers);
  let includeHeaders = init?.headers != null;
  if (!multipart) {
    headers.set("Content-Type", "application/json");
    includeHeaders = true;
  }
  if (csrfToken && ["POST", "PUT", "PATCH", "DELETE"].includes(init?.method || "GET")) {
    headers.set("X-CSRF-Token", csrfToken);
    includeHeaders = true;
  }
  const response = await fetch(url, {
    ...init,
    headers: includeHeaders ? headers : undefined,
    credentials: "same-origin",
  });
  const responseCsrf = response.headers?.get("X-CSRF-Token");
  if (responseCsrf) csrfToken = responseCsrf;
  const encodedUser = response.headers?.get("X-Auth-User");
  if (encodedUser) {
    try {
      authenticatedUser = JSON.parse(decodeURIComponent(encodedUser)) as AuthUser;
    } catch {
      authenticatedUser = null;
    }
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown };
    const message = apiErrorMessage(body, response.status);
    if (response.status === 401 && typeof window !== "undefined") {
      authenticatedUser = null;
      window.dispatchEvent(new Event("coastal:unauthorized"));
    }
    throw new ApiError(message, response.status);
  }
  return response.json();
}

async function streamQuery(
  payload: QueryRequestPayload,
  options: {
    signal?: AbortSignal;
    onStatus?: (message: string) => void;
  } = {},
): Promise<QueryResult> {
  const headers = new Headers({
    "Content-Type": "application/json",
    Accept: "application/x-ndjson",
  });
  if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch("/api/queries", {
    method: "POST",
    body: JSON.stringify(payload),
    headers,
    credentials: "same-origin",
    signal: options.signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown };
    if (response.status === 401 && typeof window !== "undefined") {
      authenticatedUser = null;
      window.dispatchEvent(new Event("coastal:unauthorized"));
    }
    throw new ApiError(apiErrorMessage(body, response.status), response.status);
  }
  const contentType = response.headers?.get("Content-Type") || "";
  if (!contentType.includes("application/x-ndjson") || !response.body) {
    return response.json();
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: QueryResult | null = null;
  const consume = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line) as {
      type: "status" | "result" | "error";
      message?: string;
      data?: QueryResult;
    };
    if (event.type === "status" && event.message) options.onStatus?.(event.message);
    if (event.type === "error") throw new Error(event.message || "데이터 질의에 실패했습니다.");
    if (event.type === "result" && event.data) result = event.data;
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    lines.forEach(consume);
    if (done) break;
  }
  consume(buffer);
  if (!result) throw new Error("데이터 질의 결과를 받지 못했습니다.");
  return result;
}

export const api = {
  authState: () => authenticatedUser,
  clearAuthState: () => {
    csrfToken = "";
    authenticatedUser = null;
  },
  login: async (username: string, password: string) => {
    const result = await request<{ user: AuthUser; csrf_token: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    csrfToken = result.csrf_token;
    authenticatedUser = result.user;
    return result;
  },
  logout: async () => {
    const result = await request<{ logged_out: boolean }>("/api/auth/logout", { method: "POST" });
    csrfToken = "";
    authenticatedUser = null;
    return result;
  },
  changePassword: (current_password: string, new_password: string) =>
    request<{ changed: boolean }>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),
  sessions: () => request<UserSession[]>("/api/auth/sessions"),
  revokeSession: (id: string) => request<{ revoked: boolean }>(
    `/api/auth/sessions/${id}`,
    { method: "DELETE" },
  ),
  adminUsers: () => request<AdminUser[]>("/api/admin/users"),
  adminAuditLogs: () => request<AuditLog[]>("/api/admin/audit-logs"),
  adminReportJobs: () => request<AdminReportJob[]>("/api/admin/report-jobs"),
  createUser: (payload: { username: string; password: string; role: "admin" | "user" }) =>
    request<AuthUser>("/api/admin/users", { method: "POST", body: JSON.stringify(payload) }),
  setUserActive: (id: string, is_active: boolean) => request<AdminUser>(`/api/admin/users/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ is_active }),
  }),
  resetUserPassword: (id: string, new_password: string) =>
    request<{ reset: boolean }>(`/api/admin/users/${id}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ new_password }),
    }),
  regions: () => request<Region[]>("/api/regions"),
  metricDefinitions: () => request<MetricDefinition[]>("/api/metrics/definitions"),
  resolveMetric: (question: string) => request<MetricResolution>("/api/metrics/resolve", {
    method: "POST",
    body: JSON.stringify({ question }),
  }),
  dataQuality: (region?: string | null) => {
    const params = new URLSearchParams();
    if (region) params.set("region", region);
    return request<DataQualityReport>(`/api/data-quality${params.size ? `?${params}` : ""}`);
  },
  history: () => request<AnalysisHistoryEntry[]>("/api/history"),
  conversations: () => request<ConversationSummary[]>("/api/conversations"),
  conversation: (id: string) => request<ConversationSession>(`/api/conversations/${id}`),
  deleteConversation: (id: string) => request<{ id: string; deleted: boolean }>(`/api/conversations/${id}`, {
    method: "DELETE",
  }),
  saveConversation: (id: string, payload: {
    title: string;
    region: string | null;
    messages: any[];
    analysis_context: AnalysisContext;
    materials: ReportMaterial[];
  }) => request<ConversationSession>(`/api/conversations/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  }),
  query: streamQuery,
  compare: (regions: string[]) =>
    request<ComparisonResult>("/api/comparisons", {
      method: "POST",
      body: JSON.stringify({ regions }),
    }),
  mcpGridColumns: (region: string) => {
    const params = new URLSearchParams({ region });
    return request<{ columns: string[] }>(`/api/mcp/grid-columns?${params}`);
  },
  mcpAnalyze: (payload: {
    question: string;
    region?: string;
    columns: string[];
    rows: QueryResult["results"][number]["rows"];
    chart_spec?: McpChartSpec;
    selection?: { id: string; metric: string; grades: string[]; geometry: Polygon };
    use_grid_data?: boolean;
  }) => request<McpAnalysisResult>("/api/mcp/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  createReport: (payload: Record<string, unknown>) =>
    request<{ job_id: string; status: string }>("/api/reports", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  report: (jobId: string) => request<ReportJob>(`/api/reports/${jobId}`),
  cancelReport: (jobId: string) =>
    request<{ job_id: string; status: string }>(`/api/reports/${jobId}/cancel`, {
      method: "POST",
    }),
  retryReport: (jobId: string) =>
    request<{ job_id: string; status: string }>(`/api/reports/${jobId}/retry`, {
      method: "POST",
    }),
  preview: (jobId: string) =>
    request<{ markdown: string }>(`/api/reports/${jobId}/preview`),
  reportContent: (jobId: string) =>
    request<{ markdown: string }>(`/api/reports/${jobId}/content`),
  provenance: (jobId: string) =>
    request<ProvenanceEntry[]>(`/api/reports/${jobId}/provenance`),
  provenanceDetail: (jobId: string, evidenceId: string) =>
    request<ProvenanceEntry>(`/api/reports/${jobId}/provenance/${evidenceId}`),
  revise: (jobId: string, payload: { section: string; instruction: string }) =>
    request<ReportRevision | ReportEditQueued>(`/api/reports/${jobId}/revisions`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  saveReportContent: (jobId: string, markdown: string) =>
    request<ReportRevision | ReportEditQueued>(`/api/reports/${jobId}/content`, {
      method: "PUT",
      body: JSON.stringify({ markdown }),
    }),
  spatialLayer: (region: string) => {
    const params = new URLSearchParams({ region });
    return request<SpatialLayer>(`/api/spatial/layer?${params}`);
  },
  spatialFeatures: (region: string, grades: string[], focusNames: string[] = [], metric = "overall") => {
    // limit 미지정 = 무제한 — 지역의 모든 격자를 표시한다 (강릉 초당동 누락 사례 재발 방지).
    // 대형 시군구(최대 신안군 51,149격자)는 Canvas 렌더러로 그린다.
    const params = new URLSearchParams({ region, metric });
    if (grades.length) params.set("grades", grades.join(","));
    if (focusNames.length) params.set("focus", focusNames.join(","));
    return request<SpatialFeatureCollection>(`/api/spatial/features?${params}`);
  },
  spatialSelection: (payload: {
    region: string;
    metric: string;
    grades: string[];
    geometry: Polygon;
  }) => request<SpatialSelectionAnalysis>("/api/spatial/selections", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  spatialFilter: (payload: { region: string; question: string }) =>
    request<SpatialOperationResult>("/api/spatial/filter", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  spatialNeighborhood: (payload: {
    region: string;
    ftr_id: string;
    distance_m: number;
    metric: string;
    grades: string[];
  }) => request<SpatialOperationResult>("/api/spatial/neighborhood", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  spatialHotspots: (payload: {
    region: string;
    metric: string;
    grades: string[];
    min_cluster_size?: number;
  }) => request<SpatialOperationResult>("/api/spatial/hotspots", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  spatialQueryScope: (payload: { region: string; queries: string[] }) =>
    request<SpatialOperationResult>("/api/spatial/query-scope", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  spatialFeatureExplanation: (region: string, ftrId: string, metric = "overall") => {
    const params = new URLSearchParams({ region, metric });
    return request<SpatialSelectionAnalysis>(
      `/api/spatial/features/${encodeURIComponent(ftrId)}/explanation?${params}`,
    );
  },
  compareSpatialSelections: (payload: {
    region: string;
    metric: string;
    grades: string[];
    geometry_a: Polygon;
    geometry_b: Polygon;
  }) => request<SpatialSelectionComparison>("/api/spatial/selections/compare", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  spatialScenarios: () => request<SpatialScenario[]>("/api/spatial/scenarios"),
  saveSpatialScenario: (payload: {
    name: string;
    region: string;
    metric: string;
    grades: string[];
    geometry: Polygon;
  }) => request<SpatialScenario>("/api/spatial/scenarios", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  runSpatialScenario: (id: string) => request<SpatialSelectionAnalysis>(
    `/api/spatial/scenarios/${id}/run`,
    { method: "POST" },
  ),
  deleteSpatialScenario: (id: string) => request<{ id: string; deleted: boolean }>(
    `/api/spatial/scenarios/${id}`,
    { method: "DELETE" },
  ),
  spatialExport: (payload: {
    region: string;
    metric: string;
    grades: string[];
    focus_names: string[];
    background: "satellite" | "composite" | "transparent";
    extent: "region" | "viewport" | "selection";
    geometry?: Polygon;
  }) => request<SpatialMapExport>("/api/spatial/exports", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  spatialAnnotation: (files: File[]) => {
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    return request<SpatialAnnotationLayer>("/api/spatial/annotations", {
      method: "POST",
      body,
    });
  },
};
