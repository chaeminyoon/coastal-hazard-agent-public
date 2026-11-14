import json
import re
from pathlib import Path

from playwright.sync_api import ConsoleMessage, Route, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HOME_SCREENSHOT = ROOT / "outputs" / "e2e-chat-home.png"
REPORT_SCREENSHOT = ROOT / "outputs" / "e2e-chat-report.png"
SPATIAL_SCREENSHOT = ROOT / "outputs" / "e2e-spatial-studio.png"
REVISION_SCREENSHOT = ROOT / "outputs" / "e2e-report-revision.png"
EVIDENCE_SCREENSHOT = ROOT / "outputs" / "e2e-report-evidence.png"
COMPARISON_SCREENSHOT = ROOT / "outputs" / "e2e-region-comparison.png"
LINKED_MAP_SCREENSHOT = ROOT / "outputs" / "e2e-sentence-map-link.png"
INLINE_ANALYSIS_SCREENSHOT = ROOT / "outputs" / "e2e-inline-analysis.png"
MCP_ANALYSIS_SCREENSHOT = ROOT / "outputs" / "e2e-mcp-analysis.png"
DIRECT_EDIT_SCREENSHOT = ROOT / "outputs" / "e2e-report-direct-edit.png"
LIVE_MAP_SCREENSHOT = ROOT / "outputs" / "e2e-live-query-map.png"
HISTORY_SCREENSHOT = ROOT / "outputs" / "e2e-analysis-history.png"
HOME_SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)


def capture_console_error(message: ConsoleMessage) -> None:
    if message.type == "error":
        console_errors.append(message.text)


def use_fast_report_options(route: Route) -> None:
    payload = json.loads(route.request.post_data or "{}")
    payload.update({"use_llm": False, "use_judge": False, "make_hwpx": False})
    route.continue_(post_data=json.dumps(payload))


def answer_query(route: Route) -> None:
    payload = json.loads(route.request.post_data or "{}")
    query_payloads.append(payload)
    grades = (payload.get("analysis_context") or {}).get("grades") or []
    result = {
        "columns": ["위험성지수_등급", "격자수"],
        "rows": [[5, 13]],
    } if grades else {
        "columns": ["읍면동", "고위험 비율"],
        "rows": [["송정동", 21.4], ["우동", 16.3], ["중동", 15.2]],
    }
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({
            "question": payload["question"],
            "region": payload["region"],
            "answer": "해운대구의 원자료를 기준으로 분석했습니다.",
            "queries": ["SELECT COUNT(*) FROM grid WHERE SGG_NM = '해운대구'"],
            "results": [result],
            "grounded": True,
        }, ensure_ascii=False),
    )


def answer_revision(route: Route) -> None:
    revision_payloads.append(json.loads(route.request.post_data or "{}"))
    revision_state["applied"] = True
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"revision": 1, "section": "6.2 정책 제언"}, ensure_ascii=False),
    )


def preview_revision(route: Route) -> None:
    if not revision_state["applied"]:
        route.continue_()
        return
    response = route.fetch()
    payload = response.json()
    payload["markdown"] = re.sub(
        r"(### 6\.2 정책 제언\s+).*?(?=\n###|\n##)",
        r"\1브라우저 검증용 수정된 정책 제언.\n",
        payload["markdown"],
        flags=re.DOTALL,
    )
    route.fulfill(
        status=response.status,
        headers=response.headers,
        body=json.dumps(payload, ensure_ascii=False),
    )


def composer_value(page) -> str:
    placeholder = "연안 데이터에 대해 질문하거나 명령어를 입력하세요"
    return page.get_by_placeholder(placeholder).input_value()


console_errors: list[str] = []
query_payloads: list[dict] = []
revision_payloads: list[dict] = []
revision_state = {"applied": False}
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        headless=True,
    )
    page = browser.new_page(viewport={"width": 1440, "height": 980})
    page.on("console", capture_console_error)
    page.route("**/api/reports", use_fast_report_options)
    page.route("**/api/queries", answer_query)
    page.route("**/api/reports/*/revisions", answer_revision)
    page.route("**/api/reports/*/preview", preview_revision)
    page.goto("http://127.0.0.1:8000")
    page.wait_for_load_state("networkidle")

    assert page.get_by_role("heading", name="연안 데이터 어시스턴트").is_visible()
    assert page.get_by_role("heading", name="질문에서 근거 있는 보고서까지.").is_visible()
    page.locator("select").first.wait_for()
    assert page.locator("select").first.locator("option").count() > 0
    page.screenshot(path=str(HOME_SCREENSHOT), full_page=True)

    composer = page.get_by_placeholder("연안 데이터에 대해 질문하거나 명령어를 입력하세요")
    composer.fill("해운대구 침수 위험을 분석해줘")
    page.get_by_role("button", name="메시지 보내기").click()
    page.get_by_text("해운대구의 원자료를 기준으로 분석했습니다.").wait_for()
    inline_analysis = page.get_by_role("img", name="고위험 비율 인라인 막대 차트")
    inline_analysis.wait_for()
    inline_analysis.screenshot(path=str(INLINE_ANALYSIS_SCREENSHOT))
    page.get_by_role("heading", name="공간 작업실").wait_for(timeout=30_000)
    page.locator(".map-focus-context").get_by_text(
        "송정동 · 우동 · 중동 집중", exact=True,
    ).wait_for(timeout=30_000)
    page.locator(".map-loading").wait_for(state="hidden", timeout=30_000)
    page.locator(".spatial-studio").screenshot(path=str(LIVE_MAP_SCREENSHOT))
    page.get_by_role("button", name="공간 작업실 닫기").click()
    page.get_by_role("button", name="MCP 고급 분석").click()
    page.get_by_role("img", name="MCP 고급 분석 차트").wait_for(timeout=60_000)
    mcp_card = page.locator(".mcp-analysis-result")
    assert "recommend_visualizations" in mcp_card.inner_text()
    assert "plot_bar" in mcp_card.inner_text()
    mcp_card.screenshot(path=str(MCP_ANALYSIS_SCREENSHOT))
    assert query_payloads[-1]["region"] == "부산광역시 해운대구"
    assert page.locator("select").nth(1).input_value() == "해운대구"
    page.get_by_role("button", name="보고서에 추가").click()
    assert page.get_by_role("button", name="보고서에서 제외").is_visible()

    composer.fill("분석 지역을 수영구로 변경해줘")
    page.get_by_role("button", name="메시지 보내기").click()
    page.get_by_text("분석 지역을 부산광역시 수영구로 변경했습니다.", exact=True).wait_for()
    assert page.locator("select").nth(1).input_value() == "수영구"

    composer.fill("그럼 5등급만 분석해줘")
    page.get_by_role("button", name="메시지 보내기").click()
    page.get_by_role("heading", name="공간 작업실").wait_for()
    page.locator(".leaflet-overlay-pane path").first.wait_for(timeout=30_000)
    page.get_by_text("13개 대상 · 13개 표시").wait_for(timeout=30_000)
    assert query_payloads[-1]["analysis_context"]["grades"] == ["5"]
    assert "5등급" in page.locator(".analysis-memory").inner_text()
    page.locator(".attribute-table tbody tr").first.click()
    assert page.get_by_text("선택 피처").is_visible()
    page.get_by_role("button", name="이 격자를 대화에서 분석").click()
    assert "격자의 위험 요인을" in composer_value(page)
    page.screenshot(path=str(SPATIAL_SCREENSHOT))
    page.get_by_role("button", name="공간 작업실 닫기").click()

    composer.fill("수영구와 해운대구를 비교해줘")
    page.get_by_role("button", name="메시지 보내기").click()
    page.get_by_role("heading", name="지역 비교 분석").wait_for(timeout=30_000)
    page.get_by_text("50.6%", exact=True).wait_for(timeout=30_000)
    comparison_card = page.locator(".comparison-message")
    comparison_card.screenshot(path=str(COMPARISON_SCREENSHOT))
    comparison_card.get_by_role("button", name="보고서에 추가").click()
    assert comparison_card.get_by_role("button", name="보고서에서 제외").is_visible()
    page.get_by_role("button", name="지도에서 보기: 부산광역시 해운대구").click()
    page.get_by_role("heading", name="공간 작업실").wait_for(timeout=30_000)
    page.get_by_text("부산광역시 해운대구", exact=True).wait_for(timeout=30_000)
    page.get_by_role("button", name="공간 작업실 닫기").click()

    composer.fill("수영구 보고서 작성해줘")
    page.get_by_role("button", name="메시지 보내기").click()

    page.locator(".status-badge.complete").wait_for(timeout=120_000)
    assert page.get_by_role("link", name="Markdown").is_visible()
    assert page.locator(".spatial-figure img").count() == 1
    assert page.locator(".chart-strip img").count() > 0
    assert page.get_by_text("대화에서 선택한 추가 분석").is_visible()
    assert page.get_by_text("해운대구의 원자료를 기준으로 분석했습니다.").count() >= 2
    page.wait_for_function(
        "() => [...document.querySelectorAll('.inline-visuals img')]"
        ".every((image) => image.complete && image.naturalWidth > 0)"
    )
    page.locator(".spatial-figure").scroll_into_view_if_needed()
    page.screenshot(path=str(REPORT_SCREENSHOT))

    page.get_by_role("button", name="보고서 직접 편집").click()
    report_editor = page.get_by_role("textbox", name="보고서 Markdown 편집")
    report_editor.wait_for(timeout=30_000)
    report_editor.fill(report_editor.input_value() + "\n\n> 웹 직접 편집 검증 문장.\n")
    page.locator(".report-editor").screenshot(path=str(DIRECT_EDIT_SCREENSHOT))
    page.get_by_role("button", name="편집 내용 저장").click()
    page.get_by_text("웹 직접 편집 검증 문장.").wait_for(timeout=30_000)
    page.get_by_text("v2", exact=True).wait_for(timeout=30_000)

    grounded_sentence = page.locator(".evidence-sentence.grounded").filter(
        has_text="격자 56개",
    ).first
    grounded_sentence.wait_for(timeout=30_000)
    grounded_sentence.click()
    page.get_by_role("heading", name="문장 근거").wait_for(timeout=30_000)
    page.locator(".evidence-stat").first.wait_for(timeout=30_000)
    page.locator(".evidence-query pre").first.wait_for(timeout=30_000)
    assert page.get_by_text("FTR_IDN", exact=True).is_visible()
    page.locator(".evidence-panel").screenshot(path=str(EVIDENCE_SCREENSHOT))
    page.get_by_role("button", name="지도에서 보기", exact=True).click()
    page.get_by_role("heading", name="공간 작업실").wait_for(timeout=30_000)
    page.locator(".map-focus-context").get_by_text(
        "남천2동 집중", exact=True,
    ).wait_for(timeout=30_000)
    page.locator(".map-loading").wait_for(state="hidden", timeout=30_000)
    page.get_by_text("56개 대상 · 56개 표시", exact=True).wait_for(timeout=30_000)
    page.locator(".spatial-studio").screenshot(path=str(LINKED_MAP_SCREENSHOT))
    page.get_by_role("button", name="공간 작업실 닫기").click()

    composer.fill("정책 제언 부분을 더 짧게 수정해줘")
    page.get_by_role("button", name="메시지 보내기").click()
    page.get_by_text("브라우저 검증용 수정된 정책 제언.").wait_for(timeout=30_000)
    assert revision_payloads[-1] == {
        "section": "6.2 정책 제언",
        "instruction": "정책 제언 부분을 더 짧게 수정해줘",
    }
    page.screenshot(path=str(REVISION_SCREENSHOT))

    page.get_by_role("button", name="분석 작업 이력 열기").click()
    history_panel = page.get_by_role("dialog", name="분석 작업 이력")
    history_panel.wait_for(timeout=30_000)
    history_panel.get_by_text(
        "부산광역시 수영구 · 부산광역시 해운대구 지역 비교",
        exact=True,
    ).wait_for(timeout=30_000)
    history_panel.get_by_text("부산광역시 수영구 보고서 작성", exact=True).wait_for()
    history_panel.screenshot(path=str(HISTORY_SCREENSHOT))
    browser.close()

assert not console_errors, console_errors
print(
    "E2E passed: "
    f"{HOME_SCREENSHOT}, {SPATIAL_SCREENSHOT}, {REPORT_SCREENSHOT}, "
    f"{DIRECT_EDIT_SCREENSHOT}, {REVISION_SCREENSHOT}, {LIVE_MAP_SCREENSHOT}, "
    f"{HISTORY_SCREENSHOT}"
)
