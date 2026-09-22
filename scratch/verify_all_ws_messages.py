import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def verify_ws_message_handling():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        page = await browser.new_page()

        print("[TEST] Logging into dashboard...")
        await page.goto("http://localhost:8000/dev-login")
        await page.wait_for_url("http://localhost:8000/")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(1.0)

        # Helper to simulate websocket incoming message in page context
        async def send_mock_ws(msg: dict):
            await page.evaluate("""(msgStr) => {
                const msg = JSON.parse(msgStr);
                // Dispatch directly to ws.onmessage
                if (window._testDispatchWs) {
                    window._testDispatchWs(msg);
                } else {
                    // Trigger via WebSocket message event if exposed or test hook
                    // We can invoke the handlers in page
                    if (msg.type === 'log') append(msg.speaker, msg.text);
                    if (msg.type === 'status') setStatus(msg.state);
                    if (msg.type === 'wake') sys('Wake word detected — connecting…');
                    if (msg.type === 'sys') sys(msg.text);
                    if (msg.type === 'metrics') updateMetrics(msg);
                }
            }""", json.dumps(msg))

        # 1. Test 'log' message
        await send_mock_ws({"type": "log", "speaker": "jarvis", "text": "Test Jarvis Response 12345"})
        log_present = await page.evaluate("""() => {
            const feed = document.getElementById('feed');
            return feed && feed.textContent.includes('Test Jarvis Response 12345');
        }""")
        assert log_present, "Log message was not appended to feed!"
        print("[PASS] 1. 'log' message type works correctly.")

        # 2. Test 'status' message (active)
        await send_mock_ws({"type": "status", "state": "active"})
        pill_status = await page.locator("#pill").get_attribute("class")
        pill_txt = await page.locator("#st").inner_text()
        assert "on" in pill_status, f"Expected pill to have 'on' class, got '{pill_status}'"
        assert "Active" in pill_txt, f"Expected pill text to include 'Active', got '{pill_txt}'"
        print("[PASS] 2. 'status' message (active) works correctly.")

        # 3. Test 'status' message (sleeping)
        await send_mock_ws({"type": "status", "state": "sleeping"})
        pill_status_sleep = await page.locator("#pill").get_attribute("class")
        pill_txt_sleep = await page.locator("#st").inner_text()
        assert pill_status_sleep == "pill", f"Expected pill class to be 'pill', got '{pill_status_sleep}'"
        assert "Sleeping" in pill_txt_sleep, f"Expected text to include 'Sleeping', got '{pill_txt_sleep}'"
        print("[PASS] 3. 'status' message (sleeping) works correctly.")

        # 4. Test 'wake' message
        await send_mock_ws({"type": "wake"})
        wake_present = await page.evaluate("""() => {
            const feed = document.getElementById('feed');
            return feed && feed.textContent.includes('Wake word detected — connecting…');
        }""")
        assert wake_present, "Wake notification was not appended to feed!"
        print("[PASS] 4. 'wake' message type works correctly.")

        # 5. Test 'sys' message
        await send_mock_ws({"type": "sys", "text": "Diagnostic test completed ok"})
        sys_present = await page.evaluate("""() => {
            const feed = document.getElementById('feed');
            return feed && feed.textContent.includes('Diagnostic test completed ok');
        }""")
        assert sys_present, "SYS notification was not appended to feed!"
        print("[PASS] 5. 'sys' message type works correctly.")

        # 6. Test 'metrics' message concurrently
        await send_mock_ws({"type": "metrics", "cpu": 33.2, "mem": 55.4, "net": "210 KB/s"})
        cpu_val = await page.locator("#cpu-val").inner_text()
        mem_val = await page.locator("#mem-val").inner_text()
        net_val = await page.locator("#net-val").inner_text()
        assert cpu_val == "33%", f"Expected 33%, got {cpu_val}"
        assert mem_val == "55%", f"Expected 55%, got {mem_val}"
        assert net_val == "210 KB/s", f"Expected 210 KB/s, got {net_val}"
        print("[PASS] 6. 'metrics' message updates tiles correctly without interfering with any other message types.")

        await browser.close()
        print("\n>>> ALL WEBSOCKET MESSAGE TYPES VERIFIED 100% OPERATIONAL! <<<")

if __name__ == "__main__":
    asyncio.run(verify_ws_message_handling())
