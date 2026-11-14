import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
// @ts-expect-error Vitest runs this regression check in Node; production code does not import node:fs.
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";

import App, { chatDensityForLayout, spatialMaxWidth, SpatialSelectionMessage } from "./App";
import { api } from "./api";

const regions = [{ name: "부산광역시", districts: ["수영구", "해운대구"] }];
const stylesheet = readFileSync("src/styles.css", "utf8");

function response(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body });
}

function errorResponse(body: unknown, status = 422) {
  return Promise.resolve({ ok: false, status, json: async () => body });
}

afterEach(() => {
  cleanup();
  api.clearAuthState();
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("coastal chat workspace", () => {
  it("lets the spatial workspace cover the chat and progressively reduces chat detail", () => {
    expect(spatialMaxWidth(1920)).toBe(1640);
    expect(chatDensityForLayout(1920, 800)).toBe("full");
    expect(chatDensityForLayout(1920, 1100)).toBe("compact");
    expect(chatDensityForLayout(1920, 1400)).toBe("minimal");
    expect(chatDensityForLayout(1920, 1640)).toBe("hidden");
  });

  it("keeps the whole province selected until the user chooses a district", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url === "/api/regions") return response([
        ...regions,
        { name: "전라남도", districts: ["여수시", "목포시"] },
      ]);
      throw new Error(`unexpected request: ${url}`);
    }));
    render(<App />);

    const province = await screen.findByRole("combobox", { name: "시·도" });
    fireEvent.change(province, { target: { value: "전라남도" } });

    expect(screen.getByRole("combobox", { name: "시·군·구" })).toHaveValue("");
  });

  it("asks which denominator to use before an ambiguous high-risk ratio query", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "고위험 비율이 가장 높은 읍면동 5곳을 알려줘",
        region: "부산광역시 수영구",
        answer: "남천2동이 21.4%로 가장 높습니다.",
        queries: ["SELECT 1"],
        results: [],
        grounded: true,
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "고위험 비율이 가장 높은 읍면동 5곳을 알려줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByRole("dialog", { name: "고위험 비율 기준 선택" })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith("/api/queries", expect.anything());
    fireEvent.click(screen.getByRole("button", { name: /읍면동 자체 대비/ }));

    await screen.findByText("남천2동이 21.4%로 가장 높습니다.");
    const queryCall = fetchMock.mock.calls.find(([url]) => url === "/api/queries");
    expect(JSON.parse(String(queryCall?.[1]?.body)).analysis_context.metric_definition)
      .toBe("high_risk_ratio");
  });

  it("links a composite spatial question to filter and SQL-scope layers", async () => {
    const operation = (operationId: string, operation: "filter" | "query_scope", name: string) => ({
      operation_id: operationId,
      operation,
      name,
      region: "부산광역시 수영구",
      conditions: [],
      stats: { feature_count: 2 },
      summary: `${name} 2개 격자`,
      feature_collection: {
        type: "FeatureCollection",
        features: [],
        metadata: { count: 2, truncated: false },
      },
      evidence: { source: "GPKG", queries: ["SELECT * FROM grid"] },
      report_material: {
        question: name, answer: `${name} 2개 격자`, region: "부산광역시 수영구",
        grounded: true, queries: [], results: [],
      },
    });
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "강풍 4·5등급이면서 고령인구 4·5등급 격자를 찾아줘",
        region: "부산광역시 수영구",
        answer: "복합조건 대상 격자를 조회했습니다.",
        queries: ['SELECT * FROM grid WHERE "강풍_등급" IN (4, 5)'],
        results: [],
        grounded: true,
      });
      if (url === "/api/spatial/filter") return response(operation("filter-1", "filter", "복합필터 · 강풍·고령인구"));
      if (url === "/api/spatial/query-scope") return response(operation("scope-1", "query_scope", "질문에 사용된 데이터 조회 범위"));
      if (url === "/api/spatial/scenarios") return response([]);
      if (url.startsWith("/api/spatial/layer?")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 4,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: {},
        metrics: [{ id: "overall", label: "종합 위험", group: "종합", grade_column: "위험성지수_등급", grade_counts: {} }],
      });
      if (url.startsWith("/api/spatial/features?")) return response({
        type: "FeatureCollection", features: [], metadata: { count: 0, truncated: false },
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "강풍 4·5등급이면서 고령인구 4·5등급 격자를 찾아줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByText("복합필터 · 강풍·고령인구")).toBeInTheDocument();
    expect(screen.getByText("질문에 사용된 데이터 조회 범위")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/spatial/filter",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("keeps a grounded GPKG filter result when the natural-language SQL request fails", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return errorResponse({ detail: "LLM SQL 생성 실패" }, 503);
      if (url === "/api/spatial/filter") return response({
        operation_id: "filter-fallback",
        operation: "filter",
        name: "복합필터 · 강풍·고령인구",
        region: "부산광역시 수영구",
        conditions: [],
        stats: { feature_count: 2 },
        summary: "복합조건을 만족하는 격자는 2개입니다.",
        feature_collection: {
          type: "FeatureCollection", features: [], metadata: { count: 2, truncated: false },
        },
        evidence: { source: "GPKG", queries: ["GPKG 속성필터"] },
        report_material: {
          question: "복합필터", answer: "복합조건을 만족하는 격자는 2개입니다.",
          region: "부산광역시 수영구", grounded: true,
          queries: ["GPKG 속성필터"], results: [],
        },
      });
      if (url === "/api/spatial/scenarios") return response([]);
      if (url.startsWith("/api/spatial/layer?")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 4,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: {},
        metrics: [{ id: "overall", label: "종합 위험", group: "종합", grade_column: "위험성지수_등급", grade_counts: {} }],
      });
      if (url.startsWith("/api/spatial/features?")) return response({
        type: "FeatureCollection", features: [], metadata: { count: 0, truncated: false },
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "강풍 4·5등급이면서 고령인구 4·5등급 격자를 찾아줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect((await screen.findAllByText("복합조건을 만족하는 격자는 2개입니다.")).length)
      .toBeGreaterThan(0);
    expect(screen.queryByText("LLM SQL 생성 실패")).not.toBeInTheDocument();
  });

  it("consumes streamed query progress and renders the grounded result", async () => {
    const queryResult = {
      question: "고위험 지역을 알려줘",
      region: "부산광역시 수영구",
      answer: "남천2동의 고위험 비율이 가장 높습니다.",
      queries: ["SELECT 21.4 AS high_pct"],
      results: [{ columns: ["지역", "고위험비율"], rows: [["남천2동", 21.4]] }],
      grounded: true,
    };
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") {
        return Promise.resolve(new Response(
          [
            JSON.stringify({ type: "status", message: "원자료를 집계하고 있습니다." }),
            JSON.stringify({ type: "result", data: queryResult }),
          ].join("\n") + "\n",
          { headers: { "Content-Type": "application/x-ndjson" } },
        ));
      }
      throw new Error(`unexpected request: ${url}`);
    }));
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "고위험 지역을 알려줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByText("남천2동의 고위험 비율이 가장 높습니다."))
      .toBeInTheDocument();
  });

  it("lets the user stop a long-running data query", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") {
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        });
      }
      throw new Error(`unexpected request: ${url}`);
    }));
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "고위험 지역을 오래 분석해줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    fireEvent.click(await screen.findByRole("button", { name: "질의 중단" }));

    expect(await screen.findByText("질의를 중단했습니다.")).toBeInTheDocument();
  });

  it("retries a failed query and copies its answer with SQL", async () => {
    let queryAttempts = 0;
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const queryResult = {
      question: "고위험 지역을 알려줘",
      region: "부산광역시 수영구",
      answer: "남천2동이 가장 높습니다.",
      queries: ["SELECT '남천2동' AS name"],
      results: [{ columns: ["지역"], rows: [["남천2동"]] }],
      grounded: true,
    };
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") {
        queryAttempts += 1;
        return queryAttempts === 1
          ? errorResponse({ detail: "일시적인 조회 오류" }, 503)
          : response(queryResult);
      }
      throw new Error(`unexpected request: ${url}`);
    }));
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "고위험 지역을 알려줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    fireEvent.click(await screen.findByRole("button", { name: "질의 다시 시도" }));
    expect(await screen.findByText("남천2동이 가장 높습니다.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "답변과 SQL 복사" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(
      "남천2동이 가장 높습니다.\n\nSQL\nSELECT '남천2동' AS name",
    ));
    expect(screen.getByRole("status")).toHaveTextContent("답변과 SQL을 복사했습니다.");
  });

  it("shows raw-value drivers in a selected-grid chat analysis", () => {
    render(<SpatialSelectionMessage
      result={{
        selection_id: "selection-1",
        region: "부산광역시 수영구",
        metric: { id: "overall", label: "종합 위험", group: "종합", grade_column: "위험성지수_등급" },
        geometry: { type: "Polygon", coordinates: [[[129.1, 35.1], [129.2, 35.1], [129.1, 35.1]]] },
        stats: { selected_count: 12, average_grade: 4.2, high_risk_count: 9, high_risk_pct: 75, grade_counts: { "5": 9 } },
        overlaps: [],
        feature_collection: { type: "FeatureCollection", features: [], metadata: { count: 12, truncated: false } },
        summary: "선택 격자 12개를 분석했습니다.",
        analysis: {
          narrative: "강풍 원자료 평균 25.00m/s이며 지역 전체 평균은 18.33m/s입니다.",
          drivers: [{
            factor: "강풍", group: "위해성", unit: "m/s", selected_mean: 25,
            region_mean: 18.33, selected_high_risk_pct: 100, region_high_risk_pct: 66.7,
            difference_pct_point: 33.3, high_risk_range: [20, 30],
          }],
        },
        report_material: {
          question: "선택 영역",
          answer: "분석",
          region: "부산광역시 수영구",
          grounded: true,
          queries: [],
          results: [],
        },
      }}
      materialSelected={false}
      onToggleMaterial={vi.fn()}
      onOpenMap={vi.fn()}
    />);

    expect(screen.getByText(/강풍 원자료 평균 25.00m\/s/)).toBeInTheDocument();
    expect(screen.getByText("25m/s")).toBeInTheDocument();
    expect(screen.getByText("지역 평균 18.33m/s")).toBeInTheDocument();
    expect(screen.getByText("+33.3%p")).toBeInTheDocument();
  });

  it("prompts for login after a 401 response and opens the workspace", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions" && fetchMock.mock.calls.filter(([value]) => value === "/api/regions").length === 1) {
        return errorResponse({ detail: "로그인이 필요합니다." }, 401);
      }
      if (url === "/api/auth/login") return response({
        user: { id: "admin-1", username: "coastal-admin", role: "admin" },
        csrf_token: "csrf-token",
      });
      if (url === "/api/regions") return response(regions);
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    expect(await screen.findByRole("heading", { name: "관리자 로그인" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Coastal" })).toHaveAttribute("src", `data:image/svg+xml;base64,${btoa(readFileSync("src/assets/coastal-wordmark.svg", "utf8"))}`);
    fireEvent.change(screen.getByLabelText("아이디"), { target: { value: "coastal-admin" } });
    fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "admin-password" } });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));

    expect(await screen.findByRole("heading", { name: "연안재해 에이전트" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "시·도" })).toHaveValue("");
    expect(screen.queryByRole("combobox", { name: "시·군·구" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({ method: "POST", credentials: "same-origin" }),
    );
  });

  it("keeps the active workspace mounted while an expired session is reauthenticated", async () => {
    let regionRequests = 0;
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") {
        regionRequests += 1;
        return regionRequests === 1
          ? errorResponse({ detail: "로그인이 필요합니다." }, 401)
          : response(regions);
      }
      if (url === "/api/auth/login") return response({
        user: { id: "admin-1", username: "coastal-admin", role: "admin" },
        csrf_token: "csrf-token",
      });
      if (url === "/api/queries") return response({
        question: "현재 분석을 유지해줘",
        region: "부산광역시 수영구",
        answer: "현재 분석 결과입니다.",
        queries: ["SELECT 1"],
        results: [],
        grounded: true,
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findByRole("heading", { name: "관리자 로그인" });
    fireEvent.change(screen.getByLabelText("아이디"), { target: { value: "coastal-admin" } });
    fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "admin-password" } });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));
    await screen.findByRole("heading", { name: "연안재해 에이전트" });

    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "현재 분석을 유지해줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    await screen.findByText("현재 분석 결과입니다.");

    act(() => window.dispatchEvent(new Event("coastal:unauthorized")));

    expect(await screen.findByRole("dialog", { name: "세션 재인증" })).toBeInTheDocument();
    expect(screen.getByText("현재 분석 결과입니다.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("아이디"), { target: { value: "coastal-admin" } });
    fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "admin-password" } });
    fireEvent.click(screen.getByRole("button", { name: "다시 로그인" }));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "세션 재인증" })).not.toBeInTheDocument());
    expect(screen.getByText("현재 분석 결과입니다.")).toBeInTheDocument();
  });

  it("lets an admin create and disable users from the account panel", async () => {
    const users = [{
      id: "user-1",
      username: "analyst",
      role: "user",
      is_active: true,
      created_at: "2026-07-20T01:00:00+00:00",
    }];
    let regionRequests = 0;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") {
        regionRequests += 1;
        return regionRequests === 1
          ? errorResponse({ detail: "로그인이 필요합니다." }, 401)
          : response(regions);
      }
      if (url === "/api/auth/login") return response({
        user: { id: "admin-1", username: "coastal-admin", role: "admin" },
        csrf_token: "csrf-token",
      });
      if (url === "/api/admin/users" && !init?.method) return response(users);
      if (url === "/api/admin/audit-logs" && !init?.method) return response([{
        id: "audit-1",
        user_id: "admin-1",
        action: "auth.login.succeeded",
        resource_type: "user",
        resource_id: "admin-1",
        details: {},
        ip_address: "127.0.0.1",
        created_at: "2026-07-20T01:05:00+00:00",
      }]);
      if (url === "/api/admin/report-jobs" && !init?.method) return response([{
        job_id: "job-1",
        username: "analyst",
        region: "부산광역시 수영구",
        status: "running",
        stage: "analyze",
        progress: 2,
        created_at: "2026-07-20T01:06:00+00:00",
        updated_at: "2026-07-20T01:07:00+00:00",
      }]);
      if (url.startsWith("/api/data-quality")) return response({
        region: "부산광역시 수영구",
        row_count: 443,
        schema_column_count: 102,
        dataset_version: "dataset-v1",
        sources: [{
          name: "본평가_평가완료_시각화.gpkg",
          size: 1024,
          modified_at: "2026-07-31T01:30:00+00:00",
        }],
        columns: [{
          name: "인구_원자료", total_count: 443, missing_count: 74,
          missing_pct: 16.7, invalid_count: 0, unit: "명",
        }],
        summary: { missing_cells: 74, invalid_grade_cells: 0, unit_missing_columns: [] },
        capabilities: {
          time_series: { supported: false, reason: "현재 원자료에 시간 컬럼이 없습니다." },
          spatial_impact: { supported: true, reason: "원자료 연결 상태" },
          scheduled_monitoring: { supported: false, reason: "2개 시점의 데이터가 필요합니다." },
        },
      });
      if (url === "/api/admin/users" && init?.method === "POST") return response({
        id: "user-2", username: "reviewer", role: "user",
      });
      if (url === "/api/admin/users/user-1" && init?.method === "PATCH") return response({
        ...users[0], is_active: false,
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findByRole("heading", { name: "관리자 로그인" });
    fireEvent.change(screen.getByLabelText("아이디"), { target: { value: "coastal-admin" } });
    fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "admin-password" } });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));
    await screen.findByRole("heading", { name: "연안재해 에이전트" });

    expect(screen.getByRole("button", { name: "공간분석 표시" })).toHaveClass("header-control");
    expect(screen.getByRole("button", { name: "계정 메뉴 열기" })).toHaveClass("header-control");
    expect(document.querySelector(".region-picker")).toHaveClass("header-control");

    fireEvent.click(screen.getByRole("button", { name: "계정 메뉴 열기" }));
    fireEvent.click(screen.getByRole("button", { name: "사용자 관리" }));
    expect(await screen.findByRole("dialog", { name: "사용자 관리" })).toBeInTheDocument();
    expect(screen.getAllByText("analyst")).toHaveLength(2);
    expect(await screen.findByText("로그인 성공")).toBeInTheDocument();
    expect(await screen.findByText("job-1")).toBeInTheDocument();
    expect(await screen.findByText("데이터 품질 진단")).toBeInTheDocument();
    expect(screen.getByText("16.7%")).toBeInTheDocument();
    expect(screen.getByText("최근 자료 갱신")).toBeInTheDocument();
    expect(screen.getByText(/2026\. 7\. 31/)).toBeInTheDocument();
    expect(screen.getByText("현재 원자료에 시간 컬럼이 없습니다.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("새 사용자 아이디"), { target: { value: "reviewer" } });
    fireEvent.change(screen.getByLabelText("임시 비밀번호"), { target: { value: "reviewer-password" } });
    fireEvent.click(screen.getByRole("button", { name: "계정 추가" }));
    await screen.findByText("reviewer");

    fireEvent.click(screen.getByRole("button", { name: "analyst 계정 비활성화" }));
    await screen.findByText("비활성", { selector: ".admin-user-status" });
  });

  it("lets a signed-in user change the password and revoke sessions", async () => {
    let changedPayload: Record<string, unknown> | null = null;
    let revokedSession = "";
    let regionRequests = 0;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") {
        regionRequests += 1;
        return regionRequests === 1
          ? errorResponse({ detail: "로그인이 필요합니다." }, 401)
          : response(regions);
      }
      if (url === "/api/auth/login") return response({
        user: { id: "user-1", username: "analyst", role: "user" },
        csrf_token: "csrf-token",
      });
      if (url === "/api/auth/sessions") return response([
        {
          id: "current-session", current: true, created_ip: "192.168.2.10",
          created_at: "2026-07-31T01:00:00+00:00",
          expires_at: "2026-07-31T09:00:00+00:00",
        },
        {
          id: "other-session", current: false, created_ip: "192.168.2.11",
          created_at: "2026-07-31T02:00:00+00:00",
          expires_at: "2026-07-31T10:00:00+00:00",
        },
      ]);
      if (url === "/api/auth/change-password" && init?.method === "POST") {
        changedPayload = JSON.parse(String(init.body));
        return response({ changed: true });
      }
      if (url === "/api/auth/sessions/other-session" && init?.method === "DELETE") {
        revokedSession = "other-session";
        return response({ revoked: true });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findByRole("heading", { name: "관리자 로그인" });
    fireEvent.change(screen.getByLabelText("아이디"), { target: { value: "analyst" } });
    fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "current-password" } });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));
    await screen.findByRole("heading", { name: "연안재해 에이전트" });

    fireEvent.click(screen.getByRole("button", { name: "계정 메뉴 열기" }));
    fireEvent.click(screen.getByRole("button", { name: "계정 설정" }));
    const dialog = await screen.findByRole("dialog", { name: "계정 설정" });
    fireEvent.change(within(dialog).getByLabelText("현재 비밀번호"), { target: { value: "current-password" } });
    fireEvent.change(within(dialog).getByLabelText("새 비밀번호"), { target: { value: "updated-password" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "비밀번호 변경" }));
    await waitFor(() => expect(changedPayload).toEqual({
      current_password: "current-password",
      new_password: "updated-password",
    }));
    fireEvent.click(within(dialog).getByRole("button", { name: "192.168.2.11 세션 종료" }));
    await waitFor(() => expect(revokedSession).toBe("other-session"));
  });

  it("opens and closes the primary navigation from the compact header", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response(regions)));
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    const navigation = screen.getByLabelText("주요 탐색");
    const toggle = screen.getByRole("button", { name: "메뉴 열기" });

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(navigation).not.toHaveClass("mobile-open");
    fireEvent.click(toggle);

    expect(navigation).toHaveClass("mobile-open");
    const close = screen.getByRole("button", { name: "탐색 닫기" });
    fireEvent.click(close);

    expect(navigation).not.toHaveClass("mobile-open");
  });

  it("restores a saved conversation session and continues with its context", async () => {
    let queryPayload: Record<string, unknown> | null = null;
    const savedQuery = {
      question: "수영구 고위험 지역을 알려줘",
      region: "부산광역시 수영구",
      answer: "남천2동의 고위험 비율이 가장 높습니다.",
      queries: ["SELECT * FROM grid"],
      results: [{ columns: ["지역"], rows: [["남천2동"]] }],
      grounded: true,
    };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/conversations") return response([{
        id: "session-1",
        title: "수영구 고위험 지역을 알려줘",
        region: "부산광역시 수영구",
        summary: "남천2동의 고위험 비율이 가장 높습니다.",
        message_count: 2,
        created_at: "2026-07-14T14:30:00+00:00",
        updated_at: "2026-07-14T14:31:00+00:00",
      }]);
      if (url === "/api/conversations/session-1" && !init?.method) return response({
        id: "session-1",
        title: "수영구 고위험 지역을 알려줘",
        region: "부산광역시 수영구",
        messages: [
          { id: "saved-user", role: "user", kind: "text", text: "수영구 고위험 지역을 알려줘" },
          { id: "saved-answer", role: "assistant", kind: "query", query: savedQuery },
        ],
        analysis_context: {
          region: "부산광역시 수영구",
          grades: ["5"],
          comparison_regions: [],
          selection: {
            id: "selection-1",
            metric: "overall",
            grades: ["4", "5"],
            geometry: {
              type: "Polygon",
              coordinates: [[[129.1, 35.1], [129.2, 35.1], [129.1, 35.1]]],
            },
            ftr_ids: ["G1", "G2"],
          },
        },
        materials: [],
        created_at: "2026-07-14T14:30:00+00:00",
        updated_at: "2026-07-14T14:31:00+00:00",
      });
      if (url === "/api/queries") {
        queryPayload = JSON.parse(String(init?.body));
        return response({ ...savedQuery, question: "그중 노출성이 높은 곳은?" });
      }
      if (url.startsWith("/api/conversations/") && init?.method === "PUT") return response({ id: "session-1" });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.click(screen.getByRole("button", { name: "분석 작업 이력 열기" }));

    const historyPanel = await screen.findByRole("dialog", { name: "분석 작업 이력" });
    expect(historyPanel).toBeInTheDocument();
    expect(historyPanel).toHaveClass("left-drawer");
    expect(screen.getByText("수영구 고위험 지역을 알려줘")).toBeInTheDocument();
    expect(screen.getByText("남천2동의 고위험 비율이 가장 높습니다.")).toBeInTheDocument();
    expect(screen.getByText("메시지 2개")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "대화 이어서 열기" }));

    await waitFor(() => expect(
      screen.queryByRole("dialog", { name: "분석 작업 이력" }),
    ).not.toBeInTheDocument());
    expect(screen.getByText("남천2동의 고위험 비율이 가장 높습니다.")).toBeInTheDocument();
    const composer = screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요");
    fireEvent.change(composer, { target: { value: "그중 노출성이 높은 곳은?" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    await waitFor(() => expect(queryPayload).not.toBeNull());
    expect(queryPayload).toMatchObject({
      history: [
        { role: "user", content: "수영구 고위험 지역을 알려줘" },
        { role: "assistant", content: "남천2동의 고위험 비율이 가장 높습니다." },
      ],
      analysis_context: {
        grades: ["5"],
        selection: expect.objectContaining({
          id: "selection-1",
          metric: "overall",
        }),
      },
    });
    expect(
      ((queryPayload as unknown as {
        analysis_context: { selection: Record<string, unknown> };
      })
        .analysis_context.selection),
    ).not.toHaveProperty("ftr_ids");
  });

  it("resumes the last conversation and reconnects an active report after reload", async () => {
    localStorage.setItem("coastal:last-conversation:admin-1", "session-last");
    localStorage.setItem("coastal:last-region:admin-1", "부산광역시 해운대구");
    const eventSourceUrls: string[] = [];
    let regionRequests = 0;
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") {
        regionRequests += 1;
        return regionRequests === 1
          ? errorResponse({ detail: "로그인이 필요합니다." }, 401)
          : response(regions);
      }
      if (url === "/api/auth/login") return response({
        user: { id: "admin-1", username: "coastal-admin", role: "admin" },
        csrf_token: "csrf-token",
      });
      if (url === "/api/conversations/session-last") return response({
        id: "session-last",
        title: "해운대구 보고서",
        region: "부산광역시 해운대구",
        messages: [
          { id: "saved-user", role: "user", kind: "text", text: "해운대구 보고서를 작성해줘" },
          {
            id: "saved-report",
            role: "assistant",
            kind: "report",
            report: {
              job_id: "job-running",
              status: "running",
              stage: "analyze",
              progress: 2,
              result: {},
              errors: [],
            },
          },
        ],
        analysis_context: {
          region: "부산광역시 해운대구",
          grades: [],
          comparison_regions: [],
        },
        materials: [],
        created_at: "2026-07-31T01:00:00+00:00",
        updated_at: "2026-07-31T01:10:00+00:00",
      });
      if (url === "/api/reports/job-running") return response({
        job_id: "job-running",
        status: "running",
        stage: "visualize",
        progress: 3,
        result: {},
        errors: [],
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      constructor(url: string) {
        eventSourceUrls.push(url);
      }
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findByRole("heading", { name: "관리자 로그인" });
    fireEvent.change(screen.getByLabelText("아이디"), { target: { value: "coastal-admin" } });
    fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "admin-password" } });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));

    expect(await screen.findByText("해운대구 보고서를 작성해줘")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/reports/job-running",
      expect.anything(),
    ));
    expect(eventSourceUrls).toEqual(["/api/reports/job-running/events"]);
    expect(screen.getByRole("combobox", { name: "시·군·구" })).toHaveValue("해운대구");
    expect(document.querySelector(".chat-app")).toHaveStyle("--spatial-width: 640px");
  });

  it("confirms and deletes a saved conversation from analysis history", async () => {
    let deleteCount = 0;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/conversations") return response([{
        id: "session-delete",
        title: "수영구 고위험 지역",
        region: "부산광역시 수영구",
        summary: "남천2동 고위험 격자 조회",
        message_count: 2,
        created_at: "2026-07-14T14:30:00+00:00",
        updated_at: "2026-07-14T14:31:00+00:00",
      }]);
      if (url === "/api/conversations/session-delete" && init?.method === "DELETE") {
        deleteCount += 1;
        return response({ id: "session-delete", deleted: true });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.click(screen.getByRole("button", { name: "분석 작업 이력 열기" }));
    await screen.findByText("수영구 고위험 지역");
    expect(screen.queryByText("대화 세션", { selector: ".history-entry-top span" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "대화 삭제" }));
    expect(deleteCount).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "대화 삭제 확인" }));

    await waitFor(() => expect(deleteCount).toBe(1));
    expect(screen.queryByText("수영구 고위험 지역")).not.toBeInTheDocument();
    expect(screen.getByText("아직 저장된 대화 세션이 없습니다.")).toBeInTheDocument();
  });

  it("closes the analysis history dialog with Escape", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/conversations") return response([]);
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.click(screen.getByRole("button", { name: "분석 작업 이력 열기" }));
    expect(await screen.findByRole("dialog", { name: "분석 작업 이력" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "분석 작업 이력" })).not.toBeInTheDocument();
  });

  it("centers the interface on one conversational composer", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response(regions)));

    render(<App />);

    expect(screen.getByRole("img", { name: "Coastal" })).toHaveAttribute("src", `data:image/svg+xml;base64,${btoa(readFileSync("src/assets/coastal-wordmark.svg", "utf8"))}`);
    expect(screen.getByRole("heading", { name: "연안재해 에이전트" })).toBeInTheDocument();
    expect(screen.queryByText("COASTLINE")).not.toBeInTheDocument();
    expect(screen.queryByText("DATA INTELLIGENCE")).not.toBeInTheDocument();
    expect(screen.queryByText("LIVE ANALYSIS SESSION")).not.toBeInTheDocument();
    expect(screen.queryByText("실제 데이터에 연결됨")).not.toBeInTheDocument();
    expect(document.querySelector(".assistant-orb")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "/보고서작성" })).toBeInTheDocument();
    expect((await screen.findAllByText("부산광역시 수영구")).length).toBeGreaterThan(0);
  });

  it("keeps the navigation pane fixed and uses the agent name", () => {
    vi.stubGlobal("fetch", vi.fn(() => response(regions)));
    render(<App />);

    expect(screen.queryByRole("separator", { name: "좌측 탐색창 너비 조절" })).not.toBeInTheDocument();
    expect(screen.getByText("연안재해 에이전트", { selector: ".thread-item" })).toBeInTheDocument();
  });

  it("keeps sidebar icons and the Coastal brand refresh link", () => {
    vi.stubGlobal("fetch", vi.fn(() => response(regions)));
    render(<App />);

    const navigation = screen.getByLabelText("주요 탐색");
    const icon = navigation.querySelector(".lucide") as SVGElement;
    expect(icon).toBeInTheDocument();
    expect(getComputedStyle(icon).display).not.toBe("none");
    expect(screen.getByRole("link", { name: "연안재해 에이전트 새로고침" })).toHaveAttribute("href", "/");
  });

  it("keeps functional icons visible outside the navigation pane", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response(regions)));
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    const icon = document.querySelector(".composer-sources .lucide") as SVGElement;
    expect(icon).toBeInTheDocument();
    expect(getComputedStyle(icon).display).not.toBe("none");
  });

  it("keeps icons visible while restoring global accessible typography", () => {
    expect(stylesheet).toContain("Accessible typography");
    expect(stylesheet).not.toMatch(/\.lucide\s*\{[^}]*display\s*:\s*none/i);
    expect(stylesheet).toMatch(/body\s*\*\s*\{[^}]*font-size:\s*16px\s*!important/is);
  });

  it("uses equal left-aligned region fields and removes district qualifiers from labels", async () => {
    let queryPayload: Record<string, unknown> | null = null;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response([{
        name: "부산광역시",
        districts: ["수영구", "남구(부산)", "동구(부산)"],
      }]);
      if (url === "/api/queries") {
        queryPayload = JSON.parse(String(init?.body));
        return response({
          question: "전국 위험도를 알려줘",
          region: null,
          answer: "전국 위험도를 조회했습니다.",
          queries: ["SELECT avg(score) FROM grid"],
          results: [{ columns: ["avg_score"], rows: [[52.1]] }],
          grounded: true,
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    const sidoSelect = await screen.findByLabelText("시·도");
    expect(within(sidoSelect).getByRole("option", { name: "전국" })).toBeInTheDocument();
    expect(sidoSelect).toHaveClass("region-select");
    expect(sidoSelect).not.toHaveClass("centered-value");
    const picker = document.querySelector(".region-picker");
    expect(picker).toHaveClass("equal-columns");
    expect(picker?.children).toHaveLength(2);
    expect(picker?.querySelector(":scope > svg")).not.toBeInTheDocument();
    const districtSelect = screen.getByLabelText("시·군·구");
    expect(districtSelect).toHaveClass("region-select");
    expect(within(districtSelect).getByRole("option", { name: "남구" })).toHaveValue("남구(부산)");
    expect(within(districtSelect).queryByRole("option", { name: "남구(부산)" })).not.toBeInTheDocument();
    fireEvent.change(sidoSelect, { target: { value: "" } });
    expect(screen.queryByLabelText("시·군·구")).not.toBeInTheDocument();
    expect(document.querySelector(".welcome-status b")).toHaveTextContent("전국");

    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "전국 위험도를 알려줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    await screen.findByText("전국 위험도를 조회했습니다.");
    expect(queryPayload).toMatchObject({ region: null, scope: "national" });
  });

  it("replaces the metric dictionary with a practical usage guide", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      throw new Error(`unexpected request: ${url}`);
    }));
    render(<App />);

    const guideButton = await screen.findByRole("button", { name: "사용 방법 열기" });
    expect(screen.queryByRole("button", { name: "지표 정의 사전 열기" })).not.toBeInTheDocument();
    fireEvent.click(guideButton);

    const guide = screen.getByRole("dialog", { name: "연안재해 에이전트 사용 방법" });
    expect(within(guide).getByText("질문에서 보고서까지, 8단계 실무 가이드")).toBeInTheDocument();
    expect(within(guide).getByRole("navigation", { name: "사용 방법 목차" })).toBeInTheDocument();
    expect(within(guide).getByRole("heading", { name: "1. 지역과 분석 범위 설정" })).toBeInTheDocument();
    expect(within(guide).getByRole("heading", { name: "4. 공간분석 지도 사용" })).toBeInTheDocument();
    expect(within(guide).getByRole("heading", { name: "7. 보고서 자료 수집과 작성" })).toBeInTheDocument();
    expect(within(guide).getByRole("heading", { name: "8. 검토·근거·다운로드·이력" })).toBeInTheDocument();
    expect(within(guide).getAllByRole("img").length).toBeGreaterThanOrEqual(8);
    expect(within(guide).getAllByText("/보고서작성").length).toBeGreaterThan(0);
  });

  it("starts a report from the slash command", async () => {
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => response(regions))
      .mockImplementationOnce(() => response({ job_id: "job-1", status: "queued" }))
      .mockImplementationOnce(() => response({
        job_id: "job-1",
        status: "queued",
        stage: null,
        progress: 0,
        result: {},
        errors: [],
      }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "/보고서 작성" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/reports",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          region: "부산광역시 수영구",
          use_llm: true,
          use_judge: true,
          make_hwpx: true,
        }),
      }),
    ));
    expect(await screen.findByText("작성 중")).toBeInTheDocument();
  });

  it("asks for confirmation before a natural-language report request", async () => {
    let reportRequests = 0;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        reportRequests += 1;
        return response({ job_id: "job-confirmed", status: "queued" });
      }
      if (url === "/api/reports/job-confirmed") return response({
        job_id: "job-confirmed", status: "queued", stage: null, progress: 0,
        result: {}, errors: [],
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    const composer = screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요");
    fireEvent.change(composer, { target: { value: "지금까지 내용을 보고서로 만들어줘" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByRole("dialog", { name: "보고서 작성 설정" })).toBeInTheDocument();
    expect(screen.getByText("보고서를 생성할까요?")).toBeInTheDocument();
    expect(reportRequests).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: "보고서 생성" }));
    await waitFor(() => expect(reportRequests).toBe(1));
  });

  it("drags the report setup dialog by its header and keeps it inside the viewport", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      throw new Error(`unexpected request: ${url}`);
    }));
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    const composer = screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요");
    fireEvent.change(composer, { target: { value: "지금까지 내용을 보고서로 만들어줘" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    const dialog = await screen.findByRole("dialog", { name: "보고서 작성 설정" });
    const header = dialog.querySelector("header");
    expect(header).not.toBeNull();
    vi.spyOn(dialog, "getBoundingClientRect").mockReturnValue({
      x: 200,
      y: 100,
      left: 200,
      right: 800,
      top: 100,
      bottom: 600,
      width: 600,
      height: 500,
      toJSON: () => ({}),
    });

    const closeButton = within(dialog).getByRole("button", { name: "보고서 작성 설정 닫기" });
    fireEvent.pointerDown(closeButton, { button: 0, pointerId: 6, clientX: 780, clientY: 120 });
    expect(dialog).not.toHaveClass("is-dragging");
    fireEvent.pointerUp(window, { pointerId: 6 });

    fireEvent.pointerDown(header as HTMLElement, { button: 0, pointerId: 7, clientX: 400, clientY: 200 });
    expect(dialog).toHaveClass("is-dragging");
    fireEvent.pointerMove(window, { pointerId: 7, clientX: 520, clientY: 280 });
    expect(dialog).toHaveStyle({ transform: "translate3d(120px, 80px, 0)" });

    fireEvent.pointerMove(window, { pointerId: 7, clientX: 1400, clientY: 1200 });
    expect(dialog).toHaveStyle({ transform: "translate3d(216px, 160px, 0)" });
    fireEvent.pointerUp(window, { pointerId: 7 });
    expect(dialog).not.toHaveClass("is-dragging");
  });

  it("keeps report actions visible while long setup content scrolls", () => {
    expect(stylesheet).toMatch(
      /\.report-setup-dialog\s*\{[^}]*grid-template-rows:\s*auto minmax\(0,\s*1fr\) auto;[^}]*height:\s*min\(820px,\s*92vh\)/s,
    );
    expect(stylesheet).toMatch(
      /\.report-setup-content\s*\{[^}]*overflow-y:\s*auto;[^}]*overscroll-behavior:\s*contain;[^}]*scrollbar-gutter:\s*stable;/s,
    );
  });

  it("reviews report materials and applies generation options", async () => {
    let reportPayload: Record<string, unknown> | null = null;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "5등급 격자는 몇 개인가?",
        region: "부산광역시 수영구",
        answer: "5등급 격자는 13개입니다.",
        queries: ["SELECT 13 AS count"],
        results: [{ columns: ["격자수"], rows: [[13]] }],
        grounded: true,
      });
      if (url === "/api/reports" && init?.method === "POST") {
        reportPayload = JSON.parse(String(init.body));
        return response({ job_id: "job-options", status: "queued" });
      }
      if (url === "/api/reports/job-options") return response({
        job_id: "job-options", status: "queued", stage: null, progress: 0,
        result: {}, errors: [],
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    const composer = screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요");
    fireEvent.change(composer, { target: { value: "5등급 격자는 몇 개인가?" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    fireEvent.click(await screen.findByRole("button", { name: "보고서에 추가" }));

    fireEvent.click(screen.getByRole("button", { name: "보고서 자료 바구니 열기" }));
    const dialog = await screen.findByRole("dialog", { name: "보고서 작성 설정" });
    expect(within(dialog).getByText("5등급 격자는 몇 개인가?")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByLabelText("HWPX 생성"));
    fireEvent.click(within(dialog).getByRole("button", { name: "보고서 생성" }));

    await waitFor(() => expect(reportPayload).not.toBeNull());
    expect(reportPayload).toEqual(expect.objectContaining({
      use_llm: true,
      use_judge: true,
      make_hwpx: false,
      materials: [expect.objectContaining({
        question: "5등급 격자는 몇 개인가?",
        queries: ["SELECT 13 AS count"],
      })],
    }));
  });

  it("does not force the chat scroll position when a report stage is refreshed", async () => {
    const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView");
    let stageCompleted: (() => void) | undefined;
    let reportReads = 0;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        return response({ job_id: "job-scroll", status: "queued" });
      }
      if (url === "/api/reports/job-scroll") {
        reportReads += 1;
        return response({
          job_id: "job-scroll",
          status: "running",
          stage: reportReads === 1 ? "ingest" : "analyze",
          progress: reportReads === 1 ? 0 : 1,
          result: {},
          errors: [],
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener(type: string, listener: () => void) {
        if (type === "stage_completed") stageCompleted = listener;
      }
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "/보고서작성" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByText("작성 중")).toBeInTheDocument();
    await waitFor(() => expect(reportReads).toBe(1));
    const callsAfterMessageAppend = scrollIntoView.mock.calls.length;

    act(() => stageCompleted?.());

    await waitFor(() => expect(reportReads).toBe(2));
    await waitFor(() => expect(document.querySelector(".stage-track .active small")).toHaveTextContent("분석"));
    expect(scrollIntoView).toHaveBeenCalledTimes(callsAfterMessageAppend);
  });

  it("polls the report status when the SSE connection fails", async () => {
    let reportReads = 0;
    let sseError: (() => void) | undefined;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        return response({ job_id: "job-sse", status: "queued" });
      }
      if (url === "/api/reports/job-sse") {
        reportReads += 1;
        return response({
          job_id: "job-sse",
          status: reportReads === 1 ? "running" : "completed",
          stage: reportReads === 1 ? "analyze" : "convert",
          progress: reportReads === 1 ? 2 : 7,
          result: reportReads === 1 ? {} : { report_md_path: "report.md" },
          errors: [],
        });
      }
      if (url === "/api/reports/job-sse/preview") return response({ markdown: "# 완료 보고서" });
      if (url === "/api/reports/job-sse/provenance") return response([]);
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener(type: string, listener: () => void) {
        if (type === "error") sseError = listener;
      }
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "/보고서작성" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByText("작성 중")).toBeInTheDocument();
    expect(reportReads).toBe(1);

    act(() => sseError?.());

    await waitFor(() => expect(reportReads).toBe(2));
    expect(await screen.findByText("완료")).toBeInTheDocument();
    expect(await screen.findByText("완료 보고서")).toBeInTheDocument();
  });

  it("announces a background report completion in the global toast", async () => {
    let completed: (() => void) | undefined;
    let reportReads = 0;
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        return response({ job_id: "job-toast", status: "queued" });
      }
      if (url === "/api/reports/job-toast") {
        reportReads += 1;
        return response({
          job_id: "job-toast",
          status: reportReads === 1 ? "running" : "completed",
          stage: reportReads === 1 ? "analyze" : "convert",
          progress: reportReads === 1 ? 2 : 7,
          result: {},
          errors: [],
        });
      }
      if (url === "/api/reports/job-toast/preview") return response({ markdown: "# 보고서" });
      if (url === "/api/reports/job-toast/provenance") return response([]);
      if (url.startsWith("/api/conversations/")) return response({});
      throw new Error(`unexpected request: ${url}`);
    }));
    vi.stubGlobal("EventSource", class {
      addEventListener(type: string, listener: () => void) {
        if (type === "job_completed") completed = listener;
      }
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "/보고서작성" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    await screen.findByText("작성 중");
    act(() => completed?.());

    expect(await screen.findByRole("status")).toHaveTextContent("보고서 작성이 완료되었습니다.");
  });

  it("uses an accessible, consistently aligned report stage list", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        return response({ job_id: "job-progress", status: "queued" });
      }
      if (url === "/api/reports/job-progress") return response({
        job_id: "job-progress",
        status: "running",
        stage: "analyze",
        progress: 1,
        result: {},
        errors: [],
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "/보고서작성" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    const stageList = await screen.findByRole("list", { name: "보고서 작업 단계" });
    const stages = within(stageList).getAllByRole("listitem");
    expect(stages).toHaveLength(7);
    expect(stages[1]).toHaveAttribute("aria-current", "step");
    expect(stages[1].querySelector(".stage-number")).toHaveTextContent("2");
    expect(stages[1].querySelector(".stage-label")).toHaveTextContent("분석");
  });

  it("opens a report chart in an image dialog and closes it with Escape", async () => {
    const completedJob = {
      job_id: "job-figures",
      status: "completed",
      stage: "convert",
      progress: 7,
      result: {
        report_md_path: "report.md",
        figures: {
          risk_map: "risk_map.png",
          factor_lift: "factor_lift.png",
        },
      },
      errors: [],
    };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        return response({ job_id: "job-figures", status: "queued" });
      }
      if (url === "/api/reports/job-figures") return response(completedJob);
      if (url === "/api/reports/job-figures/preview") return response({ markdown: "# 보고서" });
      if (url === "/api/reports/job-figures/provenance") return response([]);
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "/보고서작성" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    fireEvent.click(await screen.findByRole("button", { name: "요인별 고위험 격자 비교 크게 보기" }));

    const dialog = screen.getByRole("dialog", { name: "요인별 고위험 격자 비교" });
    expect(dialog.closest(".figure-lightbox")?.parentElement).toBe(document.body);
    expect(within(dialog).getByRole("img", { name: "요인별 고위험 격자 비교 확대 이미지" }))
      .toHaveAttribute("src", "/api/reports/job-figures/assets/factor_lift.png");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "요인별 고위험 격자 비교" })).not.toBeInTheDocument();
  });

  it("cancels a running queued report from the chat card", async () => {
    let reportStatus = "running";
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        return response({ job_id: "job-cancel", status: "queued" });
      }
      if (url === "/api/reports/job-cancel/cancel" && init?.method === "POST") {
        reportStatus = "cancelled";
        return response({ job_id: "job-cancel", status: "cancel_requested" });
      }
      if (url === "/api/reports/job-cancel") return response({
        job_id: "job-cancel",
        status: reportStatus,
        stage: "analyze",
        progress: 2,
        result: {},
        errors: [],
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "/보고서작성" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    fireEvent.click(await screen.findByRole("button", { name: "보고서 작업 취소" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/reports/job-cancel/cancel",
      expect.objectContaining({ method: "POST" }),
    ));
    expect(await screen.findByText("취소됨")).toBeInTheDocument();
  });

  it("retries a failed queued report from the same chat card", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        return response({ job_id: "job-failed", status: "queued" });
      }
      if (url === "/api/reports/job-failed") return response({
        job_id: "job-failed",
        status: "failed",
        stage: "narrate",
        progress: 4,
        result: {},
        errors: ["LLM timeout"],
      });
      if (url === "/api/reports/job-failed/retry" && init?.method === "POST") {
        return response({ job_id: "job-retry", status: "queued" });
      }
      if (url === "/api/reports/job-retry") return response({
        job_id: "job-retry",
        status: "queued",
        stage: null,
        progress: 0,
        result: {},
        errors: [],
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "/보고서작성" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    fireEvent.click(await screen.findByRole("button", { name: "보고서 작업 재시도" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/reports/job-failed/retry",
      expect.objectContaining({ method: "POST" }),
    ));
    expect(await screen.findByText("작성 중")).toBeInTheDocument();
  });

  it("automatically saves completed chat messages as one conversation", async () => {
    let savedUrl = "";
    let savedPayload: Record<string, unknown> | null = null;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "수영구 위험도를 알려줘",
        region: "부산광역시 수영구",
        answer: "수영구 위험도를 조회했습니다.",
        queries: ["SELECT avg(score) FROM grid"],
        results: [{ columns: ["score"], rows: [[52.1]] }],
        grounded: true,
      });
      if (url.startsWith("/api/conversations/") && init?.method === "PUT") {
        savedUrl = url;
        savedPayload = JSON.parse(String(init.body));
        return response({ id: url.split("/").at(-1) });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "수영구 위험도를 알려줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    await screen.findByText("수영구 위험도를 조회했습니다.");
    await waitFor(() => expect(savedPayload).not.toBeNull(), { timeout: 2000 });
    expect(savedUrl).toMatch(/^\/api\/conversations\/session-/);
    expect(savedPayload).toMatchObject({
      title: "수영구 위험도",
      region: "부산광역시 수영구",
    });
    expect((savedPayload as unknown as { messages: unknown[] }).messages).toHaveLength(2);
  });

  it("serializes overlapping conversation autosaves", async () => {
    let queryCount = 0;
    let saveCalls = 0;
    let activeSaves = 0;
    let maxActiveSaves = 0;
    let resolveFirstSave = () => {};
    let resolveSecondSave = () => {};
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") {
        queryCount += 1;
        return response({
          question: `질문 ${queryCount}`,
          region: "부산광역시 수영구",
          answer: `답변 ${queryCount}`,
          queries: ["SELECT 1"],
          results: [],
          grounded: true,
        });
      }
      if (url.startsWith("/api/conversations/") && init?.method === "PUT") {
        saveCalls += 1;
        activeSaves += 1;
        maxActiveSaves = Math.max(maxActiveSaves, activeSaves);
        return new Promise((resolve) => {
          const finish = () => {
            activeSaves -= 1;
            resolve({ ok: true, json: async () => ({ id: url.split("/").at(-1) }) });
          };
          if (saveCalls === 1) resolveFirstSave = finish;
          else resolveSecondSave = finish;
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    const composer = screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요");
    fireEvent.change(composer, { target: { value: "첫 번째 질문" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    await screen.findByText("답변 1");
    await waitFor(() => expect(saveCalls).toBe(1), { timeout: 2000 });

    fireEvent.change(composer, { target: { value: "두 번째 질문" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    await screen.findByText("답변 2");
    await new Promise((resolve) => window.setTimeout(resolve, 500));

    expect(saveCalls).toBe(1);
    expect(maxActiveSaves).toBe(1);
    resolveFirstSave();
    await waitFor(() => expect(saveCalls).toBe(2));
    expect(maxActiveSaves).toBe(1);
    resolveSecondSave();
  });

  it("selects a region mentioned in a natural report request", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        return response({ job_id: "job-2", status: "queued" });
      }
      if (url === "/api/reports/job-2") return response({
        job_id: "job-2",
        status: "queued",
        stage: null,
        progress: 0,
        result: {},
        errors: [],
      });
      if (url.startsWith("/api/conversations/") && init?.method === "PUT") {
        return response({ id: "session-2" });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "해운대구 보고서 작성해줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    fireEvent.click(await screen.findByRole("button", { name: "보고서 생성" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/reports",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          region: "부산광역시 해운대구",
          use_llm: true,
          use_judge: true,
          make_hwpx: true,
        }),
      }),
    ));
    expect(screen.getByRole("combobox", { name: "시·군·구" })).toHaveValue("해운대구");
    expect(screen.getByText("분석 지역을 부산광역시 해운대구로 변경했습니다.")).toBeInTheDocument();
  });

  it("changes the analysis region through chat without running a query", async () => {
    const fetchMock = vi.fn(() => response(regions));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "분석 지역을 해운대구로 변경해줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByText("분석 지역을 부산광역시 해운대구로 변경했습니다.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps structured analysis filters for a follow-up question", async () => {
    const queryPayloads: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") {
        queryPayloads.push(JSON.parse(String(init?.body)));
        return response({
          question: "질문",
          region: "부산광역시 해운대구",
          answer: "실제 데이터로 분석했습니다.",
          queries: ["SELECT 1"],
          results: [{ columns: ["값"], rows: [[1]] }],
          grounded: true,
        });
      }
      if (url.startsWith("/api/spatial/layer")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 10,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: { "5": 2 },
      });
      if (url.startsWith("/api/spatial/features")) return response({
        type: "FeatureCollection", features: [], metadata: { count: 0, truncated: false },
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    const composer = screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요");
    fireEvent.change(composer, { target: { value: "해운대구 침수 위험을 분석해줘" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    await waitFor(() => expect(queryPayloads).toHaveLength(1));

    fireEvent.change(composer, { target: { value: "그럼 5등급만 분석해줘" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    await waitFor(() => expect(queryPayloads).toHaveLength(2));

    expect(queryPayloads[1]).toEqual(expect.objectContaining({
      region: "부산광역시 해운대구",
      analysis_context: expect.objectContaining({
        region: "부산광역시 해운대구",
        grades: ["5"],
        comparison_regions: [],
      }),
    }));
  });

  it("limits long assistant answers before sending them as follow-up history", async () => {
    const queryPayloads: Array<Record<string, unknown>> = [];
    const longAnswer = "분석".repeat(1200);
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") {
        queryPayloads.push(JSON.parse(String(init?.body)));
        return response({
          question: queryPayloads.length === 1 ? "첫 질문" : "후속 질문",
          region: "부산광역시 수영구",
          answer: queryPayloads.length === 1 ? longAnswer : "후속 조회가 완료됐습니다.",
          queries: ["SELECT 1"],
          results: [{ columns: ["값"], rows: [[1]] }],
          grounded: true,
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    const composer = screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요");
    fireEvent.change(composer, { target: { value: "첫 질문" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    await screen.findByText(longAnswer);
    fireEvent.change(composer, { target: { value: "후속 질문" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    await screen.findByText("후속 조회가 완료됐습니다.");
    const history = queryPayloads[1].history as Array<{ role: string; content: string }>;
    expect(history.find((item) => item.role === "assistant")?.content).toHaveLength(2000);
  });

  it("renders structured API validation errors as readable text", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return errorResponse({
        detail: [{ msg: "대화 이력은 2,000자 이하여야 합니다." }],
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "위험지역을 다시 확인해줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByText("대화 이력은 2,000자 이하여야 합니다.")).toBeInTheDocument();
    expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();
  });

  it("uses the full chat row for query answers when avatars are hidden", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "고위험 지역을 알려줘",
        region: "부산광역시 수영구",
        answer: "실제 데이터에 따르면 남천2동의 고위험 비율이 가장 높습니다.",
        queries: ["SELECT 1"],
        results: [{ columns: ["지역"], rows: [["남천2동"]] }],
        grounded: true,
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "고위험 지역을 알려줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    const answer = await screen.findByText("실제 데이터에 따르면 남천2동의 고위험 비율이 가장 높습니다.");
    const turn = answer.closest(".chat-turn") as HTMLElement;
    expect(turn.querySelector(".avatar")).not.toBeInTheDocument();
  });

  it("does not open the map for a general regional risk question", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "고위험 지역과 등급을 알려줘",
        region: "부산광역시 수영구",
        answer: "남천2동은 5등급입니다.",
        queries: ["SELECT ADM_NM, grade FROM grid"],
        results: [{
          columns: ["ADM_NM", "위험성지수_등급"],
          rows: [["남천2동", 5]],
        }],
        grounded: true,
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "고위험 지역과 등급을 알려줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByText("남천2동은 5등급입니다.")).toBeInTheDocument();
    await act(async () => new Promise((resolve) => window.setTimeout(resolve, 100)));
    expect(document.querySelector(".spatial-studio")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith("/api/spatial/"))).toBe(false);
  });

  it("synchronizes query result places and grades to the live GPKG map", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "고위험 읍면동을 지도에 보여줘",
        region: "부산광역시 수영구",
        answer: "남천2동과 민락동이 고위험 지역입니다.",
        queries: ["SELECT ADM_NM, grade FROM grid"],
        results: [{
          columns: ["ADM_NM", "위험성지수_등급", "고위험비율"],
          rows: [["남천2동", 5, 21.4], ["민락동", 4, 16.3]],
        }],
        grounded: true,
      });
      if (url.startsWith("/api/spatial/layer")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 443,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: { "4": 43, "5": 13 },
      });
      if (url.startsWith("/api/spatial/features")) return response({
        type: "FeatureCollection", features: [], metadata: { count: 0, truncated: false },
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "고위험 읍면동을 지도에 보여줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByRole("heading", { name: "공간분석" })).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("focus=%EB%82%A8%EC%B2%9C2%EB%8F%99%2C%EB%AF%BC%EB%9D%BD%EB%8F%99"),
      expect.anything(),
    ));
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("grades=4%2C5"),
      expect.anything(),
    );
    expect(screen.getByText("남천2동 · 민락동")).toBeInTheDocument();
  });

  it("immediately applies comma-separated grade instructions to an open spatial workspace", async () => {
    const featureUrls: string[] = [];
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "4,5등급만 남겨줘",
        region: "부산광역시 수영구",
        answer: "4·5등급 격자만 조회했습니다.",
        queries: ["SELECT COUNT(*) AS cnt_all, COUNT(*) FILTER (...) AS cnt_45 FROM grid"],
        results: [{
          columns: ["cnt_all", "cnt_45", "pct_45"],
          rows: [[443, 56, 12.6]],
        }],
        grounded: true,
      });
      if (url.startsWith("/api/spatial/layer")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 443,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: { "4": 43, "5": 13 },
      });
      if (url.startsWith("/api/spatial/features")) {
        featureUrls.push(url);
        return response({
          type: "FeatureCollection", features: [], metadata: { count: 0, truncated: false },
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.click(screen.getByRole("button", { name: "공간분석 열기" }));
    await screen.findByRole("heading", { name: "공간분석" });

    const composer = screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요");
    fireEvent.change(composer, { target: { value: "4,5등급만 남겨줘" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    await waitFor(() => expect(featureUrls.some((url) => (
      url.includes("grades=4%2C5")
    ))).toBe(true));
  });

  it("renders grouped query results as an inline bar analysis", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "고위험 지역 순위를 보여줘",
        region: "부산광역시 수영구",
        answer: "남천2동의 고위험 비율이 가장 높습니다.",
        queries: ["SELECT ADM_NM, high_risk_pct FROM grid"],
        results: [{
          columns: ["ADM_NM", "high_risk_pct"],
          rows: [["남천2동", 21.4], ["민락동", 16.3], ["광안2동", 15.2]],
        }],
        grounded: true,
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "고위험 지역 순위를 보여줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    const chart = await screen.findByRole("img", { name: "high_risk_pct 인라인 막대 차트" });
    expect(within(chart).getByText("남천2동")).toBeInTheDocument();
    expect(within(chart).getByText("21.4")).toBeInTheDocument();
  });

  it("renders a single-row query result as inline key metrics", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "수영구 위험 현황을 요약해줘",
        region: "부산광역시 수영구",
        answer: "수영구에는 443개 격자가 있습니다.",
        queries: ["SELECT COUNT(*) AS grid_count, AVG(grade) AS avg_grade FROM grid"],
        results: [{ columns: ["grid_count", "avg_grade"], rows: [[443, 3.12]] }],
        grounded: true,
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "수영구 위험 현황을 요약해줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    const metrics = await screen.findByRole("group", { name: "인라인 핵심 지표" });
    expect(within(metrics).getByText("grid_count")).toBeInTheDocument();
    expect(within(metrics).getByText("443")).toBeInTheDocument();
    expect(within(metrics).getByText("avg_grade")).toBeInTheDocument();
    expect(within(metrics).getByText("3.12")).toBeInTheDocument();
  });

  it("runs MCP advanced analysis and renders its chart inline", async () => {
    const downloadClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    let mcpPayload: Record<string, unknown> | null = null;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "지역별 위험도를 비교해줘",
        region: "부산광역시 수영구",
        answer: "지역별 위험도를 조회했습니다.",
        queries: ["SELECT region, score FROM grid"],
        results: [{
          columns: ["지역", "위험도"],
          rows: [["수영구", 72.5], ["해운대구", 64.1]],
        }],
        grounded: true,
      });
      if (url === "/api/mcp/analyze") {
        mcpPayload = JSON.parse(String(init?.body));
        return response({
          analysis_id: "analysis-1",
          chart: "bar",
          columns: ["지역", "위험도"],
          reason: "지역별 값을 비교하기 적합한 막대 차트입니다.",
          chart_url: "/api/mcp/analyses/analysis-1/assets/chart.png",
          charts: [
            {
              chart: "bar",
              columns: ["지역", "위험도"],
              reason: "지역별 값을 비교하기 적합한 막대 차트입니다.",
              chart_url: "/api/mcp/analyses/analysis-1/assets/chart.png",
              asset_name: "chart.png",
              analysis: "실제 데이터 812행을 분석했다. 위험도 평균은 68.3이다.",
              grounded: true,
              evidence: {
                columns: ["근거 항목", "값"],
                rows: [["분석 행 수", 812], ["위험도 평균", 68.3]],
              },
            },
            {
              chart: "line",
              columns: ["지역", "위험도"],
              reason: "지역별 변화 흐름을 비교하는 선 차트입니다.",
              chart_url: "/api/mcp/analyses/analysis-1/assets/line.png",
              asset_name: "line.png",
              analysis: "실제 데이터 812행의 지역별 위험도 흐름을 분석했다.",
              grounded: true,
              evidence: {
                columns: ["근거 항목", "값"],
                rows: [["분석 행 수", 812]],
              },
            },
          ],
          tool_calls: ["recommend_visualizations", "plot_auto"],
          tools_available: 60,
          dataset: {
            source: "duckdb_grid_raw",
            row_count: 812,
            column_count: 31,
          },
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "지역별 위험도를 비교해줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    fireEvent.click(await screen.findByRole("button", { name: "MCP 고급 분석" }));

    const chart = await screen.findByRole("img", { name: "MCP 막대 차트" });
    expect(chart).toHaveAttribute(
      "src",
      "/api/mcp/analyses/analysis-1/assets/chart.png",
    );
    expect(screen.getByText("지역별 값을 비교하기 적합한 막대 차트입니다.")).toBeInTheDocument();
    expect(screen.getByText("실제 데이터 812행을 분석했다. 위험도 평균은 68.3이다.")).toBeInTheDocument();
    expect(screen.getByText("DuckDB 격자 원자료 812행 · 31열 확장 분석")).toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: "MCP 시각화 선택" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "선 차트" }));
    expect(screen.getByRole("img", { name: "MCP 선 차트" })).toHaveAttribute(
      "src",
      "/api/mcp/analyses/analysis-1/assets/line.png",
    );
    expect(screen.getByText("지역별 변화 흐름을 비교하는 선 차트입니다.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "현재 MCP 차트 다운로드" }));
    expect(downloadClick).toHaveBeenCalledOnce();
    const localDownload = downloadClick.mock.instances[0] as HTMLAnchorElement;
    expect(localDownload.getAttribute("href")).toBe("/api/mcp/analyses/analysis-1/assets/line.png");
    expect(localDownload.download).toBe("line.png");
    expect(mcpPayload).toEqual({
      question: "지역별 위험도를 비교해줘",
      region: "부산광역시 수영구",
      columns: ["지역", "위험도"],
      rows: [["수영구", 72.5], ["해운대구", 64.1]],
    });
    downloadClick.mockRestore();
  });

  it("adds the active grounded MCP chart and evidence to a report", async () => {
    const analysisId = "a".repeat(32);
    let reportPayload: Record<string, unknown> | null = null;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "고위험 지역의 원자료 관계를 분석해줘",
        region: "부산광역시 수영구",
        answer: "고위험 지역 원자료를 조회했습니다.",
        queries: ["SELECT raw factors FROM grid"],
        results: [{
          columns: ["지역", "강풍 (m/s)", "침수면적 (m²)"],
          rows: [["민락동", 20.5, 1200], ["광안동", 12.1, 950]],
        }],
        grounded: true,
      });
      if (url === "/api/mcp/analyze") return response({
        analysis_id: analysisId,
        chart: "correlation_heatmap",
        columns: ["강풍 (m/s)", "침수면적 (m²)"],
        reason: "원자료 사이의 관계를 비교합니다.",
        chart_url: `/api/mcp/analyses/${analysisId}/assets/correlation_heatmap.png`,
        asset_name: "correlation_heatmap.png",
        analysis: (
          "실제 데이터 213행을 분석했다. " +
          "강풍과 침수면적의 상관계수는 0.62로 양의 관계가 나타났다."
        ),
        grounded: true,
        evidence: {
          columns: ["근거 항목", "값"],
          rows: [["분석 행 수", 213], ["강풍–침수면적 상관계수", 0.62]],
        },
        tool_calls: ["plot_correlation_heatmap"],
        tools_available: 60,
        dataset: {
          source: "duckdb_grid_raw",
          row_count: 213,
          column_count: 31,
          query: "SELECT expanded raw factors FROM grid",
        },
      });
      if (url === "/api/reports" && init?.method === "POST") {
        reportPayload = JSON.parse(String(init.body));
        return response({ job_id: "job-mcp", status: "queued" });
      }
      if (url === "/api/reports/job-mcp") return response({
        job_id: "job-mcp",
        status: "queued",
        stage: null,
        progress: 0,
        result: {},
        errors: [],
      });
      if (url.startsWith("/api/conversations/") && init?.method === "PUT") {
        return response({ id: url.split("/").at(-1) });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    const composer = screen.getByPlaceholderText(
      "연안 데이터에 대해 질문하거나 명령어를 입력하세요",
    );
    fireEvent.change(composer, {
      target: { value: "고위험 지역의 원자료 관계를 분석해줘" },
    });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    fireEvent.click(await screen.findByRole("button", { name: "MCP 고급 분석" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "현재 MCP 차트를 보고서에 추가",
    }));

    expect(screen.getByRole("button", {
      name: "현재 MCP 차트를 보고서에서 제외",
    })).toBeInTheDocument();

    fireEvent.change(composer, { target: { value: "/보고서작성" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    await waitFor(() => expect(reportPayload).not.toBeNull());
    expect(reportPayload).toMatchObject({
      region: "부산광역시 수영구",
      materials: [{
        question: "고위험 지역의 원자료 관계를 분석해줘",
        answer: (
          "실제 데이터 213행을 분석했다. " +
          "강풍과 침수면적의 상관계수는 0.62로 양의 관계가 나타났다."
        ),
        region: "부산광역시 수영구",
        grounded: true,
        queries: ["SELECT expanded raw factors FROM grid"],
        results: [{
          columns: ["근거 항목", "값"],
          rows: [["분석 행 수", 213], ["강풍–침수면적 상관계수", 0.62]],
        }],
        mcp_chart: {
          analysis_id: analysisId,
          asset_name: "correlation_heatmap.png",
          caption: "부산광역시 수영구 상관관계 히트맵",
          chart: "correlation_heatmap",
        },
      }],
    });
  });

  it("keeps diverse chartable columns from a wide query result within the MCP limit", async () => {
    let mcpPayload: Record<string, unknown> | null = null;
    const fillerColumns = Array.from({ length: 51 }, (_, index) => `raw_${index}`);
    const columns = ["ADM_NM", ...fillerColumns, "위험성지수_등급"];
    const rows = [
      ["남천2동", ...fillerColumns.map((_, index) => index), 5],
      ["민락동", ...fillerColumns.map((_, index) => index + 1), 4],
    ];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "4,5등급만 남겨줘",
        region: "부산광역시 수영구",
        answer: "4·5등급 격자를 조회했습니다.",
        queries: ["SELECT * FROM grid WHERE grade IN (4, 5)"],
        results: [{ columns, rows }],
        grounded: true,
      });
      if (url === "/api/mcp/analyze") {
        mcpPayload = JSON.parse(String(init?.body));
        return response({
          analysis_id: "analysis-wide",
          chart: "bar",
          columns: ["ADM_NM", "위험성지수_등급"],
          reason: "지역별 위험등급을 비교합니다.",
          chart_url: "/api/mcp/analyses/analysis-wide/assets/chart.png",
          tool_calls: ["recommend_visualizations", "plot_bar"],
          tools_available: 60,
        });
      }
      if (url.startsWith("/api/spatial/layer")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 443,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: { "4": 43, "5": 13 },
      });
      if (url.startsWith("/api/spatial/features")) return response({
        type: "FeatureCollection", features: [], metadata: { count: 0, truncated: false },
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    const composer = screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요");
    fireEvent.change(composer, { target: { value: "4,5등급만 남겨줘" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    fireEvent.click(await screen.findByRole("button", { name: "MCP 고급 분석" }));

    const expectedColumns = [
      "ADM_NM",
      ...fillerColumns.slice(0, 48),
      "위험성지수_등급",
    ];
    await waitFor(() => expect(mcpPayload).toEqual({
      question: "4,5등급만 남겨줘",
      region: "부산광역시 수영구",
      columns: expectedColumns,
      rows: [
        ["남천2동", ...fillerColumns.slice(0, 48).map((_, index) => index), 5],
        ["민락동", ...fillerColumns.slice(0, 48).map((_, index) => index + 1), 4],
      ],
    }));
  });

  it("lets the user choose a chart and its axes for MCP analysis", async () => {
    let mcpPayload: Record<string, unknown> | null = null;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "강우와 위험도의 관계를 보여줘",
        region: "부산광역시 수영구",
        answer: "강우와 위험도 원자료를 조회했습니다.",
        queries: ["SELECT ADM_NM, rain, risk FROM grid"],
        results: [{
          columns: ["지역", "강우", "위험도"],
          rows: [["민락동", 20.5, 4.2], ["광안동", 12.1, 3.1]],
        }],
        grounded: true,
      });
      if (url === "/api/mcp/analyze") {
        mcpPayload = JSON.parse(String(init?.body));
        return response({
          analysis_id: "analysis-custom",
          chart: "scatter",
          columns: ["강우", "위험도", "지역"],
          reason: "사용자 지정 산점도입니다.",
          chart_url: "/api/mcp/analyses/analysis-custom/assets/scatter.png",
          charts: [{
            chart: "scatter",
            columns: ["강우", "위험도", "지역"],
            reason: "사용자 지정 산점도입니다.",
            chart_url: "/api/mcp/analyses/analysis-custom/assets/scatter.png",
          }],
          tool_calls: ["plot_scatter"],
          tools_available: 60,
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "강우와 위험도의 관계를 보여줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    fireEvent.click(await screen.findByRole("button", { name: "MCP 시각화 직접 설정" }));

    const settings = screen.getByRole("group", { name: "MCP 시각화 설정" });
    fireEvent.change(within(settings).getByLabelText("그래프 유형"), {
      target: { value: "scatter" },
    });
    fireEvent.change(within(settings).getByLabelText("Y축"), {
      target: { value: "위험도" },
    });
    fireEvent.change(within(settings).getByLabelText("그룹"), {
      target: { value: "지역" },
    });
    fireEvent.click(within(settings).getByRole("button", { name: "선택한 그래프 생성" }));

    await waitFor(() => expect(mcpPayload).toEqual({
      question: "강우와 위험도의 관계를 보여줘",
      region: "부산광역시 수영구",
      columns: ["강우", "위험도", "지역"],
      rows: [[20.5, 4.2, "민락동"], [12.1, 3.1, "광안동"]],
      chart_spec: {
        chart: "scatter",
        x_column: "강우",
        y_column: "위험도",
        group_column: "지역",
        aggregation: "mean",
        top_n: 20,
        bins: 10,
        normalize: false,
        x_label: "강우 (mm/h)",
        y_label: "위험도",
      },
    }));
    expect(await screen.findByRole("img", { name: "MCP 산점도" })).toBeInTheDocument();
  });

  it("adds a grounded query result to the next report", async () => {
    let reportPayload: Record<string, unknown> | null = null;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "5등급 격자는 몇 개인가?",
        region: "부산광역시 수영구",
        answer: "5등급 격자는 13개입니다.",
        queries: ["SELECT 13 AS count"],
        results: [{ columns: ["격자수"], rows: [[13]] }],
        grounded: true,
      });
      if (url === "/api/reports" && init?.method === "POST") {
        reportPayload = JSON.parse(String(init.body));
        return response({ job_id: "job-material", status: "queued" });
      }
      if (url === "/api/reports/job-material") return response({
        job_id: "job-material", status: "queued", stage: null, progress: 0,
        result: {}, errors: [],
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    const composer = screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요");
    fireEvent.change(composer, { target: { value: "5등급 격자는 몇 개인가?" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    fireEvent.click(await screen.findByRole("button", { name: "보고서에 추가" }));
    expect(screen.getByRole("button", { name: "보고서에서 제외" })).toBeInTheDocument();

    fireEvent.change(composer, { target: { value: "/보고서 작성" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    await waitFor(() => expect(reportPayload).not.toBeNull());

    expect(reportPayload).toEqual(expect.objectContaining({
      materials: [expect.objectContaining({
        question: "5등급 격자는 몇 개인가?",
        answer: "5등급 격자는 13개입니다.",
        queries: ["SELECT 13 AS count"],
      })],
    }));
  });

  it("revises a completed report section from a chat instruction", async () => {
    let revisionPayload: Record<string, unknown> | null = null;
    let previewCount = 0;
    const completedJob = {
      job_id: "job-complete", status: "completed", stage: "convert", progress: 7,
      result: { report_md_path: "report.md", revision_count: 0 }, errors: [],
    };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        return response({ job_id: "job-complete", status: "queued" });
      }
      if (url === "/api/reports/job-complete" && !init?.method) return response(completedJob);
      if (url === "/api/reports/job-complete/preview") {
        previewCount += 1;
        return response({ markdown: previewCount === 1
          ? "# 보고서\n\n### 6.2 정책 제언\n\n기존 정책 제언"
          : "# 보고서\n\n### 6.2 정책 제언\n\n수정된 정책 제언" });
      }
      if (url === "/api/reports/job-complete/revisions") {
        revisionPayload = JSON.parse(String(init?.body));
        return response({
          job_id: "job-complete",
          task_id: "job-complete-edit-1",
          status: "queued",
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    const composer = screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요");
    fireEvent.change(composer, { target: { value: "/보고서 작성" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    expect(await screen.findByText("완료")).toBeInTheDocument();

    fireEvent.change(composer, { target: { value: "정책 제언 부분을 더 짧게 수정해줘" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    await waitFor(() => expect(revisionPayload).toEqual({
      section: "6.2 정책 제언",
      instruction: "정책 제언 부분을 더 짧게 수정해줘",
    }));
    expect(await screen.findByText("보고서 수정 작업을 큐에 등록했습니다.")).toBeInTheDocument();
    expect(await screen.findByText("수정된 정책 제언")).toBeInTheDocument();
  });

  it("edits and saves a completed report directly in the web preview", async () => {
    let savedMarkdown = "";
    const completedJob = {
      job_id: "job-direct", status: "completed", stage: "convert", progress: 7,
      result: { report_md_path: "report.md", revision_count: 0 }, errors: [],
    };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        return response({ job_id: "job-direct", status: "queued" });
      }
      if (url === "/api/reports/job-direct" && !init?.method) return response(completedJob);
      if (url === "/api/reports/job-direct/preview") return response({
        markdown: savedMarkdown || "# 보고서\n\n기존 보고서 본문\n\n![](/api/reports/job-direct/assets/map.png)",
      });
      if (url === "/api/reports/job-direct/content" && !init?.method) return response({
        markdown: "# 보고서\n\n기존 보고서 본문\n\n![](../figures/map.png)",
      });
      if (url === "/api/reports/job-direct/provenance") return response([]);
      if (url === "/api/reports/job-direct/content" && init?.method === "PUT") {
        savedMarkdown = JSON.parse(String(init.body)).markdown;
        completedJob.result = {
          report_md_path: "report_v2.md",
          revision_count: 1,
        };
        return response({ revision: 1, mode: "direct_edit", section: "전체 보고서" });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "/보고서 작성" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    expect(await screen.findByText("기존 보고서 본문")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "보고서 직접 편집" }));
    const editor = await screen.findByRole("textbox", { name: "보고서 Markdown 편집" });
    expect(editor).toHaveValue("# 보고서\n\n기존 보고서 본문\n\n![](../figures/map.png)");
    fireEvent.change(editor, {
      target: { value: "# 보고서\n\n웹에서 직접 수정한 보고서 본문" },
    });
    fireEvent.click(screen.getByRole("button", { name: "편집 내용 저장" }));

    await waitFor(() => expect(savedMarkdown).toBe(
      "# 보고서\n\n웹에서 직접 수정한 보고서 본문",
    ));
    expect(await screen.findByText("웹에서 직접 수정한 보고서 본문")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
  });

  it("downloads every completed report file through the local browser", async () => {
    const downloadClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const completedJob = {
      job_id: "job-download", status: "completed", stage: "convert", progress: 7,
      result: { report_md_path: "report.md", report_hwpx_path: "report.hwpx" }, errors: [],
    };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        return response({ job_id: "job-download", status: "queued" });
      }
      if (url === "/api/reports/job-download") return response(completedJob);
      if (url === "/api/reports/job-download/preview") return response({ markdown: "# 다운로드 보고서" });
      if (url === "/api/reports/job-download/provenance") return response([]);
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "/보고서작성" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    await screen.findByText("다운로드 보고서");

    fireEvent.click(screen.getByRole("link", { name: "Markdown" }));
    fireEvent.click(screen.getByRole("link", { name: "HWPX" }));

    expect(downloadClick).toHaveBeenCalledTimes(2);
    expect((downloadClick.mock.instances[0] as HTMLAnchorElement).getAttribute("href"))
      .toBe("/api/reports/job-download/download/md");
    expect((downloadClick.mock.instances[1] as HTMLAnchorElement).getAttribute("href"))
      .toBe("/api/reports/job-download/download/hwpx");
    downloadClick.mockRestore();
  });

  it("cancels a direct report edit without saving", async () => {
    let saveCount = 0;
    const completedJob = {
      job_id: "job-cancel", status: "completed", stage: "convert", progress: 7,
      result: { report_md_path: "report.md", revision_count: 0 }, errors: [],
    };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        return response({ job_id: "job-cancel", status: "queued" });
      }
      if (url === "/api/reports/job-cancel") return response(completedJob);
      if (url === "/api/reports/job-cancel/preview") {
        return response({ markdown: "# 보고서\n\n원래 본문" });
      }
      if (url === "/api/reports/job-cancel/content" && !init?.method) {
        return response({ markdown: "# 보고서\n\n원래 본문" });
      }
      if (url === "/api/reports/job-cancel/provenance") return response([]);
      if (url === "/api/reports/job-cancel/content") {
        saveCount += 1;
        return response({});
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "/보고서 작성" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));
    await screen.findByText("원래 본문");
    fireEvent.click(screen.getByRole("button", { name: "보고서 직접 편집" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "보고서 Markdown 편집" }), {
      target: { value: "저장하지 않을 내용" },
    });
    fireEvent.click(screen.getByRole("button", { name: "직접 편집 취소" }));

    expect(screen.queryByRole("textbox", { name: "보고서 Markdown 편집" })).not.toBeInTheDocument();
    expect(screen.getByText("원래 본문")).toBeInTheDocument();
    expect(saveCount).toBe(0);
  });

  it("opens SQL and source rows when a grounded report sentence is clicked", async () => {
    const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView");
    const completedJob = {
      job_id: "job-evidence", status: "completed", stage: "convert", progress: 7,
      result: { report_md_path: "report.md" }, errors: [],
    };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/reports" && init?.method === "POST") {
        return response({ job_id: "job-evidence", status: "queued" });
      }
      if (url === "/api/reports/job-evidence") return response(completedJob);
      if (url === "/api/reports/job-evidence/preview") return response({
        markdown: "# 보고서\n\n**1) 남천2동** — 격자 56개, 평균 등급 3.25, 고위험 비율 21.4%",
      });
      if (url === "/api/reports/job-evidence/provenance") return response([{
        id: "s1",
        sentence: "남천2동 — 격자 56개, 평균 등급 3.25, 고위험 비율 21.4%",
        grounded: true,
        stats: [{ path: "데이터개요.총 격자 수", value: 443 }],
        gpkg_fields: ["FTR_IDN", "SD_NM"],
        map_context: {
          region: "부산광역시 수영구",
          adm_names: ["남천2동"],
          grades: ["5"],
          metric_id: "exposure",
        },
        queries: [{ sql: "SELECT COUNT(*) AS total_count FROM grid", row_count: 1 }],
      }, {
        id: "s2",
        sentence: "기후변화 대응이 필요하다.",
        grounded: false,
        stats: [],
        gpkg_fields: [],
        queries: [],
      }]);
      if (url === "/api/reports/job-evidence/provenance/s1") return response({
        id: "s1",
        sentence: "남천2동 — 격자 56개, 평균 등급 3.25, 고위험 비율 21.4%",
        grounded: true,
        stats: [{ path: "데이터개요.총 격자 수", value: 443 }],
        gpkg_fields: ["FTR_IDN", "SD_NM"],
        map_context: {
          region: "부산광역시 수영구",
          adm_names: ["남천2동"],
          grades: ["5"],
          metric_id: "exposure",
        },
        queries: [{
          sql: "SELECT COUNT(*) AS total_count FROM grid",
          columns: ["total_count"],
          rows: [[443]],
          row_count: 1,
        }],
      });
      if (url.startsWith("/api/spatial/layer")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 56,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: { "5": 13 },
      });
      if (url.startsWith("/api/spatial/features")) return response({
        type: "FeatureCollection", features: [], metadata: { count: 0, truncated: false },
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "/보고서 작성" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    const sentence = await screen.findByRole("button", {
      name: "근거 보기: 1) 남천2동 — 격자 56개, 평균 등급 3.25, 고위험 비율 21.4%",
    });
    fireEvent.click(sentence);

    expect(await screen.findByRole("heading", { name: "문장 근거" })).toBeInTheDocument();
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({
      block: "center",
      inline: "nearest",
    }));
    expect(screen.getByText("데이터개요.총 격자 수")).toBeInTheDocument();
    expect(screen.getByText("SELECT COUNT(*) AS total_count FROM grid")).toBeInTheDocument();
    expect(screen.getByText("FTR_IDN")).toBeInTheDocument();
    const evidenceLayout = document.querySelector(".evidence-layout") as HTMLElement;
    const evidenceResizer = screen.getByRole("separator", { name: "문장 근거 높이 조절" });
    expect(evidenceResizer).toHaveAttribute("aria-valuenow", "560");

    fireEvent.mouseDown(evidenceResizer, { clientY: 500 });
    fireEvent.mouseMove(window, { clientY: 700 });
    fireEvent.mouseUp(window);

    expect(evidenceLayout.style.getPropertyValue("--evidence-height")).toBe("760px");
    expect(evidenceResizer).toHaveAttribute("aria-valuenow", "760");
    fireEvent.click(screen.getByRole("button", { name: "지도에서 보기" }));
    expect(await screen.findByRole("heading", { name: "공간분석" })).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("focus=%EB%82%A8%EC%B2%9C2%EB%8F%99"),
      expect.anything(),
    ));
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("grades=5"),
      expect.anything(),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("metric=exposure"),
      expect.anything(),
    );
    expect(await screen.findByRole("button", { name: "사용자 영역 그리기" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "저장 시나리오 보기" })).toBeInTheDocument();
  });

  it("runs a deterministic regional comparison from the conversation", async () => {
    let comparisonPayload: Record<string, unknown> | null = null;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/comparisons") {
        comparisonPayload = JSON.parse(String(init?.body));
        return response({
          regions: ["부산광역시 수영구", "부산광역시 해운대구"],
          summary: [
            { region: "부산광역시 수영구", grid_count: 443, avg_grade: 3.12, high_risk_count: 56, high_risk_pct: 12.6 },
            { region: "부산광역시 해운대구", grid_count: 610, avg_grade: 3.03, high_risk_count: 61, high_risk_pct: 10.0 },
          ],
          distribution: {
            "부산광역시 수영구": [{ grade: "4", count: 43, pct: 9.7 }, { grade: "5", count: 13, pct: 2.9 }],
            "부산광역시 해운대구": [{ grade: "4", count: 50, pct: 8.2 }, { grade: "5", count: 11, pct: 1.8 }],
          },
          queries: ["SELECT region comparison", "SELECT grade distribution"],
          results: [{
            columns: ["region", "grid_count", "avg_grade", "high_risk_count", "high_risk_pct"],
            rows: [["부산광역시 수영구", 443, 3.12, 56, 12.6], ["부산광역시 해운대구", 610, 3.03, 61, 10.0]],
          }],
          answer: "부산광역시 수영구의 4·5등급 비율이 12.6%로 가장 높습니다.",
          grounded: true,
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "수영구와 해운대구를 비교해줘" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByRole("heading", { name: "지역 비교 분석" })).toBeInTheDocument();
    expect(comparisonPayload).toEqual({
      regions: ["부산광역시 수영구", "부산광역시 해운대구"],
    });
    expect(screen.getByText("12.6%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "지도에서 보기: 부산광역시 수영구" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "보고서에 추가" }));
    expect(screen.getByRole("button", { name: "보고서에서 제외" })).toBeInTheDocument();
  });

  it("compares a province-wide baseline with a district named in the same province", async () => {
    let comparisonPayload: Record<string, unknown> | null = null;
    const gangwonRegions = [
      { name: "강원특별자치도", districts: ["고성군(강원)"] },
      { name: "경상남도", districts: ["고성군(경남)"] },
    ];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(gangwonRegions);
      if (url === "/api/comparisons") {
        comparisonPayload = JSON.parse(String(init?.body));
        return response({
          regions: ["강원특별자치도", "강원특별자치도 고성군(강원)"],
          summary: [
            { region: "강원특별자치도", grid_count: 30000, avg_grade: 2.8, high_risk_count: 4200, high_risk_pct: 14.0 },
            { region: "강원특별자치도 고성군(강원)", grid_count: 4108, avg_grade: 3.1, high_risk_count: 1135, high_risk_pct: 27.6 },
          ],
          distribution: {
            "강원특별자치도": [{ grade: "5", count: 1200, pct: 4.0 }],
            "강원특별자치도 고성군(강원)": [{ grade: "5", count: 300, pct: 7.3 }],
          },
          queries: ["SELECT province comparison", "SELECT grade distribution"],
          results: [],
          answer: "강원특별자치도 고성군(강원)의 4·5등급 비율이 27.6%입니다.",
          grounded: true,
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await waitFor(() => expect(screen.getByRole("combobox", { name: "시·도" })).toHaveValue("강원특별자치도"));
    fireEvent.change(
      screen.getByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요"),
      { target: { value: "강원도 전체 대비 / 강원도 고성군은 어느 수준이야" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByRole("heading", { name: "지역 비교 분석" })).toBeInTheDocument();
    expect(comparisonPayload).toEqual({
      regions: ["강원특별자치도", "강원특별자치도 고성군(강원)"],
    });
    expect(screen.getAllByText("강원특별자치도 고성군").length).toBeGreaterThan(0);
    expect(screen.queryByText("강원특별자치도 고성군(강원)")).not.toBeInTheDocument();
    expect(screen.queryByText("경상남도 고성군(경남)")).not.toBeInTheDocument();
  });

  it("opens a spatial workspace backed by the selected GPKG region", async () => {
    vi.stubGlobal("innerWidth", 1920);
    vi.stubGlobal("innerHeight", 1080);
    localStorage.setItem("coastal:spatial-width", "1200");
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url.startsWith("/api/spatial/layer")) return response({
        id: "risk_grid",
        name: "연안재해 위험 격자",
        feature_count: 443,
        geometry_type: "Polygon",
        source_crs: "EPSG:5179",
        grade_counts: { "4": 43, "5": 13 },
      });
      if (url.startsWith("/api/spatial/features")) return response({
        type: "FeatureCollection",
        features: [],
        metadata: { count: 0, truncated: false },
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.click(screen.getByRole("button", { name: "공간분석 열기" }));

    expect(await screen.findByRole("heading", { name: "공간분석" })).toBeInTheDocument();
    expect(screen.queryByText("GPKG LIVE WORKSPACE")).not.toBeInTheDocument();
    expect(document.querySelector(".spatial-header svg")).not.toBeInTheDocument();
    expect(await screen.findByText("연안재해 위험 격자")).toBeInTheDocument();
    expect(screen.getByText("속성 테이블")).toBeInTheDocument();
    const workspace = document.querySelector(".chat-app") as HTMLElement;
    const separator = screen.getByRole("separator", { name: "공간분석 너비 조절" });
    expect(workspace.style.getPropertyValue("--spatial-width")).toBe("1200px");
    expect(separator).toHaveAttribute("aria-valuemax", "1640");

    fireEvent.mouseDown(separator, { clientX: 1200 });
    fireEvent.mouseMove(window, { clientX: 1000 });
    fireEvent.mouseUp(window);

    expect(workspace.style.getPropertyValue("--spatial-width")).toBe("1400px");
    expect(separator).toHaveAttribute("aria-valuenow", "1400");

    const tableSeparator = screen.getByRole("separator", { name: "지도와 속성 테이블 높이 조절" });
    const attributeDock = document.querySelector(".attribute-dock") as HTMLElement;
    expect(attributeDock.style.getPropertyValue("--attribute-table-height")).toBe("155px");
    expect(tableSeparator).toHaveAttribute("aria-valuemax", "640");

    fireEvent.mouseDown(tableSeparator, { clientY: 600 });
    fireEvent.mouseMove(window, { clientY: 400 });
    fireEvent.mouseUp(window);

    expect(attributeDock.style.getPropertyValue("--attribute-table-height")).toBe("355px");
    expect(tableSeparator).toHaveAttribute("aria-valuenow", "355");
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining(
      "region=%EB%B6%80%EC%82%B0%EA%B4%91%EC%97%AD%EC%8B%9C+%EC%88%98%EC%98%81%EA%B5%AC",
    ), expect.anything());
  });

  it("updates an open spatial workspace when the header region changes", async () => {
    const requestedRegions: string[] = [];
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url.startsWith("/api/spatial/layer")) {
        requestedRegions.push(new URL(url, "http://test").searchParams.get("region") || "");
        return response({
          id: "risk_grid", name: "연안재해 위험 격자", feature_count: 443,
          geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: {},
          metrics: [],
        });
      }
      if (url.startsWith("/api/spatial/features")) return response({
        type: "FeatureCollection", features: [], metadata: { count: 0, truncated: false },
      });
      if (url === "/api/spatial/scenarios") return response([]);
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.click(screen.getByRole("button", { name: "공간분석 열기" }));
    await waitFor(() => expect(requestedRegions).toContain("부산광역시 수영구"));

    fireEvent.change(screen.getByRole("combobox", { name: "시·군·구" }), {
      target: { value: "해운대구" },
    });

    await waitFor(() => expect(requestedRegions).toContain("부산광역시 해운대구"));
  });

  it("folds and resizes the layer pane", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url.startsWith("/api/spatial/layer")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 443,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: { "4": 43, "5": 13 },
      });
      if (url.startsWith("/api/spatial/features")) return response({
        type: "FeatureCollection", features: [], metadata: { count: 0, truncated: false },
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.click(screen.getByRole("button", { name: "공간분석 열기" }));
    await screen.findByRole("heading", { name: "공간분석" });
    expect(screen.getByRole("button", { name: "마지막 꼭짓점 되돌리기" })).toBeDisabled();

    const body = document.querySelector(".spatial-body") as HTMLElement;
    const separator = screen.getByRole("separator", { name: "레이어 창 너비 조절" });
    expect(body.style.getPropertyValue("--layer-width")).toBe("260px");
    fireEvent.keyDown(separator, { key: "ArrowRight" });
    expect(body.style.getPropertyValue("--layer-width")).toBe("276px");

    fireEvent.click(screen.getByRole("button", { name: "레이어 창 접기" }));
    expect(screen.queryByRole("region", { name: "레이어 창" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "레이어 창 펼치기" }));
    expect(screen.getByRole("region", { name: "레이어 창" })).toBeInTheDocument();
  });

  it("renders and filters grid grades by the selected evaluation factor", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url.startsWith("/api/spatial/layer")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 2,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: { "2": 1, "5": 1 },
        metrics: [
          { id: "overall", label: "종합 위험", group: "종합", grade_column: "위험성지수_등급", grade_counts: { "2": 1, "5": 1 } },
          { id: "강풍", label: "강풍", group: "위해성", grade_column: "강풍_등급", grade_counts: { "4": 1, "5": 1 } },
        ],
      });
      if (url.startsWith("/api/spatial/features")) return response({
        type: "FeatureCollection",
        features: [{
          type: "Feature",
          geometry: { type: "Polygon", coordinates: [[[129, 35], [129.01, 35], [129.01, 35.01], [129, 35]]] },
          properties: { FTR_IDN: "G2", ADM_NM: "남천동", "강풍_등급": 4, "위험성지수_등급": 2 },
        }],
        metadata: { count: 1, truncated: false, metric: { id: "강풍", label: "강풍", group: "위해성", grade_column: "강풍_등급" } },
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.click(screen.getByRole("button", { name: "공간분석 열기" }));
    const selector = await screen.findByRole("combobox", { name: "지도 평가항목" });
    fireEvent.change(selector, { target: { value: "강풍" } });
    fireEvent.click(screen.getByRole("button", { name: /4등급/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("metric=%EA%B0%95%ED%92%8D"),
      expect.anything(),
    ));
    expect(document.querySelector(".map-legend strong")).toHaveTextContent("강풍 등급");
    expect(screen.getByRole("columnheader", { name: "강풍 등급" })).toBeInTheDocument();
  });

  it("switches the spatial basemap to satellite imagery", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url.startsWith("/api/spatial/layer")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 0,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: {}, metrics: [],
      });
      if (url.startsWith("/api/spatial/features")) return response({
        type: "FeatureCollection", features: [], metadata: { count: 0, truncated: false },
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.click(screen.getByRole("button", { name: "공간분석 열기" }));
    const satellite = await screen.findByRole("button", { name: "위성영상 배경지도" });
    fireEvent.click(satellite);

    expect(satellite).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(
      document.querySelector<HTMLImageElement>('.leaflet-tile[src*="World_Imagery"]'),
    ).toBeInTheDocument());
  });

  it("uploads a shapefile annotation layer and labels it by an attribute", async () => {
    let annotationRequest: RequestInit | undefined;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url.startsWith("/api/spatial/layer")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 0,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: {}, metrics: [],
      });
      if (url.startsWith("/api/spatial/features")) return response({
        type: "FeatureCollection", features: [], metadata: { count: 0, truncated: false },
      });
      if (url === "/api/spatial/annotations" && init?.method === "POST") {
        annotationRequest = init;
        return response({
          id: "layer-1", name: "district", feature_count: 1,
          geometry_type: "Polygon", source_crs: "EPSG:5179", display_crs: "EPSG:4326",
          columns: ["지역명", "지역코드"], suggested_label_field: "지역명",
          geojson: {
            type: "FeatureCollection",
            features: [{
              type: "Feature",
              properties: { 지역명: "광안동", 지역코드: "261401" },
              geometry: { type: "Polygon", coordinates: [[[129.1, 35.1], [129.11, 35.1], [129.11, 35.11], [129.1, 35.1]]] },
            }],
          },
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.click(screen.getByRole("button", { name: "공간분석 열기" }));
    const input = await screen.findByLabelText("지역 annotation 파일 업로드");
    const files = [
      new File(["shp"], "district.shp"),
      new File(["dbf"], "district.dbf"),
      new File(["prj"], "district.prj"),
    ];
    fireEvent.change(input, { target: { files } });

    expect(await screen.findByText("district")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "annotation 표시 필드" })).toHaveValue("지역명");
    await waitFor(() => expect(document.querySelector(".annotation-label")).toHaveTextContent("광안동"));
    expect(annotationRequest?.body).toBeInstanceOf(FormData);
    expect(annotationRequest?.headers).toBeUndefined();
  });

  it("exports the current spatial map and adds it to report materials", async () => {
    const exportBodies: Array<Record<string, unknown>> = [];
    const downloadClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/regions") return response(regions);
      if (url.startsWith("/api/spatial/layer")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 32,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: { "4": 32 },
        metrics: [
          { id: "overall", label: "종합 위험", group: "종합", grade_column: "위험성지수_등급", grade_counts: { "4": 32 } },
          { id: "파랑", label: "파랑", group: "위해성", grade_column: "파랑_등급", grade_counts: { "4": 32 } },
        ],
      });
      if (url.startsWith("/api/spatial/features")) return response({
        type: "FeatureCollection", features: [], metadata: { count: 32, truncated: false },
      });
      if (url === "/api/spatial/exports" && init?.method === "POST") {
        exportBodies.push(JSON.parse(String(init.body)));
        return response({
          image_id: "map-1",
          filename: "부산광역시_수영구_파랑_4등급.png",
          caption: "부산광역시 수영구 파랑 4등급 공간분석",
          region: "부산광역시 수영구",
          metric: "파랑",
          grades: ["4"],
          feature_count: 32,
          image_url: "/api/spatial/exports/map-1",
          download_url: "/api/spatial/exports/map-1/download",
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.click(screen.getByRole("button", { name: "공간분석 열기" }));
    const selector = await screen.findByRole("combobox", { name: "지도 평가항목" });
    fireEvent.change(selector, { target: { value: "파랑" } });
    fireEvent.click(screen.getByRole("button", { name: /4등급/ }));
    fireEvent.click(screen.getByRole("button", { name: "현재 지도를 보고서에 추가" }));

    expect(await screen.findByRole("button", { name: "현재 지도를 보고서에서 제외" })).toBeInTheDocument();
    expect(screen.getByText("보고서 자료 1")).toBeInTheDocument();
    expect(exportBodies[0]).toEqual({
      region: "부산광역시 수영구",
      metric: "파랑",
      grades: ["4"],
      focus_names: [],
      background: "composite",
      extent: "region",
    });

    fireEvent.click(screen.getByRole("button", { name: "현재 지도 이미지 저장" }));
    expect(screen.getByRole("dialog", { name: "지도 이미지 저장 옵션" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "위성영상" }));
    fireEvent.click(screen.getByRole("radio", { name: "현재 화면" }));
    fireEvent.click(screen.getByRole("button", { name: "옵션대로 이미지 생성" }));
    expect(await screen.findByRole("link", { name: "PNG 다운로드" })).toHaveAttribute(
      "href",
      "/api/spatial/exports/map-1/download",
    );
    expect(exportBodies[1]).toMatchObject({
      background: "satellite",
      extent: "viewport",
      geometry: { type: "Polygon" },
    });
    expect(downloadClick).toHaveBeenCalledOnce();
    const localDownload = downloadClick.mock.instances[0] as HTMLAnchorElement;
    expect(localDownload.getAttribute("href")).toBe("/api/spatial/exports/map-1/download");
    expect(localDownload.download).toBe("부산광역시_수영구_파랑_4등급.png");
    downloadClick.mockRestore();
  });

  it("does not show static grounded or select-only claims", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "수영구 위험도를 알려줘",
        region: "부산광역시 수영구",
        answer: "실제 조회 결과입니다.",
        queries: ["SELECT 1"],
        results: [{ columns: ["값"], rows: [[1]] }],
        grounded: true,
      });
      if (url.startsWith("/api/conversations/") && url !== "/api/conversations/") return response({
        id: "session-1", title: "수영구 위험도", region: "부산광역시 수영구",
        messages: [], analysis_context: { region: "부산광역시 수영구", grades: [], comparison_regions: [] },
        materials: [], created_at: "2026-07-15", updated_at: "2026-07-15",
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    const input = await screen.findByPlaceholderText("연안 데이터에 대해 질문하거나 명령어를 입력하세요");
    fireEvent.change(input, { target: { value: "수영구 위험도를 알려줘" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByText("실제 조회 결과입니다.")).toBeInTheDocument();
    expect(screen.queryByText("DATA GROUNDED")).not.toBeInTheDocument();
    expect(screen.queryByText("SELECT ONLY")).not.toBeInTheDocument();
  });

  it("does not allow an ungrounded query to be added to report materials", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url === "/api/queries") return response({
        question: "선택 영역과 전체를 비교해줘",
        region: "부산광역시 수영구",
        answer: "선택 범위를 검증하지 못했습니다.",
        queries: ["SELECT COUNT(*) FROM selected_grid"],
        results: [{ columns: ["count"], rows: [[0]] }],
        grounded: false,
        scope_valid: false,
      });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    const input = await screen.findByPlaceholderText(
      "연안 데이터에 대해 질문하거나 명령어를 입력하세요",
    );
    fireEvent.change(input, { target: { value: "선택 영역과 전체를 비교해줘" } });
    fireEvent.click(screen.getByRole("button", { name: "메시지 보내기" }));

    expect(await screen.findByText("수치 확인이 필요한 답변")).toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "검증 실패 답변은 보고서에 추가할 수 없습니다",
    })).toBeDisabled();
  });

  it("keeps the newest grade result when older requests finish later", async () => {
    type FetchResult = { ok: boolean; json: () => Promise<unknown> };
    const pending: Array<{ url: string; resolve: (value: FetchResult) => void }> = [];
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url.startsWith("/api/spatial/layer")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 443,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: { "4": 43, "5": 13 },
      });
      if (url.startsWith("/api/spatial/features")) {
        return new Promise<FetchResult>((resolve) => pending.push({ url, resolve }));
      }
      throw new Error(`unexpected request: ${url}`);
    });
    const collection = (name: string, id: string) => ({
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        geometry: { type: "Polygon", coordinates: [[[129, 35], [129.01, 35], [129.01, 35.01], [129, 35]]] },
        properties: { FTR_IDN: id, ADM_NM: name, "위험성지수_등급": 5 },
      }],
      metadata: { count: 1, truncated: false },
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.click(screen.getByRole("button", { name: "공간분석 열기" }));
    await screen.findByRole("heading", { name: "공간분석" });
    await waitFor(() => expect(pending).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: /5등급/ }));
    await waitFor(() => expect(pending).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: /4등급/ }));
    await waitFor(() => expect(pending).toHaveLength(3));

    await act(async () => pending[2].resolve(await response(collection("최신결과", "latest"))));
    expect(await screen.findByText("최신결과")).toBeInTheDocument();
    await act(async () => pending[1].resolve(await response(collection("이전결과", "stale"))));
    await act(async () => pending[0].resolve(await response(collection("초기결과", "initial"))));

    await waitFor(() => expect(screen.getByText("최신결과")).toBeInTheDocument());
    expect(screen.queryByText("이전결과")).not.toBeInTheDocument();
    expect(screen.queryByText("초기결과")).not.toBeInTheDocument();
  });

  it("clears the previous map result as soon as the grade filter changes", async () => {
    type FetchResult = { ok: boolean; json: () => Promise<unknown> };
    const pending: Array<{ url: string; resolve: (value: FetchResult) => void }> = [];
    const collection = (name: string, id: string) => ({
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        geometry: { type: "Polygon", coordinates: [[[129, 35], [129.01, 35], [129.01, 35.01], [129, 35]]] },
        properties: { FTR_IDN: id, ADM_NM: name, "위험성지수_등급": 5 },
      }],
      metadata: { count: 1, truncated: false },
    });
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/regions") return response(regions);
      if (url.startsWith("/api/spatial/layer")) return response({
        id: "risk_grid", name: "연안재해 위험 격자", feature_count: 443,
        geometry_type: "Polygon", source_crs: "EPSG:5179", grade_counts: { "5": 13 },
      });
      if (url.startsWith("/api/spatial/features")) {
        return new Promise<FetchResult>((resolve) => pending.push({ url, resolve }));
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await screen.findAllByText("부산광역시 수영구");
    fireEvent.click(screen.getByRole("button", { name: "공간분석 열기" }));
    await waitFor(() => expect(pending).toHaveLength(1));
    await act(async () => pending[0].resolve(await response(collection("이전 지도 결과", "old"))));
    expect(await screen.findByText("이전 지도 결과")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /5등급/ }));
    await waitFor(() => expect(pending).toHaveLength(2));

    expect(screen.queryByText("이전 지도 결과")).not.toBeInTheDocument();
    expect(screen.getByText("GPKG 공간 레이어를 조회하고 있습니다.")).toBeInTheDocument();
  });
});
