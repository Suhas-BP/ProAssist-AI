"""
tests/verify_mobile_audio_ui.py
===============================
Headless browser verification of mobile layout, zero horizontal scroll,
console error hygiene, audio routing controls, and State-Table verification
for all combinations of (phone: idle/live/error) x (laptop: muted/unmuted).
"""

import asyncio
import os
import secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dashboard.server import DashboardServer
from playwright.async_api import async_playwright
import uvicorn


async def run_verification():
    server = DashboardServer()
    tok = secrets.token_urlsafe(32)
    server._tokens.add(tok)
    server._token_keys[tok] = "key123"

    config = uvicorn.Config(server.app, host="127.0.0.1", port=18899, log_level="warning")
    uv_server = uvicorn.Server(config)
    server_task = asyncio.create_task(uv_server.serve())

    await asyncio.sleep(1.0)
    errors_by_width = {}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="msedge", headless=True)

            widths = [360, 375, 390, 412, 768, 1024]

            for w in widths:
                console_errors = []
                context = await browser.new_context(
                    viewport={"width": w, "height": 844},
                    is_mobile=(w < 768),
                    has_touch=(w < 768),
                )
                page = await context.new_page()

                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                page.on("pageerror", lambda exc: console_errors.append(str(exc)))

                await page.add_init_script(f"""
                    sessionStorage.setItem('jarvis_token', '{tok}');
                    sessionStorage.setItem('jarvis_key', 'key123');
                """)

                await page.goto("http://127.0.0.1:18899/", wait_until="networkidle")

                scroll_width = await page.evaluate("() => document.documentElement.scrollWidth")
                client_width = await page.evaluate("() => document.documentElement.clientWidth")
                has_h_scroll = scroll_width > client_width

                print(f"[WIDTH {w}px] scrollWidth: {scroll_width}, clientWidth: {client_width}, has_h_scroll: {has_h_scroll}")
                if has_h_scroll:
                    errors_by_width[w] = f"Horizontal overflow: scrollWidth {scroll_width} > clientWidth {client_width}"

                critical_errors = [e for e in console_errors if "favicon" not in e and "404" not in e]
                if critical_errors:
                    print(f"[WIDTH {w}px] Console errors:", critical_errors)
                    errors_by_width[w] = f"Console errors: {critical_errors}"

                # ── State Table Verification on 390px (Task 1 Item 3) ─────────
                if w == 390:
                    print("\n>> Running State-Table Test for (phone: idle/live/error) x (laptop: muted/unmuted)...")
                    phone_states = ["idle", "streaming", "error"]
                    laptop_states = [True, False]  # muted, unmuted

                    for p_state in phone_states:
                        for l_muted in laptop_states:
                            res = await page.evaluate(f"""(() => {{
                                _setMicState('{p_state}');
                                _onMicStateBroadcast({{ phone: {'true' if p_state == 'streaming' else 'false'}, desktop_muted: {'true' if l_muted else 'false'} }});
                                const btn = document.getElementById('mic-btn');
                                const span = btn ? btn.querySelector('span') : null;
                                const badge = document.getElementById('laptop-mic-badge');
                                return {{
                                    btnClass: btn ? btn.className : '',
                                    btnText: span ? span.textContent.trim() : (btn ? btn.innerText.trim() : ''),
                                    badgeDisplay: badge ? window.getComputedStyle(badge).display : ''
                                }};
                            }})()""")

                            # 1. Assert phone mic button reflects ONLY phone state
                            if p_state == "idle":
                                assert "state-idle" in res["btnClass"], f"Expected state-idle, got {res['btnClass']}"
                                assert "Mic" in res["btnText"], f"Expected Mic, got {res['btnText']}"
                            elif p_state == "streaming":
                                assert "state-streaming" in res["btnClass"], f"Expected state-streaming, got {res['btnClass']}"
                                assert "Live" in res["btnText"], f"Expected Live, got {res['btnText']}"
                            elif p_state == "error":
                                assert "state-error" in res["btnClass"], f"Expected state-error, got {res['btnClass']}"
                                assert "Error" in res["btnText"], f"Expected Error, got {res['btnText']}"

                            # 2. Assert laptop mute state is reflected in #laptop-mic-badge separately
                            if l_muted:
                                assert res["badgeDisplay"] != "none", f"Expected laptop badge visible when muted, got {res['badgeDisplay']}"
                            else:
                                assert res["badgeDisplay"] == "none", f"Expected laptop badge hidden when unmuted, got {res['badgeDisplay']}"

                            print(f"   [PASS] Phone: {p_state:<9} | Laptop Muted: {str(l_muted):<5} -> Button: {res['btnText']} | Badge: {res['badgeDisplay']}")

                await context.close()

            # ── 2. Run Mocked WebSocket Client JS Tests (Task 1 Patch 4) ────────
            await run_mocked_ws_client_js_tests(browser, "http://127.0.0.1:18899/", tok)

            await browser.close()
    finally:
        uv_server.should_exit = True
        await asyncio.sleep(0.5)
        server_task.cancel()

    assert not errors_by_width, f"Verification failed with errors: {errors_by_width}"
    print("\nALL MOBILE AUDIO UI CHECKS, STATE-TABLE TESTS & MOCKED WS CLIENT JS TESTS PASSED!")


async def run_mocked_ws_client_js_tests(browser, base_url: str, tok: str):
    """Playwright tests with a mocked WebSocket exercising real client JS (Task 1 Patch 4 Item 2):
    - close 4000 -> no reconnect and the 'Take back' banner shows
    - close 1008 -> exactly one retry after ~4 s, then a halt message
    - close 4008 -> normal backoff retries
    - unexpected close -> 'Reconnecting', never 'Error', for the first retries
    """
    print("\n" + "=" * 70)
    print(">> RUNNING PLAYWRIGHT MOCKED WEBSOCKET CLIENT JS TEST SUITE (PATCH 4)")
    print("=" * 70)

    init_script = f"""
        sessionStorage.setItem('jarvis_token', '{tok}');
        sessionStorage.setItem('jarvis_key', 'key123');

        // Mock getUserMedia so mic stream acquisition succeeds headlessly
        if (!navigator.mediaDevices) navigator.mediaDevices = {{}};
        navigator.mediaDevices.getUserMedia = async (constraints) => {{
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = audioCtx.createOscillator();
            const dst = audioCtx.createMediaStreamDestination();
            osc.connect(dst);
            osc.start();
            return dst.stream;
        }};

        // Global tracking of WebSocket instances
        window.__mockSockets = [];
        window.__voiceWsInstances = [];
        window.__playbackWsInstances = [];

        class MockWebSocket {{
            constructor(url) {{
                this.url = url;
                this.readyState = 0; // CONNECTING
                this.binaryType = 'arraybuffer';
                this.onopen = null;
                this.onclose = null;
                this.onerror = null;
                this.onmessage = null;
                window.__mockSockets.push(this);

                if (url.includes('/ws/phone-audio')) {{
                    window.__voiceWsInstances.push(this);
                }} else if (url.includes('/ws/phone-playback')) {{
                    window.__playbackWsInstances.push(this);
                }}

                // Transition to OPEN after 20ms
                setTimeout(() => {{
                    if (this.readyState === 0) {{
                        this.readyState = 1; // OPEN
                        if (this.onopen) this.onopen({{ type: 'open' }});
                    }}
                }}, 20);
            }}

            send(data) {{}}

            close(code = 1000, reason = '') {{
                this.readyState = 3;
                if (this.onclose) this.onclose({{ code, reason }});
            }}

            serverClose(code, reason) {{
                this.readyState = 3;
                if (this.onclose) this.onclose({{ code, reason }});
            }}
        }}

        window.WebSocket = MockWebSocket;
    """

    async def create_test_page():
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
        )
        page = await context.new_page()
        await page.add_init_script(init_script)
        await page.goto(base_url, wait_until="networkidle")
        return context, page

    # ── Test 1: Close 4000 -> no reconnect and "Take back" banner shows ──────
    print("   [1/4] Testing Close 4000: no reconnect and 'Take back' banner...")
    ctx1, page1 = await create_test_page()
    try:
        await page1.evaluate("() => doMic()")
        await page1.wait_for_selector("#mic-btn.state-streaming", timeout=3000)
        ws_count = await page1.evaluate("() => window.__voiceWsInstances.length")
        assert ws_count == 1, f"Expected 1 voice WS initially, got {ws_count}"

        # Trigger server close with code 4000 ("replaced")
        await page1.evaluate("() => window.__voiceWsInstances[0].serverClose(4000, 'replaced')")
        await page1.wait_for_timeout(500)

        # Verify no reconnect
        ws_count_after = await page1.evaluate("() => window.__voiceWsInstances.length")
        assert ws_count_after == 1, f"Expected 1 voice WS (no reconnect), got {ws_count_after}"

        # Verify banner in DOM
        banner_info = await page1.evaluate("""() => {
            const b = document.getElementById('take-back-banner');
            const btn = document.getElementById('mic-btn');
            return {
                exists: b !== null,
                text: b ? b.innerText : '',
                btnClass: btn ? btn.className : ''
            };
        }""")
        assert banner_info["exists"], "Expected #take-back-banner to exist in DOM"
        assert "Another session took over this stream" in banner_info["text"], f"Expected takeover text, got {banner_info['text']}"
        assert "Take back" in banner_info["text"], f"Expected Take back button in banner, got {banner_info['text']}"
        assert "state-error" in banner_info["btnClass"], f"Expected mic button to be in state-error, got {banner_info['btnClass']}"
        print("      [PASS] Close 4000: no reconnect, banner displayed with 'Take back' button.")
    finally:
        await ctx1.close()

    # ── Test 2: Close 1008 -> exactly one retry after ~4s, then halt message ──
    print("   [2/4] Testing Close 1008: exactly one retry after ~4s, then halt...")
    ctx2, page2 = await create_test_page()
    try:
        await page2.evaluate("() => doMic()")
        await page2.wait_for_selector("#mic-btn.state-streaming", timeout=3000)
        assert (await page2.evaluate("() => window.__voiceWsInstances.length")) == 1

        # Trigger server close with code 1008 ("different device active")
        await page2.evaluate("() => window.__voiceWsInstances[0].serverClose(1008, 'different device active')")
        await page2.wait_for_timeout(200)

        # Immediately: state is reconnecting, NOT error
        btn_class = await page2.evaluate("() => document.getElementById('mic-btn').className")
        assert "state-reconnecting" in btn_class, f"Expected state-reconnecting, got {btn_class}"

        # Wait 2.0s: still exactly 1 instance, no premature retry
        await page2.wait_for_timeout(2000)
        assert (await page2.evaluate("() => window.__voiceWsInstances.length")) == 1, "Should not retry before 4s"

        # Wait for 4s timer to fire (~2.5s more -> total 4.5s)
        await page2.wait_for_timeout(2500)
        ws_count_retry = await page2.evaluate("() => window.__voiceWsInstances.length")
        assert ws_count_retry == 2, f"Expected exactly 2 voice WS instances after ~4s, got {ws_count_retry}"

        # Server closes the second retry with 1008 as well
        await page2.evaluate("() => window.__voiceWsInstances[1].serverClose(1008, 'different device active')")
        await page2.wait_for_timeout(500)

        # Verify halt: no further retry attempt
        ws_count_halt = await page2.evaluate("() => window.__voiceWsInstances.length")
        assert ws_count_halt == 2, f"Expected exactly 2 voice WS instances (halted), got {ws_count_halt}"

        # Verify halt message and state-error
        halt_info = await page2.evaluate("""() => {
            const btn = document.getElementById('mic-btn');
            const feed = document.getElementById('feed');
            return {
                btnClass: btn ? btn.className : '',
                feedText: feed ? feed.innerText : ''
            };
        }""")
        assert "state-error" in halt_info["btnClass"], f"Expected state-error on halt, got {halt_info['btnClass']}"
        assert "Another device is currently using the stream" in halt_info["feedText"], f"Expected halt message in feed, got {halt_info['feedText']}"
        print("      [PASS] Close 1008: waited 4s, retried exactly once, then halted with error message.")
    finally:
        await ctx2.close()

    # ── Test 3: Close 4008 -> normal backoff retries ─────────────────────────
    print("   [3/4] Testing Close 4008: normal backoff retries...")
    ctx3, page3 = await create_test_page()
    try:
        await page3.evaluate("() => doMic()")
        await page3.wait_for_selector("#mic-btn.state-streaming", timeout=3000)
        assert (await page3.evaluate("() => window.__voiceWsInstances.length")) == 1

        # Trigger server close with code 4008 ("rate limited")
        await page3.evaluate("() => window.__voiceWsInstances[0].serverClose(4008, 'rate limited')")
        await page3.wait_for_timeout(200)

        # Verify state is reconnecting, feed does NOT contain "Another device is currently using the stream"
        mid_info = await page3.evaluate("""() => {
            const btn = document.getElementById('mic-btn');
            const feed = document.getElementById('feed');
            return {
                btnClass: btn ? btn.className : '',
                feedText: feed ? feed.innerText : ''
            };
        }""")
        assert "state-reconnecting" in mid_info["btnClass"], f"Expected state-reconnecting, got {mid_info['btnClass']}"
        assert "Another device is currently using the stream" not in mid_info["feedText"], "Must not show another device active on 4008"

        # Normal backoff for retry 1 is 1000ms. Wait 1.3s for retry to fire
        await page3.wait_for_timeout(1300)
        ws_count_retry = await page3.evaluate("() => window.__voiceWsInstances.length")
        assert ws_count_retry == 2, f"Expected normal backoff retry after ~1s (got count={ws_count_retry})"
        print("      [PASS] Close 4008: did not halt, proceeded with normal backoff retry.")
    finally:
        await ctx3.close()

    # ── Test 4: Unexpected close -> 'Reconnecting', never 'Error', for first retries ──
    print("   [4/4] Testing Unexpected Close: 'Reconnecting', never 'Error', for first retries...")
    ctx4, page4 = await create_test_page()
    try:
        await page4.evaluate("() => doMic()")
        await page4.wait_for_selector("#mic-btn.state-streaming", timeout=3000)

        # Trigger unexpected close (code 1006 abnormal closure)
        await page4.evaluate("() => window.__voiceWsInstances[0].serverClose(1006, 'Abnormal Closure')")
        await page4.wait_for_timeout(200)

        res = await page4.evaluate("""() => {
            const btn = document.getElementById('mic-btn');
            const span = btn ? btn.querySelector('span') : null;
            return {
                btnClass: btn ? btn.className : '',
                btnText: span ? span.textContent.trim() : (btn ? btn.innerText.trim() : '')
            };
        }""")
        assert "state-reconnecting" in res["btnClass"], f"Expected state-reconnecting, got {res['btnClass']}"
        assert "Reconnecting" in res["btnText"], f"Expected Reconnecting text, got {res['btnText']}"
        assert "state-error" not in res["btnClass"], f"Must not be state-error during first retries, got {res['btnClass']}"
        assert "Error" not in res["btnText"], f"Must not show Error text during first retries, got {res['btnText']}"
        print("      [PASS] Unexpected close: displays 'Reconnecting', never 'Error', for first retries.")
    finally:
        await ctx4.close()

    print("=" * 70)
    print("ALL 4 MOCKED WEBSOCKET CLIENT JS TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_verification())
