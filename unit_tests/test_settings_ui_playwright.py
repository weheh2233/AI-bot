"""设置页浏览器回归：加载真实 HTML/CSS/JS，接口使用隔离数据，不访问开发库。"""

from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
TEST_URL = "http://127.0.0.1:4173/"
PERSONA = {
    "id": 1, "name": "默认助手", "version": 1, "is_system": True,
    "role_definition": "学习助手", "tone": "自然", "style_rules": "", "constraints": "",
}


def serve_test_request(route):
    """仅浏览器测试用的接口替身；所有请求都被拦截，不依赖运行中的服务。"""
    path = urlparse(route.request.url).path
    if path.startswith("/api/"):
        assert route.request.method == "GET", "本测试不应修改账户或调用模型"
        if path.startswith("/api/conversations/web-"):
            route.fulfill(status=404, json={"detail": "新会话尚未保存"})
            return
        responses = {
            "/api/settings/model": {
                "configured": False, "base_url": None, "model_name": None,
                "updated_at": None, "last_used_at": None,
            },
            "/api/personas": [PERSONA],
            "/api/users/me/default-persona": PERSONA,
            "/api/documents": [],
            "/api/conversations": [],
        }
        assert path in responses, f"未预期的接口请求：{path}"
        route.fulfill(json=responses[path])
    elif path == "/":
        route.fulfill(path=WEB_DIR / "index.html", content_type="text/html; charset=utf-8")
    elif path.startswith("/assets/"):
        route.fulfill(path=WEB_DIR / path.lstrip("/"))
    else:
        route.fulfill(status=404)


@pytest.fixture
def page(request):
    width, height = request.param
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("""
                localStorage.setItem('ai_bot_token', 'ui-test-token');
                localStorage.setItem('ai_bot_username', 'UI Test');
            """)
            page.route("**/*", serve_test_request)
            page.goto(TEST_URL, wait_until="networkidle")
            expect(page.locator("#auth-screen")).to_be_hidden()
            yield page
            assert not errors, errors
        finally:
            browser.close()


def assert_settings_fills_viewport(page):
    # is_visible() 只能证明有尺寸，不能发现 900px 的页面被压成 68px。
    bounds = page.locator("#settings-view").bounding_box()
    assert bounds is not None
    assert bounds["y"] == pytest.approx(0, abs=1)
    assert bounds["height"] == pytest.approx(page.viewport_size["height"], abs=1)
    assert bounds["width"] == pytest.approx(page.viewport_size["width"], abs=1)
    assert page.locator("#settings-view").evaluate(
        "el => el.scrollWidth <= el.clientWidth"
    ), "设置页不应出现横向溢出"


@pytest.mark.parametrize(
    "page", [(1280, 900), (900, 700), (390, 844), (390, 560), (320, 568)], indirect=True
)
def test_settings_overview_and_detail_views(page, tmp_path):
    page.locator("#focus-settings").click()
    assert_settings_fills_viewport(page)
    expect(page.locator("#settings-overview h1")).to_be_in_viewport(ratio=1)
    assert page.locator("[data-settings-detail]").count() == 3
    # 截图必须在自动滚动到控件之前，避免自动滚动掩盖空白首屏。
    page.screenshot(path=str(tmp_path / "overview.png"))

    controls = {
        "model": "#settings-base-url",
        "password": "#settings-old-password",
        "appearance": "input[name='settings-font-size'][value='large']",
    }
    for detail, control in controls.items():
        page.locator(f"[data-settings-detail='{detail}']").click()
        panel = page.locator(f"#settings-{detail}-detail")
        assert_settings_fills_viewport(page)
        expect(page.locator("#settings-overview")).to_be_hidden()
        for other in controls:
            if other != detail:
                expect(page.locator(f"#settings-{other}-detail")).to_be_hidden()
        assert page.locator("#settings-view").evaluate("el => el.scrollTop") == 0
        # IntersectionObserver 会计入父容器裁切，标题和表单必须真的在首屏内。
        expect(panel.locator("h1")).to_be_in_viewport(ratio=1)
        expect(page.locator(control)).to_be_in_viewport(ratio=1)
        page.screenshot(path=str(tmp_path / f"{detail}.png"))
        if detail == "appearance":
            page.locator(control).check()
            page.locator("input[name='settings-send-key'][value='ctrl-enter']").check()
            assert page.evaluate("localStorage.getItem('ai_bot_font_size')") == "large"
            assert page.evaluate("localStorage.getItem('ai_bot_send_key')") == "ctrl-enter"
        else:
            page.locator(control).fill("https://example.com/v1" if detail == "model" else "test")
        # 小屏先滚到页尾，再返回；下一页必须重新从顶部显示。
        page.locator("#settings-view").evaluate("el => el.scrollTop = el.scrollHeight")
        panel.locator("[data-settings-back]").click()
        assert page.locator("#settings-view").evaluate("el => el.scrollTop") == 0
        expect(page.locator("#settings-overview h1")).to_be_in_viewport(ratio=1)

    page.locator("#exit-settings").click()
    expect(page.locator("#chat-view")).to_be_visible()
    expect(page.locator(".rail")).to_be_visible()
    expect(page.locator(".topbar")).to_be_visible()
    expect(page.locator("#message-input")).to_be_in_viewport(ratio=1)
    page.locator("#focus-settings").click()
    assert_settings_fills_viewport(page)
    expect(page.locator("#settings-overview h1")).to_be_in_viewport(ratio=1)
    page.locator("[data-settings-detail='appearance']").click()
    expect(page.locator("input[name='settings-font-size'][value='large']")).to_be_checked()
    expect(page.locator("input[name='settings-send-key'][value='ctrl-enter']")).to_be_checked()
    print(f"\n设置页截图：{tmp_path}")
