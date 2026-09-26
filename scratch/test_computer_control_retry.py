"""
scratch/test_computer_control_retry.py
Comprehensive Dedicated Test Suite for Item 3 (Section 22: Error Recovery & Closed-Loop Action Retry).

Tests:
1. Transient Click Recovery (first-attempt miss -> second-attempt success after backoff)
2. Max Retry Exhaustion with Diagnostic Classification (total 3 attempts, explicit root cause)
3. Display Bounds Pre-verification (rejection of out-of-bounds coords without blind clicks)
4. Keyboard Retry with Window Focus Recovery (re-activating target window upon retry)
5. Observability Integration (core.logger logging verified=True on recovery, verified=False on exhaustion)
6. CONDITION 2: Fast-Path Overhead Measurement (measured milliseconds on first-attempt success)
7. CONDITION 3: State Machinery & Cooldown Interaction (WORKING state persistence and post-action cooldown timing)
"""

import sys
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
import json
import tempfile
import asyncio
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from unittest.mock import patch, MagicMock

import actions.computer_control as cc
from core.logger import ActionLogger


def test_1_transient_click_recovery():
    print("\n--- Test 1: Transient Click Recovery ---")
    attempts = 0

    def mock_screen_find(desc):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            # First attempt: element temporarily not visible/rendered
            return None
        # Second attempt: element rendered after backoff
        return 500, 300, "single"

    with patch.object(cc, "_screen_find", side_effect=mock_screen_find), \
         patch.object(cc, "_click", return_value="Clicked (500, 300) [left]"):

        res = cc.computer_control({
            "action": "screen_click",
            "description": "Submit Order",
        })

        assert "Clicked (500, 300) [left] on 'Submit Order'" in res, f"Unexpected response: {res}"
        assert attempts == 2, f"Expected exactly 2 attempts for transient recovery, got {attempts}"
        print(f"  -> Successfully recovered on attempt {attempts}: {res}")
        print("  -> Passed: Transient click recovery verified.")


def test_2_max_retry_exhaustion_diagnostics():
    print("\n--- Test 2: Max Retry Exhaustion with Diagnostic Classification ---")
    attempts = 0

    def mock_screen_find_fail(desc):
        nonlocal attempts
        attempts += 1
        return None

    with patch.object(cc, "_screen_find", side_effect=mock_screen_find_fail):
        start_t = time.perf_counter()
        res = cc.computer_control({
            "action": "screen_click",
            "description": "Invisible Button",
        })
        elapsed = time.perf_counter() - start_t

        assert "[FAILURE:ELEMENT_NOT_FOUND]" in res, f"Expected ELEMENT_NOT_FOUND diagnostic, got: {res}"
        assert "after 2 retries" in res or "total 3 attempts" in res
        assert attempts == 3, f"Expected 3 attempts (1 initial + 2 retries), got {attempts}"
        # Backoffs: 0.3s + 0.6s = ~0.9s
        assert elapsed >= 0.85, f"Expected backoff delay >= 0.85s, got {elapsed:.2f}s"
        print(f"  -> Exhaustion diagnostic verified (took {elapsed:.2f}s, {attempts} attempts):")
        print(f"       {res}")
        print("  -> Passed: Max retry exhaustion diagnostics verified.")


def test_3_display_bounds_pre_verification():
    print("\n--- Test 3: Display Bounds Pre-verification ---")
    with patch.object(cc.pyautogui, "size", return_value=(1920, 1080)), \
         patch.object(cc, "_click") as mock_click:

        # Case A: X exceeds screen width
        res_x = cc.computer_control({
            "action": "click",
            "x": 2560,
            "y": 500,
        })
        assert "[FAILURE:COORDINATES_OUT_OF_BOUNDS]" in res_x
        assert "Coordinates (2560, 500) exceed display bounds (1920x1080)" in res_x
        mock_click.assert_not_called()

        # Case B: Negative coordinate
        res_neg = cc.computer_control({
            "action": "click",
            "x": -10,
            "y": 500,
        })
        assert "[FAILURE:COORDINATES_OUT_OF_BOUNDS]" in res_neg
        mock_click.assert_not_called()

        print(f"  -> Out-of-bounds rejection verified:\n       {res_x}")
        print("  -> Passed: Invalid coordinates rejected safely without blind clicks.")


def test_4_keyboard_retry_with_focus_recovery():
    print("\n--- Test 4: Keyboard Retry with Focus Recovery ---")
    type_attempts = 0
    focus_calls = []

    def mock_type(text):
        nonlocal type_attempts
        type_attempts += 1
        if type_attempts == 1:
            raise RuntimeError("Target window not focused")
        return f"Typed: {text}"

    def mock_focus(title):
        focus_calls.append(title)
        return f"Focused window: {title}"

    with patch.object(cc, "_type", side_effect=mock_type), \
         patch.object(cc, "_focus_window", side_effect=mock_focus):

        res = cc.computer_control({
            "action": "type",
            "text": "Hello World",
            "title": "Notepad",
        })

        assert "Typed: Hello World" in res
        assert type_attempts == 2, f"Expected 2 typing attempts, got {type_attempts}"
        assert focus_calls == ["Notepad"], f"Expected focus_window('Notepad') on re-verification, got {focus_calls}"
        print(f"  -> Keyboard focus recovery verified: {res} (Focus calls: {focus_calls})")
        print("  -> Passed: Keyboard retry with focus recovery verified.")


def test_5_observability_logging_integration():
    print("\n--- Test 5: Observability Logging Integration ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_log = Path(tmp_dir) / "agent_actions.jsonl"
        ActionLogger.set_log_path(test_log)

        try:
            # 1. Recovered transient success -> verified=True
            with patch.object(cc, "_screen_find", side_effect=[None, (300, 400, "single")]), \
                 patch.object(cc, "_click", return_value="Clicked (300, 400) [left]"):

                res_rec = cc.computer_control({
                    "action": "screen_click",
                    "description": "Save Button",
                })
                ActionLogger.log_event(
                    tool="computer_control",
                    action="screen_click",
                    parameters={"description": "Save Button"},
                    permission={"level": "SAFE", "reason": "UI click"},
                    result=res_rec,
                )

            # 2. Exhausted failure -> verified=False with diagnostic source
            with patch.object(cc, "_screen_find", return_value=None):
                res_fail = cc.computer_control({
                    "action": "screen_click",
                    "description": "Missing Button",
                })
                ActionLogger.log_event(
                    tool="computer_control",
                    action="screen_click",
                    parameters={"description": "Missing Button"},
                    permission={"level": "SAFE", "reason": "UI click"},
                    result=res_fail,
                )

            lines = test_log.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 2, f"Expected 2 log records, got {len(lines)}"

            rec_success = json.loads(lines[0])
            assert rec_success["verified"] is True
            assert rec_success["verification_source"] == "ui_automation"

            rec_failure = json.loads(lines[1])
            assert rec_failure["verified"] is False
            assert rec_failure["verification_source"] == "ui_automation"
            assert "[FAILURE:ELEMENT_NOT_FOUND]" in rec_failure["verification_details"]

            print(f"  -> Logged recovered success: verified={rec_success['verified']}, source={rec_success['verification_source']}")
            print(f"  -> Logged exhausted failure: verified={rec_failure['verified']}, details={rec_failure['verification_details'][:60]}...")
            print("  -> Passed: Observability logging integration verified.")

        finally:
            ActionLogger.reset_default_path()


def test_6_fast_path_overhead_measurement():
    print("\n--- Test 6: Fast-Path Overhead Measurement (Condition 2) ---")
    # Measure the exact overhead of _retry_action and pre-verification on first-attempt success
    iterations = 5000

    with patch.object(cc.pyautogui, "size", return_value=(1920, 1080)), \
         patch.object(cc.pyautogui, "click"), \
         patch("builtins.print"):

        # Baseline: raw mock click
        t0 = time.perf_counter()
        for _ in range(iterations):
            cc._click(500, 500, "left", clicks=1)
        raw_duration = time.perf_counter() - t0

        # Wrapped: through computer_control dispatch + _retry_action + pre-verification
        t1 = time.perf_counter()
        for _ in range(iterations):
            cc.computer_control({"action": "click", "x": 500, "y": 500})
        wrapped_duration = time.perf_counter() - t1

    raw_ms_per_call = (raw_duration / iterations) * 1000.0
    wrapped_ms_per_call = (wrapped_duration / iterations) * 1000.0
    overhead_ms = max(0.0, wrapped_ms_per_call - raw_ms_per_call)

    print(f"  -> Raw call average:     {raw_ms_per_call:.4f} ms")
    print(f"  -> Wrapped call average: {wrapped_ms_per_call:.4f} ms")
    print(f"  -> MEASURED OVERHEAD:    {overhead_ms:.4f} ms per first-attempt call")

    # Prove overhead is strictly under 1 millisecond (< 0.1 ms expected)
    assert overhead_ms < 1.0, f"Overhead exceeded 1.0ms limit: {overhead_ms:.4f} ms"
    print("  -> Passed: Fast-path overhead strictly verified (< 1.0 ms).")


def test_7_state_machinery_and_cooldown_interaction():
    print("\n--- Test 7: State Machinery & Cooldown Interaction (Condition 3) ---")
    # Trace AgentLive state transitions and cooldown during multi-attempt retry

    class MockUI:
        def __init__(self):
            self.state = "LISTENING"
            self.muted = False
            self.state_history = []
        def set_state(self, s):
            self.state = s
            self.state_history.append((s, time.monotonic()))
        def write_log(self, msg):
            pass

    mock_ui = MockUI()

    # AgentLive simulator mimicking main.py::_execute_tool
    class AgentLiveSim:
        def __init__(self, ui):
            self.ui = ui
            self._action_in_flight = False
            self._action_cooldown_until = 0.0

        async def execute_tool_sim(self, tool_func):
            self.ui.set_state("THINKING")
            self._action_in_flight = True
            if not self.ui.muted:
                self.ui.set_state("WORKING")

            try:
                # Execute tool (which may take multiple retries and backoff)
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, tool_func)
                return result
            finally:
                self._action_in_flight = False
                self._action_cooldown_until = time.monotonic() + 0.35
                if not self.ui.muted:
                    self.ui.set_state("LISTENING")

    sim = AgentLiveSim(mock_ui)

    # Simulate an action that undergoes 2 retries (0.2s + 0.4s backoff = ~0.6s)
    retry_count = 0
    in_flight_samples = []

    def mock_retry_action_with_checks():
        nonlocal retry_count
        retry_count += 1
        # Sample state during retry execution
        in_flight_samples.append((sim._action_in_flight, sim.ui.state))
        if retry_count < 3:
            raise cc.ActionExecutionError("TRANSIENT", "Retry needed")
        return "Action succeeded on attempt 3"

    async def run_scenario():
        start_exec = time.monotonic()
        res = await sim.execute_tool_sim(
            lambda: cc._retry_action("test_action", mock_retry_action_with_checks, max_retries=2, initial_backoff=0.2)
        )
        end_exec = time.monotonic()
        return res, start_exec, end_exec

    res, t_start, t_end = asyncio.run(run_scenario())

    assert res == "Action succeeded on attempt 3"
    assert retry_count == 3, f"Expected 3 attempts, got {retry_count}"

    # Verify that in-flight and WORKING were active across all samples during the retry sequence
    assert all(flight is True for flight, _ in in_flight_samples), "Action in flight must stay True during retries!"
    assert all(state == "WORKING" for _, state in in_flight_samples), "UI state must remain 'WORKING' during retries!"

    # Verify state after completion
    assert sim._action_in_flight is False, "Action in flight must drop to False after completion!"
    assert sim.ui.state == "LISTENING", "UI state must return to 'LISTENING' after completion!"

    # Verify cooldown: must be set relative to completion time (t_end), not start time (t_start)
    cooldown_remaining = sim._action_cooldown_until - t_end
    assert 0.30 <= cooldown_remaining <= 0.40, (
        f"Cooldown should be ~0.35s after completion, got {cooldown_remaining:.3f}s"
    )

    print(f"  -> Multi-attempt retry completed across {retry_count} attempts ({t_end - t_start:.2f}s total duration).")
    print(f"  -> State during retries: in_flight=True, state=WORKING across all {len(in_flight_samples)} attempts.")
    print(f"  -> State after retries:  in_flight=False, state=LISTENING.")
    print(f"  -> Post-action cooldown verified: {cooldown_remaining:.3f}s remaining relative to completion time.")
    print("  -> Passed: State machinery and cooldown interaction verified.")


def main():
    print("=" * 70)
    print("RUNNING ITEM 3 (SECTION 22: ERROR RECOVERY) TEST SUITE")
    print("=" * 70)

    test_1_transient_click_recovery()
    test_2_max_retry_exhaustion_diagnostics()
    test_3_display_bounds_pre_verification()
    test_4_keyboard_retry_with_focus_recovery()
    test_5_observability_logging_integration()
    test_6_fast_path_overhead_measurement()
    test_7_state_machinery_and_cooldown_interaction()

    print("\n" + "=" * 70)
    print("ALL ITEM 3 ERROR RECOVERY & CLOSED-LOOP RETRY TESTS PASSED CLEANLY!")
    print("=" * 70)


if __name__ == "__main__":
    main()
