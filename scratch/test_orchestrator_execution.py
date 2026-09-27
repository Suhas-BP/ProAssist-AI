"""
scratch/test_orchestrator_execution.py
======================================
Permanent dedicated regression test suite for Sub-Phase 5B (PlanExecutor).

Covers:
1. Basic linear multi-step execution (happy path).
2. Security policy BLOCKED step halts immediately (report-and-stop).
3. Plan-level collision guard rejects concurrent plans while one is active.
4. Single-pause confirmation and asynchronous resume with real result threading.
5. User cancellation halts execution cleanly (PlanState.CANCELLED).
6. Resumed step verification failure routes to failure and halts execution.
7. Explicit open_app verification branches (4A window, 4B PID check, 4C failure).
8. Forced worst-case asyncio reentrancy fixture (fencing token guard verification).
9. Multi-pause index consistency with real background threading.
"""

import asyncio
import os
import random
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

# UTF-8 stdout
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import confirm
from core.permission_manager import check_permission, PermissionLevel
from agent.planner import ExecutionPlan, PlanStep, PlanState, StepStatus
from agent.context import AgentContext
from agent.orchestrator import PlanExecutor, PlanCollisionError, StepCall


def setup_confirm_hud():
    """Bind dummy HUD callbacks so confirm.request() is operational."""
    confirm.bind(
        show=lambda title, detail: None,
        hide=lambda: None,
        log=lambda msg: None,
    )


def reset_confirm_state():
    """Reset confirm module internal state between test cases."""
    with confirm._lock:
        confirm._pending = None
        confirm._listeners.clear()
        confirm._recent_resolutions.clear()


@pytest.fixture(autouse=True)
def clean_test_state():
    setup_confirm_hud()
    reset_confirm_state()
    with AgentContext.get_instance()._lock:
        AgentContext.get_instance()._previous_action_result = None
    yield
    reset_confirm_state()


def async_test(coro_fn):
    import functools
    @functools.wraps(coro_fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(coro_fn(*args, **kwargs))
    return wrapper


# ── Test 1: Basic Linear Multi-Step Execution (Happy Path) ────────────────────

@async_test
async def test_basic_linear_execution_flow():
    executed_tools = []

    async def mock_execute_tool(self_agent, step_call: StepCall):
        executed_tools.append((step_call.name, step_call.args.get("action")))
        return type("Resp", (), {"response": f"Tool {step_call.name} executed successfully."})()

    agent = type("MockAgent", (), {
        "_execute_tool": mock_execute_tool,
        "loop": asyncio.get_running_loop(),
    })()

    executor = PlanExecutor(agent=agent)

    steps = [
        PlanStep(step_id=1, tool="file_controller", action="list", parameters={"path": "."}, description="List files"),
        PlanStep(step_id=2, tool="system_status", action="get", parameters={}, description="Get status"),
        PlanStep(step_id=3, tool="file_controller", action="read", parameters={"path": "dummy.txt"}, description="Read file"),
    ]
    plan = ExecutionPlan(plan_id="plan_linear_1", goal="Test Linear Flow", steps=steps)

    res_plan = await executor.execute_plan(plan)

    assert res_plan.state == PlanState.COMPLETED
    assert res_plan.current_step_index == 3
    assert all(s.status == StepStatus.COMPLETED for s in res_plan.steps)
    assert all(s.verified is True for s in res_plan.steps)
    assert len(executed_tools) == 3
    assert executed_tools == [
        ("file_controller", "list"),
        ("system_status", "get"),
        ("file_controller", "read"),
    ]


# ── Test 2: Security BLOCKED Step Halts Immediately ───────────────────────────

@async_test
async def test_security_blocked_step_halts_immediately():
    executed_tools = []

    async def mock_execute_tool(self_agent, step_call: StepCall):
        executed_tools.append(step_call.name)
        return type("Resp", (), {"response": "OK"})()

    agent = type("MockAgent", (), {
        "_execute_tool": mock_execute_tool,
        "loop": asyncio.get_running_loop(),
    })()

    executor = PlanExecutor(agent=agent)

    steps = [
        PlanStep(step_id=1, tool="file_controller", action="list", parameters={"path": "."}, description="Safe List"),
        PlanStep(step_id=2, tool="dev_agent", action="run_project", parameters={"command": "format C:"}, description="Dangerous Command"),
        PlanStep(step_id=3, tool="file_controller", action="list", parameters={"path": "."}, description="Unreachable Step"),
    ]
    plan = ExecutionPlan(plan_id="plan_blocked_1", goal="Test Blocked Policy", steps=steps)

    res_plan = await executor.execute_plan(plan)

    assert res_plan.state == PlanState.FAILED
    assert res_plan.steps[0].status == StepStatus.COMPLETED
    assert res_plan.steps[1].status == StepStatus.FAILED
    assert "Security Policy BLOCKED" in str(res_plan.steps[1].error)
    assert res_plan.steps[2].status == StepStatus.PENDING
    assert len(executed_tools) == 1  # Step 2 and 3 NEVER dispatched!


# ── Test 3: Plan-Level Collision Guard ────────────────────────────────────────

@async_test
async def test_plan_level_collision_guard():
    async def mock_execute_tool(self_agent, step_call: StepCall):
        if step_call.args.get("action") == "delete":
            res = confirm.request(
                key="delete_file",
                title="Delete",
                detail="Delete dummy.txt",
                run=lambda: "Deleted",
            )
            return type("Resp", (), {"response": res})()
        return type("Resp", (), {"response": "OK"})()

    agent = type("MockAgent", (), {
        "_execute_tool": mock_execute_tool,
        "loop": asyncio.get_running_loop(),
    })()

    executor = PlanExecutor(agent=agent)

    plan1 = ExecutionPlan(
        plan_id="plan_active_1",
        goal="Plan 1",
        steps=[
            PlanStep(step_id=1, tool="file_controller", action="delete", parameters={"path": "dummy.txt"}, description="Step 1"),
        ],
    )
    plan2 = ExecutionPlan(
        plan_id="plan_active_2",
        goal="Plan 2",
        steps=[
            PlanStep(step_id=1, tool="file_controller", action="list", parameters={"path": "."}, description="Step 1"),
        ],
    )

    # Execute Plan 1 (pauses for confirmation)
    await executor.execute_plan(plan1)
    assert plan1.state == PlanState.PAUSED_FOR_CONFIRMATION

    # Attempt to execute Plan 2 while Plan 1 is specifically in PAUSED_FOR_CONFIRMATION -> Collision!
    with pytest.raises(PlanCollisionError) as exc_info:
        await executor.execute_plan(plan2)
    assert "Plan collision" in str(exc_info.value)
    assert "plan_active_1" in str(exc_info.value)
    assert "PAUSED_FOR_CONFIRMATION" in str(exc_info.value)

    # Cancel Plan 1 explicitly
    cancelled = executor.cancel_active_plan(reason="User cancelled")
    assert cancelled is not None
    assert cancelled.state == PlanState.CANCELLED

    # Now Plan 2 executes cleanly
    res2 = await executor.execute_plan(plan2)
    assert res2.state == PlanState.COMPLETED

    # Also test collision while Plan 3 is actively RUNNING
    plan3_in_flight = threading.Event()
    plan3_release = threading.Event()

    async def mock_slow_tool(*args, **kwargs):
        plan3_in_flight.set()
        while not plan3_release.is_set():
            await asyncio.sleep(0.01)
        return type("Resp", (), {"response": "OK"})()

    agent._execute_tool = mock_slow_tool

    plan3 = ExecutionPlan(
        plan_id="plan_active_3",
        goal="Plan 3",
        steps=[PlanStep(step_id=1, tool="file_controller", action="list", parameters={"path": "."}, description="Step 1")],
    )
    plan4 = ExecutionPlan(
        plan_id="plan_active_4",
        goal="Plan 4",
        steps=[PlanStep(step_id=1, tool="file_controller", action="list", parameters={"path": "."}, description="Step 1")],
    )

    task_plan3 = asyncio.create_task(executor.execute_plan(plan3))
    while not plan3_in_flight.is_set():
        await asyncio.sleep(0.005)

    assert plan3.state == PlanState.RUNNING

    # Attempt to execute Plan 4 while Plan 3 is specifically in RUNNING state -> Collision!
    with pytest.raises(PlanCollisionError) as exc_info_running:
        await executor.execute_plan(plan4)
    assert "Plan collision" in str(exc_info_running.value)
    assert "plan_active_3" in str(exc_info_running.value)
    assert "RUNNING" in str(exc_info_running.value)

    # Release Plan 3 to finish
    plan3_release.set()
    await task_plan3
    assert plan3.state == PlanState.COMPLETED


# ── Test 4: Single Pause Confirm and Resume Flow with Real Result ─────────────

@async_test
async def test_single_pause_confirm_resume_flow():
    executed_tools = []

    async def mock_execute_tool(self_agent, step_call: StepCall):
        name = step_call.name
        action = step_call.args.get("action")
        executed_tools.append((name, action))

        if name == "file_controller" and action == "delete":
            res = confirm.request(
                key="delete_file",
                title="Delete File",
                detail="Delete dummy.txt",
                run=lambda: "File dummy.txt deleted successfully.",
            )
            return type("Resp", (), {"response": res})()
        return type("Resp", (), {"response": f"Tool {name} success"})()

    agent = type("MockAgent", (), {
        "_execute_tool": mock_execute_tool,
        "loop": asyncio.get_running_loop(),
    })()

    executor = PlanExecutor(agent=agent)

    steps = [
        PlanStep(step_id=1, tool="file_controller", action="list", parameters={"path": "."}, description="List"),
        PlanStep(step_id=2, tool="file_controller", action="delete", parameters={"path": "dummy.txt"}, description="Delete"),
        PlanStep(step_id=3, tool="file_controller", action="list", parameters={"path": "."}, description="Verify List"),
    ]
    plan = ExecutionPlan(plan_id="plan_pause_1", goal="Test Single Pause", steps=steps)

    # Phase 1: Dispatches Step 1 (completes) and Step 2 (pauses)
    p = await executor.execute_plan(plan)
    assert p.state == PlanState.PAUSED_FOR_CONFIRMATION
    assert p.current_step_index == 1
    assert p.steps[1].status == StepStatus.PAUSED_FOR_CONFIRMATION
    assert len(executed_tools) == 2

    # Phase 2: User confirms on HUD
    confirm.resolve(True)
    await asyncio.sleep(0.05)  # Yield for resume coroutine

    # Assert plan finished completely with real result
    assert plan.state == PlanState.COMPLETED
    assert plan.current_step_index == 3
    assert plan.steps[1].status == StepStatus.COMPLETED
    assert plan.steps[1].result == "File dummy.txt deleted successfully."  # Real result!
    assert plan.steps[1].verified is True
    assert len(executed_tools) == 3


# ── Test 5: Single Pause Cancellation Flow ────────────────────────────────────

@async_test
async def test_single_pause_cancellation_flow():
    async def mock_execute_tool(self_agent, step_call: StepCall):
        if step_call.args.get("action") == "delete":
            res = confirm.request(
                key="delete_file",
                title="Delete File",
                detail="Delete dummy.txt",
                run=lambda: "Should not execute",
            )
            return type("Resp", (), {"response": res})()
        return type("Resp", (), {"response": "OK"})()

    agent = type("MockAgent", (), {
        "_execute_tool": mock_execute_tool,
        "loop": asyncio.get_running_loop(),
    })()

    executor = PlanExecutor(agent=agent)

    steps = [
        PlanStep(step_id=1, tool="file_controller", action="delete", parameters={"path": "dummy.txt"}, description="Delete"),
        PlanStep(step_id=2, tool="file_controller", action="list", parameters={"path": "."}, description="Unreachable List"),
    ]
    plan = ExecutionPlan(plan_id="plan_cancel_1", goal="Test Cancel", steps=steps)

    await executor.execute_plan(plan)
    assert plan.state == PlanState.PAUSED_FOR_CONFIRMATION

    # User presses Cancel on HUD
    confirm.resolve(False)
    await asyncio.sleep(0.05)

    assert plan.state == PlanState.CANCELLED
    assert plan.steps[0].status == StepStatus.CANCELLED
    assert "User cancelled" in str(plan.steps[0].error)
    assert plan.steps[1].status == StepStatus.PENDING


# ── Test 6: Resumed Step Verification Failure Halts Plan ──────────────────────

@async_test
async def test_resumed_step_verification_failure_halts_plan():
    async def mock_execute_tool(self_agent, step_call: StepCall):
        if step_call.args.get("action") == "delete":
            res = confirm.request(
                key="delete_file",
                title="Delete File",
                detail="Delete dummy.txt",
                # The action is confirmed, but OS returns an explicit failure string!
                run=lambda: "[FAILURE: Access is denied]",
            )
            return type("Resp", (), {"response": res})()
        return type("Resp", (), {"response": "OK"})()

    agent = type("MockAgent", (), {
        "_execute_tool": mock_execute_tool,
        "loop": asyncio.get_running_loop(),
    })()

    executor = PlanExecutor(agent=agent)

    steps = [
        PlanStep(step_id=1, tool="file_controller", action="delete", parameters={"path": "dummy.txt"}, description="Delete"),
        PlanStep(step_id=2, tool="file_controller", action="list", parameters={"path": "."}, description="Next step"),
    ]
    plan = ExecutionPlan(plan_id="plan_fail_resume_1", goal="Test Resume Failure", steps=steps)

    await executor.execute_plan(plan)
    assert plan.state == PlanState.PAUSED_FOR_CONFIRMATION

    # Confirm the action on HUD
    confirm.resolve(True)
    await asyncio.sleep(0.05)

    # Must be caught by _verify_step_outcome and routed to _handle_failure!
    assert plan.state == PlanState.FAILED
    assert plan.steps[0].status == StepStatus.FAILED
    assert "[FAILURE: Access is denied]" in str(plan.steps[0].error)
    assert plan.steps[1].status == StepStatus.PENDING  # Next step NEVER run!


# ── Test 7: Explicit open_app Verification Branches ───────────────────────────

def test_open_app_verification_branches():
    executor = PlanExecutor(agent=None)
    step = PlanStep(step_id=1, tool="open_app", action="launch", parameters={"app_name": "notepad"}, description="Open Notepad")
    ctx = AgentContext.get_instance()

    # Branch 4A: App window detected in foreground or open application list
    with ctx._lock:
        ctx._open_apps_cache = ["Notepad - Untitled", "Calculator"]
        ctx._open_apps_cache_time = time.monotonic()
        ctx._previous_action_result = None

    ok, details = executor._verify_step_outcome(step, "Launched")
    assert ok is True
    assert "window detected" in details

    # Branch 4B: Window not detected, but OS process verified via psutil PID check in AgentContext
    with ctx._lock:
        ctx._open_apps_cache = ["Calculator"]
        ctx._open_apps_cache_time = time.monotonic()
        ctx._previous_action_result = {"verified": True, "verification_source": "psutil_pid_check"}

    ok, details = executor._verify_step_outcome(step, "Launched")
    assert ok is True
    assert "process verified via psutil_pid_check" in details

    # Branch 4C: Neither window nor process verified
    with ctx._lock:
        ctx._open_apps_cache = ["Calculator"]
        ctx._open_apps_cache_time = time.monotonic()
        ctx._previous_action_result = {"verified": False, "verification_source": "psutil"}

    ok, details = executor._verify_step_outcome(step, "Launched")
    assert ok is False
    assert "Action verification failed" in details


# ── Test 8: Forced Worst-Case Asyncio Reentrancy Fixture ───────────────────────

@async_test
async def test_forced_worst_case_reentrancy_fixture():
    """
    Forces the worst-case asyncio interleaving:
    1. Coroutine A awaits _execute_tool().
    2. confirm.resolve(True) fires while Coroutine A is asleep.
    3. resume_plan() runs to completion on the event loop, driving the plan to COMPLETED.
    4. Coroutine A wakes up, detects gen != _execution_generation, and safely abandons execution.
    """
    abandoned = [False]

    async def mock_execute_tool(self_agent, step_call: StepCall):
        if step_call.args.get("action") == "delete":
            res = confirm.request(
                key="delete_file",
                title="Delete",
                detail="Delete dummy.txt",
                run=lambda: "File dummy.txt deleted.",
            )
            # Resolve immediately in background thread
            threading.Thread(target=lambda: confirm.resolve(True), daemon=True).start()

            # Deliberately delay Coroutine A resumption by 50ms so resume_plan finishes first
            await asyncio.sleep(0.05)
            return type("Resp", (), {"response": res})()

        return type("Resp", (), {"response": "OK"})()

    agent = type("MockAgent", (), {
        "_execute_tool": mock_execute_tool,
        "loop": asyncio.get_running_loop(),
    })()

    executor = PlanExecutor(agent=agent)

    steps = [
        PlanStep(step_id=1, tool="file_controller", action="list", parameters={"path": "."}, description="Step 1"),
        PlanStep(step_id=2, tool="file_controller", action="delete", parameters={"path": "dummy.txt"}, description="Step 2"),
        PlanStep(step_id=3, tool="file_controller", action="list", parameters={"path": "."}, description="Step 3"),
    ]
    plan = ExecutionPlan(plan_id="plan_forced_reentrancy", goal="Test Reentrancy", steps=steps)

    # Launch Coroutine A
    task_a = asyncio.create_task(executor.execute_plan(plan))
    await task_a

    # Must preserve COMPLETED state and exact step index
    assert plan.state == PlanState.COMPLETED
    assert plan.current_step_index == 3
    assert all(s.status == StepStatus.COMPLETED for s in plan.steps)
    assert all(s.verified is True for s in plan.steps)
    assert plan.steps[1].result == "File dummy.txt deleted."


# ── Test 9: Multi-Pause Index Consistency with Real Threading ─────────────────

@async_test
async def test_multi_pause_index_consistency_fixture():
    """
    Validates a 5-step plan with 2 separate confirmation steps (Steps 2 and 4)
    under real background concurrent threading with randomized jitter.
    """
    executed_steps = []

    async def mock_execute_tool(self_agent, step_call: StepCall):
        name = step_call.name
        action = step_call.args.get("action")
        executed_steps.append((name, action))

        if name == "file_controller" and action == "delete":
            res = confirm.request(
                key="delete_file",
                title="Delete File",
                detail="Delete dummy.txt",
                run=lambda: "File dummy.txt deleted successfully.",
            )
            await asyncio.sleep(random.uniform(0.0001, 0.001))
            return type("Resp", (), {"response": res})()

        elif name == "file_controller" and action == "organize":
            res = confirm.request(
                key="file_organize",
                title="Organize Files",
                detail="Organize mock files",
                run=lambda: "Organized 5 files into Archive.",
            )
            await asyncio.sleep(random.uniform(0.0001, 0.001))
            return type("Resp", (), {"response": res})()

        elif name == "open_app":
            with AgentContext.get_instance()._lock:
                AgentContext.get_instance()._previous_action_result = {
                    "verified": True,
                    "verification_source": "mock_test",
                    "result": "Opened notepad",
                }
            return type("Resp", (), {"response": f"Tool {name}:{action} success"})()

        return type("Resp", (), {"response": f"Tool {name}:{action} success"})()

    agent = type("MockAgent", (), {
        "_execute_tool": mock_execute_tool,
        "loop": asyncio.get_running_loop(),
    })()

    executor = PlanExecutor(agent=agent)

    steps = [
        PlanStep(step_id=1, tool="file_controller", action="list", parameters={"path": "."}, description="List A"),
        PlanStep(step_id=2, tool="file_controller", action="delete", parameters={"path": "dummy.txt"}, description="Delete Dummy"),
        PlanStep(step_id=3, tool="open_app", action="launch", parameters={"app_name": "notepad"}, description="Launch Notepad"),
        PlanStep(step_id=4, tool="file_controller", action="organize", parameters={"path": "."}, description="Organize Files"),
        PlanStep(step_id=5, tool="file_controller", action="list", parameters={"path": "."}, description="List B"),
    ]
    plan = ExecutionPlan(plan_id="plan_multi_fixture", goal="Multi-pause fixture", steps=steps)

    stop_resolver = threading.Event()
    resolved_keys = []

    def ui_resolver_thread():
        resolutions_done = 0
        while not stop_resolver.is_set() and resolutions_done < 2:
            time.sleep(0.0001)
            with confirm._lock:
                pending = confirm._pending
            if pending is not None:
                time.sleep(random.uniform(0.0001, 0.002))
                resolved_keys.append(pending.key)
                confirm.resolve(True)
                resolutions_done += 1

    resolver_t = threading.Thread(target=ui_resolver_thread, daemon=True)
    resolver_t.start()

    try:
        await executor.execute_plan(plan)

        start_wait = time.monotonic()
        while not plan.is_finished and (time.monotonic() - start_wait < 3.0):
            await asyncio.sleep(0.002)

        stop_resolver.set()
        resolver_t.join(timeout=1.0)

        assert plan.state == PlanState.COMPLETED
        assert plan.current_step_index == 5
        assert all(s.status == StepStatus.COMPLETED for s in plan.steps)
        assert all(s.verified is True for s in plan.steps)
        assert plan.steps[1].result == "File dummy.txt deleted successfully."
        assert plan.steps[3].result == "Organized 5 files into Archive."

        expected_steps = [
            ("file_controller", "list"),
            ("file_controller", "delete"),
            ("open_app", "launch"),
            ("file_controller", "organize"),
            ("file_controller", "list"),
        ]
        assert executed_steps == expected_steps
        assert resolved_keys == ["delete_file", "file_organize"]

    finally:
        stop_resolver.set()
        resolver_t.join(timeout=0.5)


if __name__ == "__main__":
    pytest.main(["-v", __file__])
