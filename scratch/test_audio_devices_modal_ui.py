"""
scratch/test_audio_devices_modal_ui.py

Comprehensive Playwright test suite for Audio Devices Modal in app.html:
1. Verifies sidebar button triggers openAudioModal().
2. Verifies modal renders dark theme, header, live mic meter, and device options.
3. Tests selecting a specific microphone, updating localStorage, checkmark, and sidebar badge.
4. Tests reverting to System Default microphone.
5. Tests closing via close button and Escape key.
6. Captures rendered screenshot of the Audio Devices modal.
"""

import asyncio
import secrets
import sys
from pathlib import Path

import uvicorn
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dashboard.server import DashboardServer

TEST_PORT = 8011


async def run_audio_ui_tests():
    print("=" * 70)
    print("RUNNING AUDIO DEVICES MODAL UI TEST SUITE")
    print("=" * 70)

    server = DashboardServer()

    dev_key = "123456"
    tok = secrets.token_urlsafe(32)
    server._tokens.add(tok)
    server._token_keys[tok] = dev_key
    server._aes_key(dev_key)

    @server.app.get("/dev-login")
    async def dev_login():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f"""<!DOCTYPE html><html><body>
        <script>
          sessionStorage.setItem('jarvis_token', '{tok}');
          sessionStorage.setItem('jarvis_key', '{dev_key}');
          location.replace('/');
        </script>
        </body></html>""")

    config = uvicorn.Config(
        server.app,
        host="127.0.0.1",
        port=TEST_PORT,
        log_level="warning",
    )
    uv_server = uvicorn.Server(config)
    server_task = asyncio.create_task(uv_server.serve())
    await asyncio.sleep(0.5)

    base_url = f"http://127.0.0.1:{TEST_PORT}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            channel="chrome",
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        context = await browser.new_context(
            permissions=["microphone"],
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        print("\n[STEP 1] Logging into dashboard...")
        await page.goto(f"{base_url}/dev-login")
        await page.wait_for_url(f"{base_url}/")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(0.3)

        btn_audio = page.locator("#btn-audio-devices")
        assert await btn_audio.is_visible(), "Audio devices sidebar button missing"
        badge = page.locator("#audio-sidebar-status")
        assert (await badge.text_content()).strip() == "Default"
        print("  -> SUCCESS: Sidebar button #btn-audio-devices visible with badge 'Default'.")

        modal = page.locator("#audio-modal")
        assert not await modal.is_visible(), "Audio modal should initially be hidden"

        # -------------------------------------------------------------
        # TEST 2: Open modal and verify elements
        # -------------------------------------------------------------
        print("\n[STEP 2] Opening Audio Devices modal...")
        await btn_audio.click()
        await page.wait_for_selector("#audio-modal.open", state="visible")
        print("  -> SUCCESS: Modal has .open class and is visible.")

        # Check title and elements
        title = await page.locator("#audio-modal-title").text_content()
        assert "Audio Input Devices" in title
        meter = page.locator("#audio-modal .audio-meter-track")
        assert await meter.is_visible()
        print(f"  -> SUCCESS: Title '{title}' and live meter track visible.")

        # Wait for device list to populate
        await page.wait_for_selector("#audio-input-list .audio-device-item")
        device_items = page.locator("#audio-input-list .audio-device-item")
        count = await device_items.count()
        assert count >= 1, "Expected at least 1 device item (System Default)"
        print(f"  -> SUCCESS: Rendered {count} audio input device option(s).")

        # Capture screenshot
        screenshot_path = BASE_DIR / "scratch" / "audio_devices_modal_rendered.png"
        await page.screenshot(path=str(screenshot_path))
        print(f"  -> SCREENSHOT: Saved rendered modal view to {screenshot_path}")

        # -------------------------------------------------------------
        # TEST 3: Select a device option
        # -------------------------------------------------------------
        print("\n[STEP 3] Testing device selection...")
        if count > 1:
            # Click the second device (first physical/fake device)
            second_device = device_items.nth(1)
            dev_name = await second_device.locator(".audio-device-name span").text_content()
            await second_device.click()
            await asyncio.sleep(0.2)

            # Check that it gets .selected class
            classes = await second_device.get_attribute("class") or ""
            assert "selected" in classes
            # Check localStorage
            pref_id = await page.evaluate("() => localStorage.getItem('agent_preferred_mic_id')")
            assert pref_id, "Preferred mic ID not set in localStorage"
            badge_txt = await badge.text_content()
            assert badge_txt.strip() == "Custom"
            print(f"  -> SUCCESS: Selected '{dev_name}', localStorage id='{pref_id[:16]}...', sidebar badge='{badge_txt}'.")

        # -------------------------------------------------------------
        # TEST 4: Revert to System Default
        # -------------------------------------------------------------
        print("\n[STEP 4] Reverting to System Default microphone...")
        default_item = device_items.first
        await default_item.click()
        await asyncio.sleep(0.2)
        classes_def = await default_item.get_attribute("class") or ""
        assert "selected" in classes_def
        pref_id_reverted = await page.evaluate("() => localStorage.getItem('agent_preferred_mic_id')")
        assert pref_id_reverted is None, "Expected preferred mic ID to be cleared"
        badge_txt_def = await badge.text_content()
        assert badge_txt_def.strip() == "Default"
        print("  -> SUCCESS: System Default selected, localStorage cleared, sidebar badge reset to 'Default'.")

        # -------------------------------------------------------------
        # TEST 5: Close modal via Done / Close button and Escape key
        # -------------------------------------------------------------
        print("\n[STEP 5] Testing modal dismissal...")
        close_btn = page.locator("#audio-modal .modal-close-btn")
        await close_btn.click()
        await page.wait_for_selector("#audio-modal:not(.open)", state="hidden")
        print("  -> SUCCESS: Modal closed via close button.")

        # Reopen and test Escape
        await btn_audio.click()
        await page.wait_for_selector("#audio-modal.open", state="visible")
        await page.keyboard.press("Escape")
        await page.wait_for_selector("#audio-modal:not(.open)", state="hidden")
        print("  -> SUCCESS: Modal reopened and dismissed via Escape key.")

        await browser.close()

    uv_server.should_exit = True
    await server_task

    print("\n" + "=" * 70)
    print(">>> ALL AUDIO DEVICES MODAL UI TESTS PASSED (100%) <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_audio_ui_tests())
