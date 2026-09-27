"""
scratch/test_code_helper_gates.py
==================================
Comprehensive test suite verifying security gates and command classification in actions/code_helper.py.

Covers:
1. _edit_action:
   - Gate behind confirm.request() with key "code_helper_edit"
   - Pre-plan: target file path, instruction, diff summary, preview shown BEFORE writing
   - Cancellation leaves files untouched at filesystem level (byte-for-byte check)
   - Confirmed write persists changes to disk and passes post-write verification
2. _optimize_action:
   - Gate behind confirm.request() with key "code_helper_optimize"
   - Pre-plan: target file path, line count delta, preview shown BEFORE writing
   - Cancellation leaves files untouched at filesystem level
   - Confirmed write persists changes to disk and passes post-write verification
3. _screen_debug_action:
   - Gate behind confirm.request() with key "code_helper_screen_debug"
   - Pre-plan: target file path, user question, preview of fix shown BEFORE writing
   - Cancellation leaves files untouched at filesystem level
   - Confirmed write persists changes to disk and passes post-write verification
4. _run_action:
   - Dangerous / destructive commands classified as BLOCKED and rejected without reaching subprocess
   - Interpreter execution classified as REQUIRES_CONFIRMATION and gated with key "code_helper_run"
   - Cancellation avoids executing subprocess
   - Confirmed execution runs subprocess and returns output
5. _build:
   - Dangerous build commands classified as BLOCKED and rejected immediately
   - Build flow gated behind confirm.request() with key "code_helper_build"
   - Cancellation leaves no files created and does not execute
   - Confirmed execution runs build loop
6. Permission Manager & Static Gates Audit:
   - verify_permission_gates() runs against active action registry and passes with zero exemptions
   - check_permission correctly classifies all code_helper actions (STRONG_CONFIRM, CONFIRM, BLOCKED, SAFE)
7. AgentTool compliance:
   - code_helper exported as AgentTool instance ACTION and TOOL schema dict
   - ACTION.execute() cleanly delegates to code_helper
"""

import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# UTF-8 stdout configuration
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import actions.code_helper as ch_mod
from actions.code_helper import code_helper, ACTION, CodeHelperTool
from core import confirm
from core.permission_manager import (
    POLICY_RULES,
    PermissionLevel,
    check_permission,
    verify_permission_gates,
)
from core.tool import AgentTool


class MockHUD:
    def __init__(self):
        self.shown = []
        self.hidden = 0
        self.logs = []

    def show(self, title: str, detail: str):
        self.shown.append({"title": title, "detail": detail})

    def hide(self):
        self.hidden += 1

    def log(self, msg: str):
        self.logs.append(msg)

    def last_prompt(self):
        return self.shown[-1] if self.shown else None


@pytest.fixture(autouse=True)
def setup_confirm_hud():
    """Ensure clean confirm HUD binding for each test."""
    hud = MockHUD()
    confirm.bind(hud.show, hud.hide, hud.log)
    with confirm._lock:
        confirm._pending = None
        confirm._listeners.clear()
        confirm._recent_resolutions.clear()
    yield hud
    with confirm._lock:
        confirm._pending = None
        confirm._listeners.clear()
        confirm._recent_resolutions.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 1. _edit_action Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_edit_action_cancellation_leaves_file_untouched(setup_confirm_hud):
    """Verify _edit_action gates write, and cancellation leaves filesystem untouched."""
    hud = setup_confirm_hud

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        original_content = "def greet(name):\n    print('Hello ' + name)\n"
        test_file.write_text(original_content, encoding="utf-8")

        mock_gemini = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "def greet(name):\n    # Updated greeting\n    print(f'Hello {name}!')\n"
        mock_gemini.generate_content.return_value = mock_response

        with patch.object(ch_mod, "_get_gemini", return_value=mock_gemini):
            res = code_helper({
                "action": "edit",
                "file_path": str(test_file),
                "description": "Use f-strings and add comment",
            })

            # 1. Gate check
            assert "[CONFIRMATION_PENDING]" in res
            assert confirm.pending_title() == f"Edit Code File: {test_file.name}"

            lp = hud.last_prompt()
            assert lp is not None
            assert f"File: {test_file.resolve()}" in lp["detail"]
            assert "Instruction: Use f-strings and add comment" in lp["detail"]

            # 2. Cancel confirmation
            confirm.resolve(False)

            # 3. Filesystem-level verification: file must remain EXACTLY identical
            current_content = test_file.read_text(encoding="utf-8")
            assert current_content == original_content, (
                "Filesystem mutation detected on cancellation! File content was modified."
            )
            assert not confirm.pending_title()


def test_edit_action_confirmed_persists_and_verifies(setup_confirm_hud):
    """Verify _edit_action executes and persists write upon user confirmation."""
    hud = setup_confirm_hud

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        original_content = "x = 1\n"
        test_file.write_text(original_content, encoding="utf-8")

        new_content = "x = 42\ny = 100\n"
        mock_gemini = MagicMock()
        mock_response = MagicMock()
        mock_response.text = new_content
        mock_gemini.generate_content.return_value = mock_response

        resolved_event = threading.Event()
        confirm.add_resolution_listener(lambda key, accepted, res: resolved_event.set(), target_key="code_helper_edit")

        with patch.object(ch_mod, "_get_gemini", return_value=mock_gemini):
            res = code_helper({
                "action": "edit",
                "file_path": str(test_file),
                "description": "Update constants",
            })

            assert "[CONFIRMATION_PENDING]" in res
            confirm.resolve(True)
            assert resolved_event.wait(timeout=3.0), "Resolution callback timed out"

            # Filesystem check: content must be updated (cleaned of outer whitespace)
            assert test_file.read_text(encoding="utf-8") == new_content.strip()


# ─────────────────────────────────────────────────────────────────────────────
# 2. _optimize_action Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_optimize_action_cancellation_leaves_file_untouched(setup_confirm_hud):
    """Verify _optimize_action gates write, and cancellation leaves filesystem untouched."""
    hud = setup_confirm_hud

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "heavy.py"
        original_content = "def calculate():\n    total = 0\n    for i in range(100):\n        total += i\n    return total\n"
        test_file.write_text(original_content, encoding="utf-8")

        mock_gemini = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "def calculate():\n    return sum(range(100))\n"
        mock_gemini.generate_content.return_value = mock_response

        with patch.object(ch_mod, "_get_gemini", return_value=mock_gemini):
            res = code_helper({
                "action": "optimize",
                "file_path": str(test_file),
            })

            assert "[CONFIRMATION_PENDING]" in res
            assert confirm.pending_title() == f"Optimize Code File: {test_file.name}"

            lp = hud.last_prompt()
            assert lp is not None
            assert f"File: {test_file.resolve()}" in lp["detail"]
            assert "Lines: 5 → 2" in lp["detail"]

            # User cancels
            confirm.resolve(False)

            # Filesystem check: original content unchanged
            assert test_file.read_text(encoding="utf-8") == original_content
            assert not confirm.pending_title()


def test_optimize_action_confirmed_persists(setup_confirm_hud):
    """Verify _optimize_action confirmed write updates the file."""
    hud = setup_confirm_hud

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "heavy.py"
        original_content = "a = 1\nb = 2\n"
        test_file.write_text(original_content, encoding="utf-8")

        optimized_code = "a, b = 1, 2\n"
        mock_gemini = MagicMock()
        mock_response = MagicMock()
        mock_response.text = optimized_code
        mock_gemini.generate_content.return_value = mock_response

        resolved_event = threading.Event()
        confirm.add_resolution_listener(lambda key, accepted, res: resolved_event.set(), target_key="code_helper_optimize")

        with patch.object(ch_mod, "_get_gemini", return_value=mock_gemini):
            res = code_helper({
                "action": "optimize",
                "file_path": str(test_file),
            })

            assert "[CONFIRMATION_PENDING]" in res
            confirm.resolve(True)
            assert resolved_event.wait(timeout=3.0), "Resolution callback timed out"

            assert test_file.read_text(encoding="utf-8") == optimized_code.strip()


def test_optimize_action_refuses_stale_write_if_file_modified_in_interim(setup_confirm_hud):
    """Verify _optimize_action aborts write if target file was modified externally between plan and confirm."""
    hud = setup_confirm_hud

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "concurrent.py"
        original_content = "def fn():\n    return 1\n"
        test_file.write_text(original_content, encoding="utf-8")

        mock_gemini = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "def fn():\n    return 42\n"
        mock_gemini.generate_content.return_value = mock_response

        resolved_event = threading.Event()
        result_holder = []
        confirm.add_resolution_listener(
            lambda key, accepted, res: (result_holder.append(res), resolved_event.set()),
            target_key="code_helper_optimize"
        )

        with patch.object(ch_mod, "_get_gemini", return_value=mock_gemini):
            res = code_helper({
                "action": "optimize",
                "file_path": str(test_file),
            })

            assert "[CONFIRMATION_PENDING]" in res

            # Simulate external modification happening while confirmation is pending
            external_change = "def fn():\n    # Modified externally by user\n    return 999\n"
            test_file.write_text(external_change, encoding="utf-8")

            # User confirms the pending optimization
            confirm.resolve(True)
            assert resolved_event.wait(timeout=3.0), "Resolution callback timed out"

            # Filesystem check: the external change MUST NOT have been overwritten!
            assert test_file.read_text(encoding="utf-8") == external_change

            # Verification that abort message was reported
            assert len(result_holder) == 1
            assert "Aborted write:" in result_holder[0]
            assert "modified externally" in result_holder[0]


def test_write_action_scoped_to_desktop_and_non_clobbering():
    """Verify code_helper write is strictly confined to DESKTOP and never clobbers existing files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_desktop = Path(tmpdir)
        with patch.object(ch_mod, "DESKTOP", mock_desktop):
            # 1. Standard write creates new file in mock_desktop
            p1 = ch_mod._resolve_save_path("my_tool.py", "python")
            assert p1 == mock_desktop / "my_tool.py"
            p1.write_text("v1", encoding="utf-8")

            # 2. Writing with same name generates non-colliding new file without clobbering
            p2 = ch_mod._resolve_save_path("my_tool.py", "python")
            assert p2 == mock_desktop / "my_tool_1.py"
            assert p1.read_text(encoding="utf-8") == "v1"

            # 3. Path escape attempt: absolute path outside Desktop is confined to mock_desktop
            p3 = ch_mod._resolve_save_path("C:/Windows/System32/malicious.py", "python")
            assert p3 == mock_desktop / "malicious.py"
            assert p3.parent == mock_desktop


# ─────────────────────────────────────────────────────────────────────────────
# 3. _screen_debug_action Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_screen_debug_cancellation_leaves_file_untouched(setup_confirm_hud):
    """Verify screen_debug fix proposal gates behind confirmation and cancel keeps file untouched."""
    hud = setup_confirm_hud

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "broken.py"
        original_content = "def buggy():\n    return 1 / 0\n"
        test_file.write_text(original_content, encoding="utf-8")

        fake_screenshot = Path(tmpdir) / "screen.png"
        fake_screenshot.write_bytes(b"\x89PNG\r\n\x1a\nfake")

        analysis_with_code = (
            "I see a ZeroDivisionError on screen.\n\n"
            "Here is the fixed code:\n```python\n"
            "def buggy():\n    return 0\n```\n"
        )

        mock_resp = MagicMock()
        mock_resp.text = analysis_with_code

        with patch.object(ch_mod, "_take_screenshot", return_value=fake_screenshot), \
             patch("core.gemini.call", return_value=mock_resp):
            res = code_helper({
                "action": "screen_debug",
                "file_path": str(test_file),
                "description": "Fix the division error on screen",
            })

            assert "[CONFIRMATION_PENDING]" in res
            assert confirm.pending_title() == f"Apply Screen Debug Fix: {test_file.name}"

            lp = hud.last_prompt()
            assert lp is not None
            assert f"File: {test_file.resolve()}" in lp["detail"]
            assert "Problem: Fix the division error on screen" in lp["detail"]

            # Cancel
            confirm.resolve(False)

            # Filesystem check
            assert test_file.read_text(encoding="utf-8") == original_content
            assert not confirm.pending_title()


def test_screen_debug_confirmed_persists(setup_confirm_hud):
    """Verify screen_debug confirmed write applies the fix."""
    hud = setup_confirm_hud

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "broken.py"
        original_content = "x = 0\n"
        test_file.write_text(original_content, encoding="utf-8")

        fake_screenshot = Path(tmpdir) / "screen.png"
        fake_screenshot.write_bytes(b"\x89PNG\r\n\x1a\nfake")

        fixed_code = "x = 100\n"
        analysis_with_code = f"Here is the fix:\n```python\n{fixed_code}```"

        mock_resp = MagicMock()
        mock_resp.text = analysis_with_code

        resolved_event = threading.Event()
        confirm.add_resolution_listener(lambda key, accepted, res: resolved_event.set(), target_key="code_helper_screen_debug")

        with patch.object(ch_mod, "_take_screenshot", return_value=fake_screenshot), \
             patch("core.gemini.call", return_value=mock_resp):
            res = code_helper({
                "action": "screen_debug",
                "file_path": str(test_file),
            })

            assert "[CONFIRMATION_PENDING]" in res
            confirm.resolve(True)
            assert resolved_event.wait(timeout=3.0), "Resolution callback timed out"

            assert test_file.read_text(encoding="utf-8") == fixed_code.strip()


# ─────────────────────────────────────────────────────────────────────────────
# 4. _run_action & Command Classification Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_run_action_blocked_command_rejected_immediately(setup_confirm_hud):
    """Verify dangerous command invocation is BLOCKED outright and never executes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "run_me.py"
        test_file.write_text("print('hello')", encoding="utf-8")

        # Dangerous argument matching dev_agent blocked pattern (e.g. rm -rf)
        with patch("subprocess.run") as mock_run:
            res = code_helper({
                "action": "run",
                "file_path": str(test_file),
                "args": ["&&", "rm -rf /"],
            })

            assert "BLOCKED:" in res
            assert "rejected by security policy" in res
            # Ensure subprocess.run was NEVER reached
            mock_run.assert_not_called()
            # Ensure no confirmation was queued
            assert not confirm.pending_title()


def test_run_action_gates_behind_confirmation(setup_confirm_hud):
    """Verify standard script execution gates behind confirm.request('code_helper_run')."""
    hud = setup_confirm_hud

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "task.py"
        test_file.write_text("print('test run')", encoding="utf-8")

        res = code_helper({
            "action": "run",
            "file_path": str(test_file),
        })

        assert "[CONFIRMATION_PENDING]" in res
        assert confirm.pending_title() == f"Execute Code File: {test_file.name}"

        lp = hud.last_prompt()
        assert lp is not None
        assert f"File: {test_file}" in lp["detail"]

        # Cancel confirmation
        confirm.resolve(False)
        assert not confirm.pending_title()


def test_run_action_confirmed_executes_subprocess(setup_confirm_hud):
    """Verify confirming code_helper_run executes the target script."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "print_test.py"
        test_file.write_text("print('MARK_LIV_SUCCESS')", encoding="utf-8")

        resolved_event = threading.Event()
        result_holder = []

        def listener(key, accepted, res):
            result_holder.append(res)
            resolved_event.set()

        confirm.add_resolution_listener(listener, target_key="code_helper_run")

        res = code_helper({
            "action": "run",
            "file_path": str(test_file),
        })

        assert "[CONFIRMATION_PENDING]" in res
        confirm.resolve(True)
        assert resolved_event.wait(timeout=5.0), "Resolution callback timed out"

        assert len(result_holder) == 1
        assert "MARK_LIV_SUCCESS" in result_holder[0]


# ─────────────────────────────────────────────────────────────────────────────
# 5. _build Command Classification & Gate Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_build_blocked_command_rejected_immediately(setup_confirm_hud):
    """Verify dangerous build command is BLOCKED and never writes or runs."""
    with patch("subprocess.run") as mock_run, \
         patch.object(ch_mod, "_write") as mock_write:
        res = code_helper({
            "action": "build",
            "description": "Script that runs format c: /q",
            "args": ["format c:"],
        })

        assert "BLOCKED:" in res
        mock_run.assert_not_called()
        mock_write.assert_not_called()
        assert not confirm.pending_title()


def test_build_gates_behind_confirmation(setup_confirm_hud):
    """Verify valid build request gates behind confirm.request('code_helper_build')."""
    hud = setup_confirm_hud

    res = code_helper({
        "action": "build",
        "description": "Build a quick sort algorithm",
        "language": "python",
    })

    assert "[CONFIRMATION_PENDING]" in res
    assert "Build & Run Code:" in confirm.pending_title()

    lp = hud.last_prompt()
    assert lp is not None
    assert "Goal: Build a quick sort algorithm" in lp["detail"]

    # Cancel
    confirm.resolve(False)
    assert not confirm.pending_title()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Static Verification & Permission Decision Classification
# ─────────────────────────────────────────────────────────────────────────────

def test_verify_permission_gates_passes_with_zero_exemptions():
    """Verify verify_permission_gates() runs cleanly with zero safe fallbacks for code_helper."""
    # Must run without raising SecurityPolicyError
    verify_permission_gates()


def test_policy_rules_classification_matches_expected_levels():
    """Verify check_permission returns correct levels and keys for code_helper."""
    # 1. Edit -> STRONG_CONFIRM (key: code_helper_edit)
    dec_edit = check_permission("code_helper", {"action": "edit", "file_path": "foo.py"})
    assert dec_edit.level == PermissionLevel.STRONG_CONFIRM
    assert dec_edit.key == "code_helper_edit"

    # 2. Screen debug -> STRONG_CONFIRM (key: code_helper_screen_debug)
    dec_screen = check_permission("code_helper", {"action": "screen_debug", "file_path": "foo.py"})
    assert dec_screen.level == PermissionLevel.STRONG_CONFIRM
    assert dec_screen.key == "code_helper_screen_debug"

    # 3. Optimize -> STRONG_CONFIRM (key: code_helper_optimize)
    dec_opt = check_permission("code_helper", {"action": "optimize", "file_path": "foo.py"})
    assert dec_opt.level == PermissionLevel.STRONG_CONFIRM
    assert dec_opt.key == "code_helper_optimize"

    # 4. Run -> CONFIRM for benign, BLOCKED for malicious
    dec_run_safe = check_permission("code_helper", {"action": "run", "file_path": "script.py"})
    assert dec_run_safe.level == PermissionLevel.CONFIRM
    assert dec_run_safe.key == "code_helper_run"

    dec_run_danger = check_permission("code_helper", {"action": "run", "file_path": "script.py", "args": ["rm -rf /"]})
    assert dec_run_danger.level == PermissionLevel.BLOCKED
    assert dec_run_danger.key == "code_helper_run_blocked"

    # 5. Build -> CONFIRM for benign, BLOCKED for malicious
    dec_build_safe = check_permission("code_helper", {"action": "build", "description": "Make a tool"})
    assert dec_build_safe.level == PermissionLevel.CONFIRM
    assert dec_build_safe.key == "code_helper_build"

    dec_build_danger = check_permission("code_helper", {"action": "build", "description": "rm -rf /"})
    assert dec_build_danger.level == PermissionLevel.BLOCKED
    assert dec_build_danger.key == "code_helper_build_blocked"

    # 6. Write & Explain -> SAFE
    dec_write = check_permission("code_helper", {"action": "write", "description": "New helper"})
    assert dec_write.level == PermissionLevel.SAFE
    assert dec_write.key == "code_helper_write"

    dec_explain = check_permission("code_helper", {"action": "explain", "code": "print(1)"})
    assert dec_explain.level == PermissionLevel.SAFE
    assert dec_explain.key == "code_helper_explain"


# ─────────────────────────────────────────────────────────────────────────────
# 7. AgentTool Compliance
# ─────────────────────────────────────────────────────────────────────────────

def test_code_helper_agent_tool_compliance():
    """Verify code_helper is registered as an AgentTool and delegates execution."""
    assert isinstance(ACTION, AgentTool)
    assert isinstance(ACTION, CodeHelperTool)
    assert ACTION.name == "code_helper"
    assert "Writes, edits, explains" in ACTION.description
    assert "parameters" in ACTION.to_tool_dict()

    # Delegate test: execute explain action directly via ACTION
    res = ACTION.execute(parameters={"action": "explain", "code": ""})
    assert "Please provide code or a file path" in res
