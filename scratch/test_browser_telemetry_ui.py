import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

async def test_frontend_telemetry_handling():
    app_html_path = BASE_DIR / "dashboard" / "static" / "app.html"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        page = await browser.new_page()
        await page.add_init_script("""
            sessionStorage.setItem('jarvis_token', 'fake_token');
            sessionStorage.setItem('jarvis_key', '123456');
        """)
        
        # Load local app.html
        url = app_html_path.as_uri()
        await page.goto(url)
        
        # Verify initial values
        initial_cpu = await page.locator("#cpu-val").inner_text()
        initial_mem = await page.locator("#mem-val").inner_text()
        print(f"Initial: CPU={initial_cpu}, MEM={initial_mem}")
        
        # Dispatch a mock 'metrics' message by calling updateMetrics directly or simulating ws event
        await page.evaluate("""() => {
            if (typeof updateMetrics === 'function') {
                updateMetrics({
                    type: 'metrics',
                    cpu: 45.4,
                    mem: 62.8,
                    net: '342 KB/s'
                });
            }
        }""")
        
        # Verify updated values
        new_cpu = await page.locator("#cpu-val").inner_text()
        new_cpu_bar = await page.locator("#cpu-bar").get_attribute("style")
        new_mem = await page.locator("#mem-val").inner_text()
        new_mem_bar = await page.locator("#mem-bar").get_attribute("style")
        new_net = await page.locator("#net-val").inner_text()
        
        print(f"Updated: CPU={new_cpu} ({new_cpu_bar}), MEM={new_mem} ({new_mem_bar}), NET={new_net}")
        
        assert new_cpu == "45%", f"Expected 45%, got {new_cpu}"
        assert "45.4%" in (new_cpu_bar or ""), f"Expected width to contain 45.4%, got {new_cpu_bar}"
        assert new_mem == "63%", f"Expected 63%, got {new_mem}"
        assert "62.8%" in (new_mem_bar or ""), f"Expected width to contain 62.8%, got {new_mem_bar}"
        assert new_net == "342 KB/s", f"Expected '342 KB/s', got {new_net}"
        
        await browser.close()
        print("\n>>> FRONTEND TELEMETRY DOM UPDATE VERIFICATION PASSED! <<<")

if __name__ == "__main__":
    asyncio.run(test_frontend_telemetry_handling())
