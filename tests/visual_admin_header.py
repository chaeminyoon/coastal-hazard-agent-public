import json
import traceback
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright


output = Path(__file__).resolve().parents[1] / "outputs" / "visual" / "admin-header.png"
output.parent.mkdir(parents=True, exist_ok=True)
auth_user = {"id": "admin-1", "username": "admin", "role": "admin"}


def route_api(route):
    path = route.request.url.split("?", 1)[0]
    print(f"API_ROUTE {path}", flush=True)
    if path.endswith("/api/regions"):
        route.fulfill(
            status=200,
            content_type="application/json",
            headers={"X-Auth-User": quote(json.dumps(auth_user))},
            body=json.dumps(
                [{"name": "부산광역시", "districts": ["수영구", "해운대구"]}],
                ensure_ascii=False,
            ),
        )
        return
    if path.endswith("/api/auth/login"):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "user": auth_user,
                    "csrf_token": "visual-test-token",
                }
            ),
        )
        return
    route.fulfill(status=404, content_type="application/json", body="{}")


try:
    print("VISUAL_CHECK starting", flush=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
        page.set_default_timeout(10_000)
        page.route("**/api/**", route_api)
        page.goto("http://127.0.0.1:5173", wait_until="networkidle")
        login_inputs = page.locator(".login-card input").count()
        print(
            f"PAGE_STATE login_inputs={login_inputs} chat_headers={page.locator('.chat-header').count()}",
            flush=True,
        )
        if login_inputs:
            page.locator(".login-card input").nth(0).fill("admin")
            page.locator(".login-card input").nth(1).fill("admin-password")
            page.locator(".login-card button[type='submit']").click()
        page.locator(".chat-header").wait_for()

        controls = [
            page.locator(".header-map-button"),
            page.locator(".region-picker"),
            page.locator(".account-summary"),
        ]
        heights = [round(control.bounding_box()["height"], 1) for control in controls]
        assert max(heights) - min(heights) <= 1, heights
        page.locator(".chat-header").screenshot(path=str(output))
        print(f"ADMIN_HEADER_VISUAL_OK heights={heights} screenshot={output}", flush=True)
        browser.close()
except Exception:
    traceback.print_exc()
    raise
