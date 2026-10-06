"""Optional browser acceptance checks; run against the local full FastAPI server.

python tests/vocabulary_browser.py --browser "C:/Program Files/Google/Chrome/Application/chrome.exe" --screenshots PATH
Requires the optional development dependency: pip install playwright
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8891")
    parser.add_argument("--screenshots", required=True)
    args = parser.parse_args()
    output = Path(args.screenshots)
    output.mkdir(parents=True, exist_ok=True)
    sample = [
        {"word": "resilient", "phonetic": "/rɪˈzɪliənt/", "zh": "adj. 有韧性的；适应力强的", "createdAt": 1791244800000},
        {"word": "articulate", "phonetic": "/ɑːˈtɪkjuleɪt/", "zh": "v. 清楚地表达", "createdAt": 1791158400000},
    ] + [{"word": f"word{i:02}", "zh": f"测试释义 {i}", "createdAt": 1791000000000 + i} for i in range(25)]
    state = {"status": 200, "body": {"available": True, "stale": False, "checkedAt": "2026-10-06T06:00:00Z", "words": sample}}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.browser, headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1050}, reduced_motion="reduce")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append({"url": page.url, "stack": error.stack}))
        page.route("**/api/v1/vocabulary", lambda route: route.fulfill(status=state["status"], content_type="application/json", body=json.dumps(state["body"])))
        page.goto(args.base_url + "/ielts", wait_until="networkidle")
        expect(page.locator("#wordTotal")).to_have_text("27")
        expect(page.locator(".vocab-word")).to_have_count(24)
        expect(page.locator("#nav")).to_be_visible()
        expect(page.locator("#footer")).to_be_attached()
        assert "<!--cy:" not in page.content()
        page.screenshot(path=str(output / "ielts-dark-test-data.png"))
        page.locator("#wordNext").click()
        expect(page.locator(".vocab-word")).to_have_count(3)
        page.locator("#wordSearch").fill("有韧性")
        expect(page.locator(".vocab-word h2")).to_have_text("resilient")
        page.locator("#wordSearch").fill(" ARTICULATE ")
        expect(page.locator(".vocab-word h2")).to_have_text("articulate")
        page.locator("#wordSearch").fill("")
        page.locator("#wordSort").select_option("az")
        expect(page.locator(".vocab-word h2").first).to_have_text("articulate")
        page.locator("#wordSort").select_option("oldest")
        expect(page.locator(".vocab-word h2").first).to_have_text("word00")
        page.locator("#wordSort").select_option("newest")
        expect(page.locator(".vocab-word h2").first).to_have_text("resilient")
        page.locator("#wordMask").click()
        expect(page.locator(".vocab-meaning").first).to_be_hidden()
        page.locator(".vocab-reveal").first.click()
        expect(page.locator(".vocab-meaning").first).to_be_visible()
        # An unchanged sync preserves the user's current study state.
        page.locator("#wordSync").click()
        expect(page.locator("#wordSync")).to_be_enabled()
        expect(page.locator(".vocab-meaning").first).to_be_visible()
        state["status"] = 503
        page.locator("#wordSync").click()
        expect(page.locator("#wordNotice")).to_contain_text("已保留当前记录")
        expect(page.locator("#wordTotal")).to_have_text("27")
        state["status"] = 200
        state["body"]["stale"] = True
        page.locator("#wordSync").click()
        expect(page.locator("#wordNotice")).to_contain_text("上次成功获取")
        state["body"]["stale"] = False
        page.locator("#wordSync").click()
        expect(page.locator("#wordNotice")).to_be_hidden()
        page.locator("#wordMask").click()
        # Use the real shared theme switch; compare tokens to the home page.
        page.locator("#themeToggle").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        page.screenshot(path=str(output / "ielts-light-test-data.png"))
        def style_snapshot():
            return page.evaluate("({font: getComputedStyle(document.body).fontFamily, background: getComputedStyle(document.body).backgroundColor})")
        notebook_style = style_snapshot()
        page.goto(args.base_url + "/", wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        assert style_snapshot() == notebook_style
        page.goto(args.base_url + "/ielts", wait_until="networkidle")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / "ielts-mobile-test-data.png"))
        page.locator("#menuBtn").click()
        expect(page.locator(".mobile-menu a[href='/ielts']")).to_be_visible()
        page.locator(".mobile-menu a[href='/ielts']").click()
        # Render untrusted vocabulary literally rather than executing HTML.
        state["body"]["words"] = [{"word": '<img src=x onerror="window.vocabXss=1">', "zh": "<script>window.vocabXss=1</script>"}]
        page.locator("#wordSync").click()
        expect(page.locator("#wordTotal")).to_have_text("1")
        expect(page.locator("#wordList img, #wordList script")).to_have_count(0)
        assert page.evaluate("window.vocabXss === undefined")
        state["body"]["words"] = []
        page.locator("#wordSync").click()
        expect(page.locator("#wordTotal")).to_have_text("0")
        expect(page.locator("#wordList")).to_contain_text("还没有单词记录")
        state["status"] = 503
        page.reload(wait_until="networkidle")
        expect(page.locator("#wordTotal")).to_have_text("—")
        expect(page.locator("#wordList")).to_contain_text("暂时无法获取单词")
        assert not page.evaluate("Object.keys(localStorage).some(k => /word|vocab/.test(k))")
        notebook_errors = [error for error in errors if error["url"].endswith("/ielts")]
        assert not notebook_errors, notebook_errors
        if errors:
            print("Existing home-page script error observed during style comparison:", errors)
        browser.close()
    print("PASS: browser search, sort, pagination, study mode, theme parity, mobile navigation, sync failures/recovery, empty state, XSS and no local vocabulary storage")


if __name__ == "__main__":
    run()
