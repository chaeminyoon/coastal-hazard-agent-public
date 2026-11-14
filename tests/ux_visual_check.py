from pathlib import Path

from playwright.sync_api import ConsoleMessage, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(parents=True, exist_ok=True)
console_errors: list[str] = []
failed_responses: list[str] = []


def capture_console_error(message: ConsoleMessage) -> None:
    if message.type == "error":
        console_errors.append(f"{message.text} @ {message.location}")


def capture_failed_response(response) -> None:
    if response.status >= 400:
        failed_responses.append(f"{response.status} {response.url}")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        headless=True,
    )

    desktop = browser.new_page(viewport={"width": 1440, "height": 980})
    desktop.on("console", capture_console_error)
    desktop.on("response", capture_failed_response)
    desktop.goto("http://127.0.0.1:5173")
    desktop.wait_for_load_state("networkidle")
    desktop.get_by_role("heading", name="질문에서 근거 있는 보고서까지.").wait_for()
    desktop.get_by_placeholder(
        "연안 데이터에 대해 질문하거나 명령어를 입력하세요",
    ).wait_for()
    assert desktop.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    desktop.screenshot(path=str(OUTPUTS / "ux-redesign-desktop.png"), full_page=True)

    tablet = browser.new_page(viewport={"width": 820, "height": 900})
    tablet.on("console", capture_console_error)
    tablet.on("response", capture_failed_response)
    tablet.goto("http://127.0.0.1:5173")
    tablet.wait_for_load_state("networkidle")
    tablet.get_by_role("button", name="메뉴 열기").click()
    navigation = tablet.get_by_label("주요 탐색")
    navigation.wait_for()
    assert "mobile-open" in (navigation.get_attribute("class") or "")
    assert tablet.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    tablet.screenshot(path=str(OUTPUTS / "ux-redesign-tablet.png"), full_page=True)
    tablet.get_by_role("button", name="탐색 닫기").click()
    assert "mobile-open" not in (navigation.get_attribute("class") or "")

    browser.close()

assert not console_errors, {"console": console_errors, "responses": failed_responses}
print("UX visual checks passed")
