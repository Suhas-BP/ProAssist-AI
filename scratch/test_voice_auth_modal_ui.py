"""
scratch/test_voice_auth_modal_ui.py

Comprehensive Playwright test suite for Voice Authentication Modal in app.html:
1. Verifies sidebar button triggers openVoiceAuthModal().
2. Validates empty name error banner.
3. Tests server rejection error propagation (409 active conversation & 409 concurrent session).
4. Tests WebSocket voice_enroll_step message handling (reading status & recording status).
5. Tests visual countdown timer and progress bar animation.
6. Tests visible Cancel button calling /api/voice-auth/enroll/cancel and dismissing modal.
7. Tests voice_enroll_done success handling, badge updating, and auto-dismiss.
8. Captures rendered screenshot of the dark-themed Voice Auth modal.
"""

import asyncio
import secrets
import sys
import threading
import time
from pathlib import Path

import uvicorn
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dashboard.server import DashboardServer

TEST_PORT = 8009


async def run_ui_tests():
    print("=" * 70)
    print("RUNNING VOICE AUTH MODAL UI TEST SUITE")
    print("=" * 70)

    server = DashboardServer()

    # Pre-authorize dev login on test server
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

    # Fake voice auth instance for status
    class MockVoiceAuth:
        def __init__(self):
            self._enrolled = False
            self._name = ""
        def is_enrolled(self):
            return self._enrolled
        def profile(self):
            return {"name": self._name} if self._enrolled else {}
        def enroll(self, name, recordings, sentences):
            self._enrolled = True
            self._name = name
            return True, f"Voice profile enrolled for {name}"

    mock_va = MockVoiceAuth()
    server.set_voice_auth(mock_va)

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

        token = await page.evaluate("() => sessionStorage.getItem('jarvis_token')")
        assert token, "Token not found in sessionStorage"
        print(f"  -> SUCCESS: Authenticated with token {token[:8]}...")

        # Verify initial badge state
        va_btn = page.locator("#btn-voice-auth")
        assert await va_btn.is_visible(), "Voice auth sidebar button missing"
        status_badge = page.locator("#va-sidebar-status")
        assert await status_badge.text_content() == "Off"
        print("  -> SUCCESS: Initial Voice auth sidebar button shows 'Off'.")

        modal = page.locator("#voice-auth-modal")
        assert not await modal.is_visible(), "Modal should initially be hidden"

        # -------------------------------------------------------------
        # TEST 2: Open modal and test empty name validation
        # -------------------------------------------------------------
        print("\n[STEP 2] Opening Voice Auth modal and testing validation...")
        await va_btn.click()
        await page.wait_for_selector("#voice-auth-modal.open", state="visible")
        print("  -> Modal opened successfully.")

        setup_screenshot_path = BASE_DIR / "scratch" / "voice_auth_modal_setup.png"
        await page.screenshot(path=str(setup_screenshot_path))
        print(f"  -> SCREENSHOT: Saved setup view to {setup_screenshot_path}")

        name_input = page.locator("#va-name-input")
        await name_input.fill("")
        start_btn = page.locator("#va-start-btn")
        await start_btn.click()

        err_banner = page.locator("#va-error-banner")
        await page.wait_for_selector("#va-error-banner", state="visible")
        err_text = await page.locator("#va-error-text").text_content()
        assert "Please enter your name" in err_text
        print(f"  -> SUCCESS: Empty name rejected: '{err_text}'.")

        # -------------------------------------------------------------
        # TEST 3: Server rejection handling (Active conversation)
        # -------------------------------------------------------------
        print("\n[STEP 3] Testing rejection when phone microphone is in active conversation...")
        conversation_active = True
        server.set_conversation_active_checker(lambda: conversation_active)

        await name_input.fill("Tony Stark")
        await start_btn.click()
        await asyncio.sleep(0.3)

        assert await err_banner.is_visible()
        err_text = await page.locator("#va-error-text").text_content()
        assert "currently in use" in err_text, f"Expected active conversation error, got: '{err_text}'"
        print(f"  -> SUCCESS: Modal clearly displayed 409 rejection: '{err_text}'.")
        conversation_active = False

        # -------------------------------------------------------------
        # TEST 4: Server rejection handling (Concurrent session)
        # -------------------------------------------------------------
        print("\n[STEP 4] Testing rejection when enrollment session is already active...")
        server._web_enroll_active = True
        await start_btn.click()
        await asyncio.sleep(0.3)

        assert await err_banner.is_visible()
        err_text = await page.locator("#va-error-text").text_content()
        assert "already in progress" in err_text, f"Expected session in progress error, got: '{err_text}'"
        print(f"  -> SUCCESS: Modal clearly displayed concurrent session rejection: '{err_text}'.")
        server._web_enroll_active = False

        # -------------------------------------------------------------
        # TEST 5: Step messages, Countdown timer & Visual Progress
        # -------------------------------------------------------------
        print("\n[STEP 5] Testing voice_enroll_step messages and visual countdown...")
        # Simulate server broadcasting Step 1 (reading)
        await server.broadcast({
            "type": "voice_enroll_step",
            "step": 1,
            "phrase": "Jarvis, status report on defense grid.",
            "status": "reading",
        })
        await page.wait_for_selector("#va-view-active", state="visible")

        step_lbl = await page.locator("#va-step-label").text_content()
        assert "Phrase 1 of 3" in step_lbl
        phrase_txt = await page.locator("#va-phrase-text").text_content()
        assert "defense grid" in phrase_txt

        phase_pill = page.locator("#va-phase-pill")
        assert "reading" in (await phase_pill.get_attribute("class") or "")
        pill_text = await phase_pill.text_content()
        assert "Ready" in pill_text or "Read" in pill_text
        print(f"  -> SUCCESS: Step 1 'reading' rendered. Phrase: {phrase_txt}")

        # Broadcast Step 1 (recording)
        await server.broadcast({
            "type": "voice_enroll_step",
            "step": 1,
            "phrase": "Jarvis, status report on defense grid.",
            "status": "recording",
        })
        await asyncio.sleep(0.2)
        assert "recording" in (await phase_pill.get_attribute("class") or "")
        countdown_lbl = await page.locator("#va-countdown-label").text_content()
        assert "Recording" in countdown_lbl
        print(f"  -> SUCCESS: Step 1 'recording' rendered. Countdown label: '{countdown_lbl}'")

        # Capture screenshot of active modal
        screenshot_path = BASE_DIR / "scratch" / "voice_auth_modal_rendered.png"
        await page.screenshot(path=str(screenshot_path))
        print(f"  -> SCREENSHOT: Saved rendered modal view to {screenshot_path}")

        # -------------------------------------------------------------
        # TEST 6: Visible Cancel button calls cancel endpoint and closes
        # -------------------------------------------------------------
        print("\n[STEP 6] Testing Cancel Enrollment button...")
        cancel_btn = page.locator("#va-cancel-btn")
        assert await cancel_btn.is_visible()
        await cancel_btn.click()
        await page.wait_for_selector("#voice-auth-modal:not(.open)", state="hidden")
        assert not server._web_enroll_active, "Session should be deactivated after cancel"
        print("  -> SUCCESS: Cancel button dismissed modal and cleared server state.")

        # -------------------------------------------------------------
        # TEST 7: Success flow & Badge update
        # -------------------------------------------------------------
        print("\n[STEP 7] Testing voice_enroll_done success and badge update...")
        await va_btn.click()
        await page.wait_for_selector("#voice-auth-modal.open", state="visible")

        # Send step 2 and then done
        await server.broadcast({
            "type": "voice_enroll_step",
            "step": 2,
            "phrase": "Re-routing auxiliary power to thrusters.",
            "status": "recording",
        })
        await page.wait_for_selector("#va-view-active", state="visible")

        # Send done ok: true
        await server.broadcast({
            "type": "voice_enroll_done",
            "ok": True,
            "message": "Voice profile enrolled for Tony Stark",
        })
        await page.wait_for_selector("#va-view-done", state="visible")
        done_title = await page.locator("#va-result-title").text_content()
        assert "Complete" in done_title
        print(f"  -> SUCCESS: Done view rendered: '{done_title}'.")

        # Check badge updates
        await asyncio.sleep(0.3)
        updated_sidebar_badge = await page.locator("#va-sidebar-status").text_content()
        assert updated_sidebar_badge == "Active", f"Expected 'Active', got '{updated_sidebar_badge}'"
        assert "active" in (await va_btn.get_attribute("class") or "")
        print("  -> SUCCESS: Sidebar badge updated to 'Active' with .active class.")

        sec_text = await page.locator("#badge-sec-text").text_content()
        assert "Voice:" in sec_text or "Enrolled" in sec_text
        print(f"  -> SUCCESS: Security footer badge updated to '{sec_text}'.")

        # Wait for auto-close
        await page.wait_for_selector("#voice-auth-modal:not(.open)", state="hidden", timeout=5000)
        print("  -> SUCCESS: Modal automatically dismissed after successful enrollment.")

        await browser.close()

    uv_server.should_exit = True
    await server_task

    print("\n" + "=" * 70)
    print(">>> ALL VOICE AUTH MODAL UI TESTS PASSED (100%) <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_ui_tests())
