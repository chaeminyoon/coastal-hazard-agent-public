import json

from playwright.sync_api import Route, sync_playwright


def handle_api(route: Route) -> None:
    path = route.request.url.split("?", 1)[0]
    if path.endswith("/api/regions"):
        payload = [{"name": "부산광역시", "districts": ["수영구"]}]
    elif path.endswith("/api/queries"):
        request = json.loads(route.request.post_data or "{}")
        payload = {
            "question": request["question"],
            "region": request["region"],
            "answer": "비교 범위를 함께 조회하지 못해 답변을 확정하지 않았습니다.",
            "queries": ["SELECT AVG(elderly) FROM selected_grid"],
            "results": [{"columns": ["selected_avg"], "rows": [[50.5]]}],
            "grounded": False,
            "scope_valid": False,
            "scope": {
                "type": "spatial_selection",
                "selection_id": "selection-1",
                "selected_count": 421,
            },
        }
    else:
        payload = {}
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(payload, ensure_ascii=False),
    )


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        headless=True,
    )
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    console_errors: list[str] = []
    failed_responses: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on(
        "response",
        lambda response: failed_responses.append(
            f"{response.status} {response.url}"
        )
        if response.status >= 400
        else None,
    )
    page.route("**/api/**", handle_api)
    page.goto("http://127.0.0.1:5173")
    page.wait_for_load_state("networkidle")
    page.locator("textarea").fill("이 영역의 고령인구 평균과 지역 전체 평균을 비교해줘")
    page.get_by_role("button", name="메시지 보내기").click()
    rejected = page.get_by_role(
        "button",
        name="검증 실패 답변은 보고서에 추가할 수 없습니다",
    )
    rejected.wait_for()
    assert rejected.is_disabled()
    assert page.get_by_text("검증 실패", exact=True).is_visible()
    assert not failed_responses, failed_responses
    browser.close()

print(
    "selection grounding browser flow passed",
    {"console_errors": console_errors, "failed_responses": failed_responses},
)
