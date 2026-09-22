import asyncio
import json
import urllib.request
from pathlib import Path
from playwright.async_api import async_playwright
import sys

BASE_DIR = Path(__file__).resolve().parent.parent

async def test_memory_endpoint_and_modal():
    print("\n--- 1. Testing GET /api/memory HTTP Endpoint ---")
    # Fetch permanent dev key / token from start_dashboard setup
    # Or get token from dev-login in browser
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        page = await browser.new_page()

        print("[TEST] Logging into dashboard...")
        await page.goto("http://localhost:8000/dev-login")
        await page.wait_for_url("http://localhost:8000/")
        await page.wait_for_load_state("networkidle")

        # Get token from sessionStorage
        token = await page.evaluate("() => sessionStorage.getItem('jarvis_token')")
        assert token, "Could not retrieve jarvis_token from sessionStorage"

        # Verify unauthorized request returns 401
        try:
            req_unauth = urllib.request.Request("http://localhost:8000/api/memory")
            urllib.request.urlopen(req_unauth)
            raise AssertionError("Expected HTTP 401 for unauthorized request")
        except urllib.error.HTTPError as e:
            assert e.code == 401, f"Expected 401, got {e.code}"
            print("[PASS] Unauthorized GET /api/memory returns HTTP 401.")

        # Verify authorized request returns 200 and entries list
        req_auth = urllib.request.Request(
            "http://localhost:8000/api/memory",
            headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req_auth) as resp:
            assert resp.status == 200, f"Expected 200, got {resp.status}"
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("ok") is True, "Response missing ok: True"
            entries = data.get("entries", [])
            print(f"[PASS] Authorized GET /api/memory returned {len(entries)} entries.")
            if entries:
                first = entries[0]
                print(f"       Sample entry: category='{first.get('category')}', key='{first.get('key')}', value='{first.get('value')[:40]}...'")

        print("\n--- 2. Testing Memory Modal UI in Browser ---")
        modal = page.locator("#memory-modal")
        btn_memory = page.locator("#btn-memory")

        # Modal initially hidden
        is_visible_initially = await modal.is_visible()
        assert not is_visible_initially, "Modal should not be visible initially"

        # Click Memory button
        print("[TEST] Clicking '#btn-memory' button...")
        await btn_memory.click()
        await page.wait_for_selector("#memory-modal.open", state="visible")
        print("[PASS] Modal has .open class and is visible.")

        # Wait for entries to render
        await page.wait_for_selector("#memory-list .memory-item, #memory-list .modal-empty")
        items = await page.locator("#memory-list .memory-item").count()
        print(f"[PASS] Rendered {items} memory items in modal list.")

        # Check styling of modal panel
        panel = page.locator(".modal-panel")
        bg = await panel.evaluate("el => window.getComputedStyle(el).backgroundColor")
        border = await panel.evaluate("el => window.getComputedStyle(el).borderColor")
        print(f"[STYLE] Modal panel background: {bg}, border: {border}")

        # Capture screenshot
        screenshot_path = "D:/Mark-LIV-main/scratch/memory_modal_rendered.png"
        await page.screenshot(path=screenshot_path)
        print(f"[SCREENSHOT] Saved modal view to {screenshot_path}")

        # Test closing with close button
        close_btn = page.locator(".modal-close-btn")
        await close_btn.click()
        await page.wait_for_selector("#memory-modal:not(.open)", state="hidden")
        print("[PASS] Modal closed via close button.")

        # Reopen and test closing with Escape key
        await btn_memory.click()
        await page.wait_for_selector("#memory-modal.open", state="visible")
        await page.keyboard.press("Escape")
        await page.wait_for_selector("#memory-modal:not(.open)", state="hidden")
        print("[PASS] Modal reopened and closed via Escape key.")

        await browser.close()
        print("\n>>> ALL MEMORY MODAL TESTS PASSED (100%) <<<")

if __name__ == "__main__":
    asyncio.run(test_memory_endpoint_and_modal())
