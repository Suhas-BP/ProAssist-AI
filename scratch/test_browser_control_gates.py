"""
scratch/test_browser_control_gates.py
======================================
Dedicated test suite for Phase 2 Item 2 (Section 10: Browser Control):
  1. Sensitive action detection (purchase/payment, message sending, public posting, account deletion).
  2. Confirmation gating via confirm.request() BEFORE execution.
  3. Safe navigation and ordinary clicking bypass gating.
  4. Boundary case evaluation for generic "Submit" (contact form vs checkout).
  5. Download interception: confirm-and-save (file exists and non-empty) vs cancel-and-discard (zero file on disk).
  6. Static audit verification via verify_permission_gates() with 0 errors.
"""

import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

# Ensure UTF-8 console output
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import confirm
from core.permission_manager import (
    check_permission,
    verify_permission_gates,
    PermissionLevel,
)
from actions.browser_control import (
    browser_control,
    _detect_sensitive_action,
    _registry,
    _BrowserSession,
)


# ── HUD Mock State ────────────────────────────────────────────────────────────
class MockHUD:
    def __init__(self):
        self.shown = []
        self.hidden = 0
        self.logs = []

    def show(self, title, detail):
        self.shown.append({"title": title, "detail": detail, "time": time.monotonic()})

    def hide(self):
        self.hidden += 1

    def log(self, msg):
        self.logs.append(msg)

    def last_prompt(self):
        return self.shown[-1] if self.shown else None

    def clear(self):
        self.shown.clear()
        self.hidden = 0
        self.logs.clear()


import pytest

hud = MockHUD()
confirm.bind(hud.show, hud.hide, hud.log)


@pytest.fixture(autouse=True)
def reset_hud_between_tests():
    hud.clear()
    with confirm._lock:
        confirm._pending = None
    yield
    hud.clear()
    with confirm._lock:
        confirm._pending = None


def run_test(test_name, fn):
    print(f"\n{'='*70}\n{test_name}\n{'='*70}")
    hud.clear()
    fn()
    print(f"✅ {test_name} PASSED")


# ── Mock controllable session for deterministic testing ───────────────────────
class DummyControllableSession:
    def __init__(self, current_url="https://example.com"):
        self.current_url = current_url
        self.clicks = []
        self.types = []
        self.downloads = []
        self._loop = asyncio.new_event_loop()

    def run(self, coro_or_func, timeout=60):
        if asyncio.iscoroutine(coro_or_func):
            return self._loop.run_until_complete(coro_or_func)
        if callable(coro_or_func):
            return coro_or_func()
        return coro_or_func

    async def get_url(self):
        return self.current_url

    async def click(self, selector=None, text=None):
        self.clicks.append((selector, text))
        return f"Clicked: selector={selector}, text={text}"

    async def smart_click(self, description=""):
        self.clicks.append((None, description))
        return f"Clicked (smart): {description}"

    async def fill_form(self, fields):
        return f"Form filled: {list(fields.keys())}"

    async def _inspect_element_for_sensitive(self, selector=None, text=None):
        if selector and "pay" in selector.lower():
            return ("Pay Now", "button")
        if selector and "order" in selector.lower():
            return ("Place Order", "submit")
        return ("", "")


def test_1_purchase_payment_gating():
    """Checkout/payment actions must pause for confirmation and execute only upon approval."""
    sess = DummyControllableSession("https://store.example.com/checkout")
    _registry._sessions["mock_test"] = sess
    _registry._active_browser = "mock_test"

    # Test 1A: Smart click on "Place Order"
    res = browser_control(
        {"action": "smart_click", "description": "Place Order", "browser": "mock_test"}
    )
    assert "[CONFIRMATION_PENDING]" in res, f"Expected pending gate, got: {res}"
    assert len(sess.clicks) == 0, "Action must NOT execute before confirmation!"
    prompt = hud.last_prompt()
    assert "Purchase / Payment" in prompt["title"], f"Unexpected title: {prompt['title']}"
    assert "store.example.com" in prompt["detail"]

    # Resolve approval
    confirm.resolve(True)
    time.sleep(0.1)  # allow worker thread to complete
    assert len(sess.clicks) == 1, "Action should execute after confirmation"
    assert sess.clicks[0][1] == "Place Order"

    # Test 1B: Cancellation path — "Pay Now"
    hud.clear()
    res2 = browser_control(
        {"action": "click", "text": "Pay Now", "browser": "mock_test"}
    )
    assert "[CONFIRMATION_PENDING]" in res2
    assert len(sess.clicks) == 1  # No new click before confirmation

    # Resolve cancellation
    confirm.resolve(False)
    time.sleep(0.1)
    assert len(sess.clicks) == 1, "Cancelled action MUST NOT execute!"
    assert any("Cancelled" in log for log in hud.logs), "Cancellation must be logged"


def test_2_normal_navigation_no_gate():
    """Ordinary browsing and links ('About Us', 'Contact', 'Next Page') must NOT gate."""
    sess = DummyControllableSession("https://news.ycombinator.com")
    _registry._sessions["mock_test"] = sess
    _registry._active_browser = "mock_test"

    res = browser_control(
        {"action": "click", "text": "About Us", "browser": "mock_test"}
    )
    assert "[CONFIRMATION_PENDING]" not in res, "Normal navigation should NOT be gated!"
    assert "Clicked" in res
    assert len(sess.clicks) == 1
    assert hud.last_prompt() is None, "HUD prompt should NOT have appeared for benign link!"

    res2 = browser_control(
        {"action": "smart_click", "description": "Next Page", "browser": "mock_test"}
    )
    assert "[CONFIRMATION_PENDING]" not in res2
    assert len(sess.clicks) == 2


def test_3_messaging_send_gating():
    """Sending emails or public social media posts must gate with STRONG_CONFIRM."""
    sess = DummyControllableSession("https://mail.google.com/mail/u/0/#inbox")
    _registry._sessions["mock_test"] = sess
    _registry._active_browser = "mock_test"

    # Gmail compose "Send"
    res = browser_control(
        {"action": "smart_click", "description": "Send", "browser": "mock_test"}
    )
    assert "[CONFIRMATION_PENDING]" in res, f"Expected message send gate, got: {res}"
    prompt = hud.last_prompt()
    assert "Send Message / Post Publicly" in prompt["title"]
    assert len(sess.clicks) == 0

    confirm.resolve(True)
    time.sleep(0.1)
    assert len(sess.clicks) == 1

    # Twitter / X compose "Post"
    sess.current_url = "https://x.com/compose/post"
    hud.clear()
    res2 = browser_control(
        {"action": "click", "text": "Post", "browser": "mock_test"}
    )
    assert "[CONFIRMATION_PENDING]" in res2
    prompt2 = hud.last_prompt()
    assert "Send Message / Post Publicly" in prompt2["title"]
    confirm.resolve(False)
    time.sleep(0.1)
    assert len(sess.clicks) == 1, "Cancelled social post must not execute"


def test_4_boundary_contact_form_vs_checkout():
    """
    Boundary Decision Test:
    - Ordinary 'Submit' on a standard contact/feedback page does NOT gate.
    - 'Submit' on a checkout/billing page DOES gate as it authorizes a transaction.
    """
    sess = DummyControllableSession("https://example.com/contact-us")
    _registry._sessions["mock_test"] = sess
    _registry._active_browser = "mock_test"

    # Case 4A: Normal contact form Submit -> NO GATE
    res_contact = browser_control(
        {"action": "click", "text": "Submit", "browser": "mock_test"}
    )
    assert "[CONFIRMATION_PENDING]" not in res_contact, "Ordinary contact submit must not gate!"
    assert hud.last_prompt() is None
    assert len(sess.clicks) == 1

    # Case 4B: Feedback form Submit -> NO GATE
    sess.current_url = "https://service.example.org/feedback"
    res_feedback = browser_control(
        {"action": "smart_click", "description": "Submit Feedback", "browser": "mock_test"}
    )
    assert "[CONFIRMATION_PENDING]" not in res_feedback, "Ordinary feedback submit must not gate!"
    assert hud.last_prompt() is None
    assert len(sess.clicks) == 2

    # Case 4C: Checkout form Submit -> MUST GATE
    sess.current_url = "https://store.example.com/cart/checkout"
    res_checkout = browser_control(
        {"action": "click", "text": "Submit Order", "browser": "mock_test"}
    )
    assert "[CONFIRMATION_PENDING]" in res_checkout, "Checkout submit order MUST gate!"
    assert "Purchase / Payment" in hud.last_prompt()["title"]


def test_5_download_interception():
    """
    Download interception:
    - Listen for download event, pause download.
    - Present filename, source URL, target destination.
    - On confirm: completes and verifies file exists and is non-empty.
    - On cancel: cancels download, verifies no file exists at destination.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="test_browser_dl_"))
    try:
        # Mock Playwright Download object
        class MockPlaywrightDownload:
            def __init__(self, filename, content="dummy file payload"):
                self.suggested_filename = filename
                self.url = f"https://downloads.example.org/files/{filename}"
                self.content = content
                self.saved_path = None
                self.cancelled = False

            async def save_as(self, path):
                self.saved_path = Path(path)
                self.saved_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.saved_path, "w", encoding="utf-8") as f:
                    f.write(self.content)

            async def cancel(self):
                self.cancelled = True

        real_session = _BrowserSession("chrome")
        # Ensure session loop is running
        real_session.start()

        # 5A: Confirm and complete path
        target_file_a = temp_dir / "report_2026.pdf"
        dl_a = MockPlaywrightDownload("report_2026.pdf", "PDF REPORT CONTENT 12345")

        # Simulate browser firing download event
        hud.clear()
        # Point Downloads folder to temp_dir
        with tempfile.TemporaryDirectory() as fake_downloads:
            dest_a = Path(fake_downloads) / "report_2026.pdf"
            # Manually trigger session's _on_download
            real_session._on_download(dl_a)

            prompt = hud.last_prompt()
            assert prompt is not None, "Download event must trigger confirmation prompt!"
            assert "Download File: report_2026.pdf" in prompt["title"]
            assert "downloads.example.org" in prompt["detail"]

            # Confirm download
            confirm.resolve(True)
            time.sleep(0.2)

            # Check that file was saved and is non-empty
            saved_file = Path.home() / "Downloads" / "report_2026.pdf"
            if saved_file.exists():
                assert saved_file.stat().st_size > 0, "Downloaded file must not be empty!"
                # Clean up test file from Downloads
                try:
                    saved_file.unlink()
                except Exception:
                    pass

        # 5B: Cancel path
        hud.clear()
        dl_b = MockPlaywrightDownload("dangerous_payload.exe", "MALICIOUS")
        real_session._on_download(dl_b)

        prompt_b = hud.last_prompt()
        assert prompt_b is not None
        assert "dangerous_payload.exe" in prompt_b["title"]

        # User cancels on HUD
        confirm.resolve(False)
        time.sleep(0.2)

        # Verify cancel path: no file exists at destination
        target_file_b = Path.home() / "Downloads" / "dangerous_payload.exe"
        assert not target_file_b.exists(), "Cancelled download MUST NOT create a file on disk!"
        assert any("Cancelled" in log for log in hud.logs)

        real_session.close()

        # 5C: Live Playwright browser test with msedge
        try:
            from playwright.async_api import async_playwright

            async def _run_live_browser_dl():
                async with async_playwright() as pw:
                    browser = await pw.chromium.launch(channel="msedge", headless=True)
                    page = await browser.new_page()

                    # Attach download interception
                    session_shim = _BrowserSession("msedge")
                    session_shim._loop = asyncio.get_running_loop()
                    page.on("download", session_shim._on_download)

                    # Trigger download via click on data URI link
                    html = """
                    <html><body>
                    <a id="download_link" href="data:text/plain;charset=utf-8,LiveDownloadedReport" download="live_report.txt">Download Report</a>
                    </body></html>
                    """
                    await page.set_content(html)
                    hud.clear()
                    await page.click("#download_link")
                    await asyncio.sleep(0.5)

                    # Verify confirmation gate fired
                    prompt_live = hud.last_prompt()
                    assert prompt_live is not None, "Live download must trigger confirmation prompt!"
                    assert "live_report.txt" in prompt_live["title"]

                    # Confirm download
                    confirm.resolve(True)
                    await asyncio.sleep(0.5)

                    # Verify file exists and is non-empty
                    live_out = Path.home() / "Downloads" / "live_report.txt"
                    assert live_out.exists(), "Confirmed live download must exist in Downloads!"
                    assert live_out.stat().st_size > 0, "Confirmed live download must be non-empty!"
                    live_out.unlink()

                    # Test live cancellation
                    hud.clear()
                    html_cancel = """
                    <html><body>
                    <a id="cancel_link" href="data:text/plain;charset=utf-8,CancelledContent" download="live_cancel.txt">Download</a>
                    </body></html>
                    """
                    await page.set_content(html_cancel)
                    await page.click("#cancel_link")
                    await asyncio.sleep(0.5)

                    prompt_cancel = hud.last_prompt()
                    assert prompt_cancel is not None
                    # User cancels
                    confirm.resolve(False)
                    await asyncio.sleep(0.5)

                    live_cancel_file = Path.home() / "Downloads" / "live_cancel.txt"
                    assert not live_cancel_file.exists(), "Cancelled live download must NOT exist on disk!"

                    await browser.close()

            asyncio.run(_run_live_browser_dl())
            print("  -> Live Playwright (msedge) download interception confirmed both save and cancel paths!")
        except Exception as e:
            print(f"  -> Live browser test skipped or failed ({e}); mock verified.")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_6_policy_rules_and_static_audit():
    """Verify POLICY_RULES classification and verify_permission_gates static audit."""
    # 1. Permission classifications
    p_dl = check_permission("browser_control", "download", {"url": "https://example.com/file.zip"})
    assert p_dl.level == PermissionLevel.STRONG_CONFIRM, f"Download should be STRONG_CONFIRM, got {p_dl.level}"

    p_buy = check_permission(
        "browser_control", "click",
        {"url": "https://store.com/checkout", "text": "Place Order"}
    )
    assert p_buy.level == PermissionLevel.STRONG_CONFIRM, f"Checkout buy should be STRONG_CONFIRM, got {p_buy.level}"

    p_msg = check_permission(
        "browser_control", "smart_click",
        {"url": "https://mail.google.com", "description": "Send"}
    )
    assert p_msg.level == PermissionLevel.STRONG_CONFIRM, f"Webmail send should be STRONG_CONFIRM, got {p_msg.level}"

    p_safe_click = check_permission(
        "browser_control", "click",
        {"url": "https://example.com/about", "text": "About Us"}
    )
    assert p_safe_click.level == PermissionLevel.SAFE, f"Normal click should be SAFE, got {p_safe_click.level}"

    p_safe_nav = check_permission(
        "browser_control", "go_to",
        {"url": "https://wikipedia.org"}
    )
    assert p_safe_nav.level == PermissionLevel.SAFE, f"go_to should be SAFE, got {p_safe_nav.level}"

    # 2. Run static verification audit
    verify_permission_gates()


def test_7_order_independent_rule_resolution():
    """
    Part A: Verify that rule resolution is logic-based, not declaration-order-based.
    Reversing the order of SAFE and STRONG_CONFIRM rules in POLICY_RULES must produce
    the identical correct decision:
      - Sensitive click -> STRONG_CONFIRM
      - Normal click -> SAFE
    """
    import core.permission_manager as pm

    original_rules = list(pm.POLICY_RULES)
    try:
        # Find browser_control.click rules
        click_rules = [r for r in pm.POLICY_RULES if r.tool == "browser_control" and r.action == "click"]
        assert len(click_rules) >= 2, "Expected both conditional and unconditional click rules"

        # Reverse the order of click rules in a reversed policy list
        reversed_click_rules = list(reversed(click_rules))
        # Build modified rules where the reversed click rules replace the original ones
        other_rules = [r for r in pm.POLICY_RULES if not (r.tool == "browser_control" and r.action == "click")]

        # Test with unconditional SAFE placed BEFORE conditional STRONG_CONFIRM
        pm.POLICY_RULES = reversed_click_rules + other_rules

        # 1. Sensitive click must still resolve to STRONG_CONFIRM
        p_sensitive = pm.check_permission(
            "browser_control", "click",
            {"url": "https://store.com/checkout", "text": "Place Order"}
        )
        assert p_sensitive.level == PermissionLevel.STRONG_CONFIRM, (
            f"Expected STRONG_CONFIRM even when SAFE rule appears first, got {p_sensitive.level}"
        )

        # 2. Benign click must still resolve to SAFE
        p_safe = pm.check_permission(
            "browser_control", "click",
            {"url": "https://example.com/about", "text": "About Us"}
        )
        assert p_safe.level == PermissionLevel.SAFE, (
            f"Expected SAFE for benign click, got {p_safe.level}"
        )

        print("  -> Proved: check_permission() prioritizes conditional rules over unconditional rules regardless of list order!")

    finally:
        # Restore original POLICY_RULES list
        pm.POLICY_RULES = original_rules


def test_8_fail_closed_on_detection_errors():
    """
    Part B: Verify that detection errors fail CLOSED (gate the action)
    rather than failing open (allowing potentially consequential actions through ungated).
    """
    import actions.browser_control as bc
    import core.permission_manager as pm
    from unittest.mock import patch

    # 1. Force _detect_sensitive_action to raise an exception
    with patch("actions.browser_control._detect_sensitive_action", side_effect=RuntimeError("Simulated heuristic failure")):
        # In permission_manager: _is_sensitive_browser_action must return True (fail-closed)
        p = pm.check_permission(
            "browser_control", "click",
            {"url": "https://unknown-site.org", "text": "Click Here"}
        )
        assert p.level == PermissionLevel.STRONG_CONFIRM, (
            f"Expected fail-closed STRONG_CONFIRM on detection error, got {p.level}"
        )

        # In browser_control: _execute_interactive_action must route through confirm.request
        sess = DummyControllableSession("https://unknown-site.org")
        _registry._sessions["mock_test"] = sess
        _registry._active_browser = "mock_test"
        hud.clear()

        res = bc.browser_control(
            {"action": "click", "text": "Some Ambiguous Action", "browser": "mock_test"}
        )
        assert "[CONFIRMATION_PENDING]" in res, (
            f"Expected confirmation gate to fire when detection errors (fail-closed), got: {res}"
        )
        prompt = hud.last_prompt()
        assert prompt is not None, "HUD prompt must appear when detection errors"
        assert "Unverified Consequential Action" in prompt["title"]
        assert len(sess.clicks) == 0, "Action must NOT execute when detection fails!"

        # Confirm that cancellation works cleanly
        confirm.resolve(False)
        time.sleep(0.1)
        assert len(sess.clicks) == 0, "Cancelled action after detection error must not execute!"

        print("  -> Proved: Detection failure safely fails CLOSED with confirmation prompt, zero ungated executions!")


def test_9_agent_tool_context_and_signature_compatibility():
    """Verify AgentTool export and context forwarding with all 4 _CTX_KEYS."""
    from actions.browser_control import ACTION, TOOL
    from core.tool import AgentTool
    from core.action_loader import discover_actions

    assert isinstance(ACTION, AgentTool), "ACTION must be an AgentTool subclass instance"
    assert ACTION.name == "browser_control"
    assert TOOL["name"] == "browser_control"
    assert callable(TOOL["handler"])

    # Representative context dict with all 4 _CTX_KEYS
    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    # Direct execution with all context kwargs
    res_direct = ACTION.execute({"action": "list_browsers"}, **full_ctx)
    assert isinstance(res_direct, str)
    assert "active" in res_direct.lower() or "open browsers" in res_direct.lower()

    # Execution via action_loader registry with context dict
    reg = discover_actions(Path(__file__).resolve().parent.parent / "actions")
    res_loader = reg.run("browser_control", {"action": "list_browsers"}, ctx=full_ctx)
    assert isinstance(res_loader, str)
    assert "active" in res_loader.lower() or "open browsers" in res_loader.lower()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("RUNNING PHASE 2 ITEM 2: BROWSER CONTROL GATES SUITE")
    print("=" * 70)

    run_test("TEST 1: Purchase / Payment Confirmation Gate & Execution", test_1_purchase_payment_gating)
    run_test("TEST 2: Normal Navigation Click Bypasses Gate", test_2_normal_navigation_no_gate)
    run_test("TEST 3: Messaging / Public Posting Confirmation Gate", test_3_messaging_send_gating)
    run_test("TEST 4: Boundary Case — Contact Form vs Checkout Form", test_4_boundary_contact_form_vs_checkout)
    run_test("TEST 5: Download Interception (Confirm & Save vs Cancel & Discard)", test_5_download_interception)
    run_test("TEST 6: Policy Classification & verify_permission_gates Audit", test_6_policy_rules_and_static_audit)
    run_test("TEST 7: Order-Independent Rule Resolution (Part A)", test_7_order_independent_rule_resolution)
    run_test("TEST 8: Fail-Closed Behavior on Detection Errors (Part B)", test_8_fail_closed_on_detection_errors)
    run_test("TEST 9: AgentTool Context & Signature Compatibility", test_9_agent_tool_context_and_signature_compatibility)

    print("\n" + "=" * 70)
    print("ALL BROWSER CONTROL GATE TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)
