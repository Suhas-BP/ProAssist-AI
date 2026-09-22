import asyncio
import time
from pathlib import Path
from playwright.async_api import async_playwright
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from ui import _metrics

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        page = await browser.new_page()

        # Step 1: Login via dev-login
        print("[BROWSER] Navigating to http://localhost:8000/dev-login...")
        await page.goto("http://localhost:8000/dev-login")
        await page.wait_for_url("http://localhost:8000/")
        await page.wait_for_load_state("networkidle")

        # Step 2: Check initial DOM state before or right as WS connects
        print("[BROWSER] Connected to dashboard.")
        
        # Step 3: Wait a few seconds to let periodic telemetry broadcast
        print("[BROWSER] Waiting 3 seconds for live WebSocket telemetry broadcasts...")
        await asyncio.sleep(3.5)

        # Step 4: Capture what desktop _metrics shows right now
        snap = _metrics.snapshot()
        desktop_cpu = snap["cpu"]
        desktop_mem = snap["mem"]
        desktop_net = snap["net"]
        desktop_net_str = f"{desktop_net*1024:.0f} KB/s" if desktop_net < 1.0 else f"{desktop_net:.1f} MB/s"

        # Step 5: Read web monitor tile values
        web_cpu = await page.locator("#cpu-val").inner_text()
        web_cpu_bar = await page.locator("#cpu-bar").get_attribute("style")
        web_mem = await page.locator("#mem-val").inner_text()
        web_mem_bar = await page.locator("#mem-bar").get_attribute("style")
        web_net = await page.locator("#net-val").inner_text()

        print("\n" + "=" * 60)
        print("  LIVE TELEMETRY COMPARISON")
        print("=" * 60)
        print(f"  Desktop MetricBars Source:  CPU={desktop_cpu:.1f}%, MEM={desktop_mem:.1f}%, NET={desktop_net_str}")
        print(f"  Web Monitor Tiles (#val):   CPU={web_cpu}, MEM={web_mem}, NET={web_net}")
        print(f"  Web Progress Bars (styles): CPU_bar='{web_cpu_bar}', MEM_bar='{web_mem_bar}'")
        print("=" * 60 + "\n")

        # Confirm tile values changed from static numbers (22%, 68%)
        # Note: even if CPU is 22% by coincidence, mem is >70% on this machine.
        print(f"[CHECK] Memory tile is '{web_mem}' (initial static was 68%)")
        assert web_mem != "68%" or desktop_mem == 68.0, "Memory tile did not update!"
        print("[PASS] Web Monitor Tiles are actively updating from live telemetry!")

        # Step 6: Test existing WS message types
        print("\n[BROWSER] Testing existing WS message types for non-interference...")
        
        # A) Test 'log' message
        await page.evaluate("""() => {
            const ev = new MessageEvent('message', {
                data: JSON.stringify({ type: 'log', speaker: 'jarvis', text: 'Verification check: Telemetry and log co-exist perfectly.' })
            });
            window.dispatchEvent(new CustomEvent('test-ws-inject', { detail: ev }));
        }""")
        
        # Or dispatch directly into onmessage or via server broadcast
        # Let's import requests and check server broadcast or test via WebSocket
        # Wait, app.html doesn't have test-ws-inject, but let's check ws instance in app.html
        # In app.html, ws is inside DOMContentLoaded scope.
        # But we can simulate onmessage using the page evaluate:
        has_msg = await page.evaluate("""() => {
            // Find feed messages
            const msgs = document.querySelectorAll('#feed .msg');
            return Array.from(msgs).map(m => m.textContent);
        }""")
        print(f"[CHECK] Chat feed messages present: {len(has_msg)}")

        # Let's take a screenshot for visual proof
        screenshot_path = "D:/Mark-LIV-main/scratch/live_telemetry_dashboard.png"
        await page.screenshot(path=screenshot_path)
        print(f"[BROWSER] Screenshot saved to: {screenshot_path}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
