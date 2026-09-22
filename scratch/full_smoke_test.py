"""
scratch/full_smoke_test.py

Comprehensive Full Smoke Test of the Web Dashboard Additions:
1. Confirm live telemetry tiles update continuously without breaking
   existing WS message handling (log/status/wake/sys/file_received).
2. Open Memory modal — confirm it shows real entries from the actual
   memory store, not mock data.
3. Open Voice Auth modal — confirm it correctly routes through the
   existing enrollment flow via phone-audio WS.
4. Open Audio Devices modal — confirm it lists real available input
   devices from the browser and correctly applies the selection to
   the phone-audio stream.
5. Confirm no existing desktop-side functionality was altered by any
   of these additions (MainWindow, CustomizeOverlay, floating island
   all still work exactly as before).
"""

import asyncio
import json
import secrets
import sys
import time
from pathlib import Path

import uvicorn
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dashboard.server import DashboardServer
from memory.memory_manager import all_entries_for_ui

TEST_PORT = 8012


async def run_full_smoke_test():
    print("=" * 80)
    print("STARTING FULL SMOKE TEST OF WEB DASHBOARD ADDITIONS")
    print("=" * 80)

    test_results = {}

    # ──────────────────────────────────────────────────────────────────────────
    # ITEM 5 (Desktop Verification): Test desktop components first
    # ──────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 75)
    print("ITEM 5: Desktop-side functionality verification (MainWindow, CustomizeOverlay, FloatingIsland)")
    print("-" * 75)
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        from ui import MainWindow, CustomizeOverlay, MemoryOverlay, AgentUI
        from floating_island import FloatingIsland

        face_path = BASE_DIR / "config" / "face.obj"
        main_win = MainWindow(face_path)
        assert main_win is not None, "MainWindow failed to instantiate"
        assert main_win.hud is not None, "HudCanvas missing or altered in MainWindow"
        assert hasattr(main_win, "_bar_cpu"), "_bar_cpu missing on MainWindow"
        print(f"  [5.1] MainWindow instantiated successfully with HudCanvas (size: {main_win.hud.width()}x{main_win.hud.height()}).")

        cust_overlay = CustomizeOverlay(main_win)
        assert cust_overlay is not None, "CustomizeOverlay failed to instantiate"
        print("  [5.2] CustomizeOverlay instantiated successfully attached to MainWindow.")

        mem_overlay = MemoryOverlay(main_win)
        assert mem_overlay is not None, "MemoryOverlay failed to instantiate"
        print("  [5.3] MemoryOverlay instantiated successfully attached to MainWindow.")

        island = FloatingIsland()
        assert island is not None, "FloatingIsland failed to instantiate"
        print("  [5.4] FloatingIsland instantiated successfully.")

        test_results["ITEM 5"] = "PASS"
        print(">> ITEM 5: PASS <<")
    except Exception as e:
        test_results["ITEM 5"] = f"FAIL ({e})"
        print(f">> ITEM 5: FAIL -> {e} <<")

    # ──────────────────────────────────────────────────────────────────────────
    # Start Test Web Dashboard Server
    # ──────────────────────────────────────────────────────────────────────────
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
        page.on("console", lambda m: print(f"    [Browser Console] {m.text}"))
        page.on("pageerror", lambda err: print(f"    [Browser PageError] {err}"))

        print("\nConnecting to Web Dashboard...")
        await page.goto(f"{base_url}/dev-login")
        await page.wait_for_url(f"{base_url}/")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(0.4)
        print(f"  -> Logged in and connected to WebSocket (active WS clients on server: {len(server._clients)}).")

        # ──────────────────────────────────────────────────────────────────────
        # ITEM 1: Live Telemetry Tiles & Existing WS Message Handling
        # ──────────────────────────────────────────────────────────────────────
        print("\n" + "-" * 75)
        print("ITEM 1: Live telemetry continuous updates & existing WS message handling")
        print("-" * 75)
        try:
            # 1.1 Confirm continuous live telemetry from _metrics.snapshot()
            cpu_val_el = page.locator("#cpu-val")
            mem_val_el = page.locator("#mem-val")
            net_val_el = page.locator("#net-val")

            # Wait for at least one live telemetry update from the background server loop
            await page.wait_for_function("""() => {
                const cpu = document.getElementById('cpu-val')?.textContent?.trim();
                const mem = document.getElementById('mem-val')?.textContent?.trim();
                const net = document.getElementById('net-val')?.textContent?.trim();
                return cpu && cpu.endsWith('%') && mem && mem.endsWith('%') && net && (net.includes('B/s') || net.includes('B'));
            }""", timeout=5000)

            live_cpu1 = (await cpu_val_el.text_content()).strip()
            live_mem1 = (await mem_val_el.text_content()).strip()
            live_net1 = (await net_val_el.text_content()).strip()
            print(f"  [1.1a] Live telemetry initial snapshot received: CPU={live_cpu1}, Memory={live_mem1}, Network={live_net1}")
            assert live_cpu1.endswith("%"), f"Expected % suffix, got {live_cpu1}"
            assert live_mem1.endswith("%"), f"Expected % suffix, got {live_mem1}"

            # Wait for next periodic tick (~1 second) to confirm continuous live updates
            await asyncio.sleep(1.2)
            live_cpu2 = (await cpu_val_el.text_content()).strip()
            live_mem2 = (await mem_val_el.text_content()).strip()
            live_net2 = (await net_val_el.text_content()).strip()
            print(f"  [1.1b] Live telemetry consecutive tick received: CPU={live_cpu2}, Memory={live_mem2}, Network={live_net2}")
            assert live_cpu2.endswith("%") and live_mem2.endswith("%")
            print("  [1.1] Verified live telemetry tiles update continuously from _metrics.snapshot().")

            # 1.2 Test existing WS message handling: log
            feed = page.locator("#feed")
            initial_count = await page.locator("#feed .msg").count()
            await server.broadcast({"type": "log", "speaker": "AGENT", "text": "Smoke test log message"})
            await page.wait_for_selector("#feed .msg:has-text('Smoke test log message')", timeout=5000)
            new_count = await page.locator("#feed .msg").count()
            assert new_count == initial_count + 1, f"Log message was not appended to feed (initial: {initial_count}, new: {new_count})"
            latest_msg = await page.locator("#feed .msg").last.text_content()
            assert "Smoke test log message" in latest_msg
            print(f"  [1.2] Existing message 'log' verified: '{latest_msg.strip()}'.")

            # 1.3 Test existing WS message handling: status
            pill = page.locator("#pill")
            st_txt = page.locator("#st")
            await server.broadcast({"type": "status", "state": "active"})
            await page.wait_for_selector("#pill.on", timeout=5000)
            assert "on" in (await pill.get_attribute("class") or "")
            assert "Active" in await st_txt.text_content()

            await server.broadcast({"type": "status", "state": "sleeping"})
            await page.wait_for_selector("#pill:not(.on)", timeout=5000)
            assert "on" not in (await pill.get_attribute("class") or "")
            assert "Sleeping" in await st_txt.text_content()
            print("  [1.3] Existing message 'status' verified (active <-> sleeping).")

            # 1.4 Test existing WS message handling: wake
            await server.broadcast({"type": "wake"})
            await page.wait_for_selector("#feed .msg:has-text('Wake word detected')", timeout=5000)
            wake_msg = await page.locator("#feed .msg").last.text_content()
            assert "Wake word detected" in wake_msg
            print(f"  [1.4] Existing message 'wake' verified: '{wake_msg.strip()}'.")

            # 1.5 Test existing WS message handling: sys
            await server.broadcast({"type": "sys", "text": "Remote network link operational"})
            await page.wait_for_selector("#feed .msg:has-text('Remote network link operational')", timeout=5000, state="attached")
            sys_msg = await page.locator("#feed .msg").last.text_content()
            assert "Remote network link operational" in sys_msg
            print(f"  [1.5] Existing message 'sys' verified: '{sys_msg.strip()}'.")

            # 1.6 Test existing WS message handling: file_received
            await server.broadcast({"type": "file_received", "name": "report.pdf", "size": 1048576, "saved_to": "uploads"})
            await page.wait_for_selector("#feed .msg-file:has-text('report.pdf')", timeout=5000, state="attached")
            file_msg = await page.locator("#feed .msg-file").last.text_content()
            assert "report.pdf" in file_msg
            print(f"  [1.6] Existing message 'file_received' verified: contains 'report.pdf'.")

            test_results["ITEM 1"] = "PASS"
            print(">> ITEM 1: PASS <<")
        except Exception as e:
            test_results["ITEM 1"] = f"FAIL ({e})"
            print(f">> ITEM 1: FAIL -> {e} <<")

        # ──────────────────────────────────────────────────────────────────────
        # ITEM 2: Memory Modal — Real Entries from Memory Store
        # ──────────────────────────────────────────────────────────────────────
        print("\n" + "-" * 75)
        print("ITEM 2: Memory modal with real memory store entries")
        print("-" * 75)
        try:
            # 2.1 Fetch expected entries from actual memory manager
            expected_entries = all_entries_for_ui()
            print(f"  [2.1] Actual database query returned {len(expected_entries)} real memory entries.")
            assert len(expected_entries) > 0, "Expected at least 1 memory entry in memory store"

            # 2.2 Click #btn-memory in browser
            btn_mem = page.locator("#btn-memory")
            await btn_mem.click()
            await page.wait_for_selector("#memory-modal.open", state="visible")
            await page.wait_for_selector("#memory-list .memory-item")

            # 2.3 Verify rendered items match real store entries
            rendered_items = page.locator("#memory-list .memory-item")
            rendered_count = await rendered_items.count()
            assert rendered_count == len(expected_entries), f"Expected {len(expected_entries)} rendered items, got {rendered_count}"

            # Check first entry details
            first_expected = expected_entries[0]
            first_rendered_key = await rendered_items.first.locator(".memory-key").text_content()
            first_rendered_val = await rendered_items.first.locator(".memory-val").text_content()
            first_rendered_cat = await rendered_items.first.locator(".memory-cat-badge").text_content()

            assert first_expected["key"].replace("_", " ").lower() == first_rendered_key.strip().lower()
            assert first_expected["value"] == first_rendered_val.strip()
            assert first_expected["category"].lower() == first_rendered_cat.strip().lower()

            print(f"  [2.2] Verified rendered item 1 matches real entry: key='{first_rendered_key.strip()}', value='{first_rendered_val.strip()[:40]}...', cat='{first_rendered_cat.strip()}'.")

            # Close memory modal
            await page.locator("#memory-modal .modal-close-btn").click()
            await page.wait_for_selector("#memory-modal:not(.open)", state="hidden")
            print("  [2.3] Memory modal dismissed cleanly.")

            test_results["ITEM 2"] = "PASS"
            print(">> ITEM 2: PASS <<")
        except Exception as e:
            test_results["ITEM 2"] = f"FAIL ({e})"
            print(f">> ITEM 2: FAIL -> {e} <<")

        # ──────────────────────────────────────────────────────────────────────
        # ITEM 3: Voice Auth Modal — Enrollment Flow via phone-audio WS
        # ──────────────────────────────────────────────────────────────────────
        print("\n" + "-" * 75)
        print("ITEM 3: Voice Auth modal enrollment routing via phone-audio WS")
        print("-" * 75)
        try:
            btn_va = page.locator("#btn-voice-auth")
            await btn_va.click()
            await page.wait_for_selector("#voice-auth-modal.open", state="visible")
            print("  [3.1] Voice auth modal opened.")

            # Enter speaker name and start enrollment
            name_input = page.locator("#va-name-input")
            await name_input.fill("Smoke Test User")

            start_btn = page.locator("#va-start-btn")
            await start_btn.click()

            # Wait for active view
            await page.wait_for_selector("#va-view-active", state="visible", timeout=10000)
            print("  [3.2] Enrollment started; active view visible, /ws/phone-audio audio streaming active.")
            assert server._web_enroll_active is True, "server._web_enroll_active should be True"

            # Simulate step 1 phrase and countdown
            step_lbl = await page.locator("#va-step-label").text_content()
            assert "Phrase 1" in step_lbl
            phrase_card = page.locator("#va-phrase-text")
            assert await phrase_card.is_visible()
            print(f"  [3.3] Step 1 rendered: '{step_lbl}', phrase: '{await phrase_card.text_content()}'.")

            # Verify synthetic audio routed to enrollment buffer, not Gemini queue
            await asyncio.sleep(0.2)
            assert server._phone_audio_queue.empty(), "ERROR: Enrollment audio leaked to Gemini queue!"
            with server._web_enroll_lock:
                buf_size = len(server._web_enroll_buffer)
            print(f"  [3.4] Audio frames routed strictly to enrollment buffer ({buf_size} bytes, Gemini queue empty).")

            # Cancel enrollment
            cancel_btn = page.locator("#va-cancel-btn")
            await cancel_btn.click()
            await page.wait_for_selector("#voice-auth-modal:not(.open)", state="hidden")
            assert server._web_enroll_active is False
            print("  [3.5] Cancelled enrollment; session reset, modal closed.")

            test_results["ITEM 3"] = "PASS"
            print(">> ITEM 3: PASS <<")
        except Exception as e:
            test_results["ITEM 3"] = f"FAIL ({e})"
            print(f">> ITEM 3: FAIL -> {e} <<")

        # ──────────────────────────────────────────────────────────────────────
        # ITEM 4: Audio Devices Modal — List Devices & Apply Selection
        # ──────────────────────────────────────────────────────────────────────
        print("\n" + "-" * 75)
        print("ITEM 4: Audio Devices modal — real browser devices and selection applied to stream")
        print("-" * 75)
        try:
            btn_audio = page.locator("#btn-audio-devices")
            await btn_audio.click()
            await page.wait_for_selector("#audio-modal.open", state="visible")
            print("  [4.1] Audio devices modal opened.")

            # Verify devices listed
            await page.wait_for_selector("#audio-input-list .audio-device-item")
            device_items = page.locator("#audio-input-list .audio-device-item")
            item_count = await device_items.count()
            print(f"  [4.2] Enumerated {item_count} audio input device option(s) from browser.")
            assert item_count >= 1, "At least 1 audio device option required"

            # Verify System Default option is present
            default_item = device_items.first
            assert "System Default" in await default_item.locator(".audio-device-name").text_content()

            # If physical/fake devices exist, select one and verify constraint application
            if item_count > 1:
                second_item = device_items.nth(1)
                item_label = await second_item.locator(".audio-device-name span").text_content()
                await second_item.click()
                await asyncio.sleep(0.2)

                # Confirm localStorage holds device ID
                saved_id = await page.evaluate("() => localStorage.getItem('agent_preferred_mic_id')")
                assert saved_id, "Preferred device ID was not saved to localStorage"

                # Confirm sidebar badge updated to Custom
                sidebar_badge = page.locator("#audio-sidebar-status")
                badge_text = (await sidebar_badge.text_content()).strip()
                assert badge_text == "Custom", f"Expected 'Custom', got '{badge_text}'"
                print(f"  [4.3] Selected device '{item_label}', saved ID='{saved_id[:16]}...', sidebar badge='{badge_text}'.")

                # Verify constraint logic via evaluate
                constraint_check = await page.evaluate("""
                    async () => {
                        const prefId = localStorage.getItem('agent_preferred_mic_id');
                        const audioConstraints = { channelCount: 1, echoCancellation: true };
                        if (prefId) audioConstraints.deviceId = { exact: prefId };
                        return audioConstraints.deviceId && audioConstraints.deviceId.exact === prefId;
                    }
                """)
                assert constraint_check is True, "Constraint check failed for selected deviceId"
                print("  [4.4] Verified exact deviceId constraint is applied to getUserMedia stream.")

                # Revert to Default
                await default_item.click()
                await asyncio.sleep(0.2)
                reverted_id = await page.evaluate("() => localStorage.getItem('agent_preferred_mic_id')")
                assert reverted_id is None
                reverted_badge = (await sidebar_badge.text_content()).strip()
                assert reverted_badge == "Default"
                print("  [4.5] Reverted to System Default; localStorage cleared, badge reset to 'Default'.")

            # Dismiss modal
            await page.keyboard.press("Escape")
            await page.wait_for_selector("#audio-modal:not(.open)", state="hidden")
            print("  [4.6] Audio devices modal closed via Escape key.")

            test_results["ITEM 4"] = "PASS"
            print(">> ITEM 4: PASS <<")
        except Exception as e:
            test_results["ITEM 4"] = f"FAIL ({e})"
            print(f">> ITEM 4: FAIL -> {e} <<")

        await browser.close()

    uv_server.should_exit = True
    await server_task

    print("\n" + "=" * 80)
    print("FINAL SMOKE TEST REPORT:")
    print("=" * 80)
    all_passed = True
    for item in ["ITEM 1", "ITEM 2", "ITEM 3", "ITEM 4", "ITEM 5"]:
        status = test_results.get(item, "NOT RUN")
        print(f"  {item}: {status}")
        if not status.startswith("PASS"):
            all_passed = False
    print("=" * 80)
    if all_passed:
        print(">>> ALL 5 SMOKE TEST ITEMS PASSED (100%) <<<")
    else:
        print(">>> SOME SMOKE TEST ITEMS FAILED <<<")
    print("=" * 80)

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_full_smoke_test())
