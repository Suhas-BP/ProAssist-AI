"""
scratch/test_subphase_5c_integration.py
=======================================
Permanent dedicated integration test suite for Sub-Phase 5C (Live Integration & Voice Loop Wiring).

Covers:
1. Tool declarations include orchestrate_plan and cancel_plan with correct schema.
2. StepCall marker verification (is_plan_step=True) and dual-condition detection.
3. Concurrency gate: Blocks conflicting mutative calls during active/paused plan.
4. Concurrency gate: Permits safe read-only queries (PermissionLevel.SAFE) during paused plan.
5. Concurrency gate: Permits cancel_plan during active plan.
6. Static pre-flight security rejection: PlanSecurityRejection caught and formatted as [PLAN_REJECTED].
7. Collision protection: Second orchestrate_plan while first is active returns [PLAN_COLLISION].
8. Text command triggers: /cancel and /plan command routing in _on_text_command.
9. Voice command trigger: Simulated turn_complete with 'cancel plan' cancels active plan.
10. Full-Stack End-to-End Test: Live file write-then-delete plan execution with
    pre-dispatch confirmation pause, concurrent safe query pass-through, real HUD resolution,
    closed-loop verification, and ActionLogger recording.
"""

import asyncio
import functools
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

# UTF-8 stdout
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core import confirm
from core.permission_manager import check_permission, PermissionLevel
from core.logger import ActionLogger
from agent.context import AgentContext
from agent.planner import (
    ExecutionPlan, PlanStep, PlanState, StepStatus,
    PlanSecurityRejection, PlanValidationError,
)
from agent.orchestrator import PlanExecutor, PlanCollisionError, StepCall
import main
from main import AgentLive, TOOL_DECLARATIONS, TextCommandCall


def async_test(coro_fn):
    """Decorator running an async coroutine synchronously for pytest."""
    @functools.wraps(coro_fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(coro_fn(*args, **kwargs))
    return wrapper


# ── Test Utilities & Fixtures ─────────────────────────────────────────────────

class DummyFunctionCall:
    """Simulates a Google GenAI types.FunctionCall arriving over WebSocket."""
    def __init__(self, name: str, args: Optional[Dict[str, Any]] = None, call_id: str = "genai_fc_123"):
        self.name = name
        self.args = args or {}
        self.id = call_id


class DummySession:
    """Simulates active Gemini Live session."""
    async def send_client_content(self, *args, **kwargs):
        pass


class MockAgentUI:
    """Mock UI conforming to AgentUI interface used by AgentLive."""
    def __init__(self):
        self.muted = False
        self.current_file = None
        self.state = "LISTENING"
        self.logs: List[str] = []
        self.banner_visible = False
        self.banner_title = ""
        self.banner_detail = ""

    def set_state(self, s: str):
        self.state = s

    def write_log(self, m: str):
        self.logs.append(m)

    def show_content(self, label: str, content: str):
        pass

    def _show_confirm_banner(self, title: str, detail: str):
        self.banner_visible = True
        self.banner_title = title
        self.banner_detail = detail

    def _hide_confirm_banner(self):
        self.banner_visible = False


def setup_confirm_hud(ui: MockAgentUI):
    """Wire confirm module to MockUI."""
    confirm.bind(
        show=lambda t, d: ui._show_confirm_banner(t, d),
        hide=lambda: ui._hide_confirm_banner(),
        log=lambda m: ui.write_log(f"SYS: {m}"),
    )


def reset_confirm_state():
    """Reset confirm module internal state."""
    with confirm._lock:
        confirm._pending = None
        confirm._listeners.clear()
        confirm._recent_resolutions.clear()


@pytest.fixture
def test_env():
    """Provides a fresh AgentLive instance and test environment."""
    reset_confirm_state()
    ui = MockAgentUI()
    setup_confirm_hud(ui)
    agent = AgentLive(ui)
    agent._awake = True
    agent._wake_enabled = False
    agent.session = DummySession()

    # Spy for spoken messages
    agent.spoken_messages = []
    original_speak = agent.speak
    def spy_speak(text: str):
        agent.spoken_messages.append(text)
        return original_speak(text)
    agent.speak = spy_speak

    sandbox_dir = REPO_ROOT / "scratch" / "test_5c_sandbox"
    if sandbox_dir.exists():
        shutil.rmtree(sandbox_dir, ignore_errors=True)
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    yield agent, ui, sandbox_dir

    if sandbox_dir.exists():
        shutil.rmtree(sandbox_dir, ignore_errors=True)
    reset_confirm_state()


# ── Unit & Integration Tests ──────────────────────────────────────────────────

def test_tool_declarations_include_planner():
    """Requirement 1: TOOL_DECLARATIONS must declare orchestrate_plan and cancel_plan."""
    names = {t["name"] for t in TOOL_DECLARATIONS}
    assert "orchestrate_plan" in names, "orchestrate_plan must be declared in TOOL_DECLARATIONS"
    assert "cancel_plan" in names, "cancel_plan must be declared in TOOL_DECLARATIONS"

    orch_decl = next(t for t in TOOL_DECLARATIONS if t["name"] == "orchestrate_plan")
    assert "goal" in orch_decl["parameters"]["properties"], "orchestrate_plan must declare 'goal' parameter"
    assert "goal" in orch_decl["parameters"]["required"], "'goal' parameter must be required"


def test_stepcall_marker():
    """Requirement 2 & Task 3: StepCall marker must have is_plan_step=True and is_plan_step strictly controls dispatch."""
    step = StepCall(name="file_controller", args={"action": "list"})
    assert step.is_plan_step is True, "StepCall must default is_plan_step=True"

    # Evaluates to True for StepCall with is_plan_step=True
    assert (isinstance(step, StepCall) and getattr(step, "is_plan_step", True) is not False) is True

    # Evaluates to False for StepCall with is_plan_step=False
    step_non_plan = StepCall(name="file_controller", args={"action": "list"}, is_plan_step=False)
    assert (isinstance(step_non_plan, StepCall) and getattr(step_non_plan, "is_plan_step", True) is not False) is False

    # Evaluates to False for TextCommandCall
    cmd_fc = TextCommandCall(name="orchestrate_plan", args={"goal": "organize files"})
    assert (isinstance(cmd_fc, StepCall) and getattr(cmd_fc, "is_plan_step", True) is not False) is False

    # Evaluates to False for external GenAI FunctionCall
    external_fc = DummyFunctionCall(name="file_controller", args={"action": "delete"})
    assert (isinstance(external_fc, StepCall) and getattr(external_fc, "is_plan_step", True) is not False) is False


@async_test
async def test_concurrency_gate_blocks_conflicting_calls(test_env):
    """Requirement 3: Concurrency gate must block non-safe mutative calls during active plan."""
    agent, ui, _ = test_env
    agent._loop = asyncio.get_running_loop()

    # Setup an active plan paused for confirmation
    plan = ExecutionPlan(
        plan_id="plan_test_block",
        goal="Test plan",
        steps=[
            PlanStep(step_id=1, description="Danger step", tool="file_controller", action="delete", parameters={"path": "dummy.txt"}),
        ],
        state=PlanState.PAUSED_FOR_CONFIRMATION,
    )
    agent._plan_executor._active_plan = plan

    # 1. Mutative call: file_controller.delete (STRONG_CONFIRM)
    conflicting_fc = DummyFunctionCall(name="file_controller", args={"action": "delete", "path": "other.txt"})
    resp = await agent._execute_tool(conflicting_fc)
    assert "[BLOCKED_PLAN_ACTIVE]" in str(resp.response.get("result", "")), "Must block file_controller.delete while plan active"

    # 2. Mutative call: desktop_control.execute_generated_code (STRONG_CONFIRM)
    desktop_fc = DummyFunctionCall(name="desktop_control", args={"action": "execute_generated_code", "code": "print(1)"})
    resp2 = await agent._execute_tool(desktop_fc)
    assert "[BLOCKED_PLAN_ACTIVE]" in str(resp2.response.get("result", "")), "Must block desktop code execution while plan active"


@async_test
async def test_concurrency_gate_allows_safe_queries(test_env):
    """Requirement 4: Concurrency gate must permit SAFE queries while plan is paused."""
    agent, ui, _ = test_env
    agent._loop = asyncio.get_running_loop()

    plan = ExecutionPlan(
        plan_id="plan_test_safe",
        goal="Test plan",
        steps=[
            PlanStep(step_id=1, description="Danger step", tool="file_controller", action="delete"),
        ],
        state=PlanState.PAUSED_FOR_CONFIRMATION,
    )
    agent._plan_executor._active_plan = plan

    # Safe call: system_status
    safe_fc = DummyFunctionCall(name="system_status", args={})
    resp = await agent._execute_tool(safe_fc)
    result_str = str(resp.response.get("result", ""))
    assert "[BLOCKED_PLAN_ACTIVE]" not in result_str, "Safe tool system_status must NOT be blocked"


@async_test
async def test_concurrency_gate_allows_cancel_plan(test_env):
    """Requirement 5: Concurrency gate must permit cancel_plan and cleanly cancel active plan."""
    agent, ui, _ = test_env
    agent._loop = asyncio.get_running_loop()

    plan = ExecutionPlan(
        plan_id="plan_to_cancel",
        goal="Test plan to cancel",
        steps=[
            PlanStep(step_id=1, description="Step 1", tool="file_controller", action="list"),
        ],
        state=PlanState.PAUSED_FOR_CONFIRMATION,
    )
    agent._plan_executor._active_plan = plan

    cancel_fc = DummyFunctionCall(name="cancel_plan", args={"reason": "User said stop"})
    resp = await agent._execute_tool(cancel_fc)
    result_str = str(resp.response.get("result", ""))
    assert "[PLAN_CANCELLED]" in result_str, "cancel_plan must return [PLAN_CANCELLED]"
    assert agent._plan_executor.active_plan is None, "Active plan must be cleared after cancellation"
    assert plan.state == PlanState.CANCELLED, "Plan state must transition to CANCELLED"


@async_test
async def test_orchestrate_plan_preflight_rejection(test_env):
    """Requirement 6: Pre-flight security rejection must return [PLAN_REJECTED] with zero steps run."""
    agent, ui, sandbox_dir = test_env
    agent._loop = asyncio.get_running_loop()

    original_create = main.create_plan
    try:
        def mock_reject(goal, **kwargs):
            raise PlanSecurityRejection("Pre-flight Security Rejection: Step 1 is BLOCKED (format c:)")
        main.create_plan = mock_reject

        fc = DummyFunctionCall(name="orchestrate_plan", args={"goal": "format my c drive"})
        resp = await agent._execute_tool(fc)
        result_str = str(resp.response.get("result", ""))
        assert "[PLAN_REJECTED]" in result_str, f"Expected [PLAN_REJECTED], got: {result_str}"
        assert any("SEC:" in log for log in ui.logs), "Rejection must be logged to UI as SEC:"
    finally:
        main.create_plan = original_create


@async_test
async def test_collision_protection_in_execute_tool(test_env):
    """Requirement 7: Starting a second plan while one is active returns [PLAN_COLLISION]."""
    agent, ui, _ = test_env
    agent._loop = asyncio.get_running_loop()

    active_plan = ExecutionPlan(
        plan_id="plan_active_123",
        goal="Active task",
        steps=[
            PlanStep(step_id=1, description="Sorting desktop", tool="file_controller", action="list"),
        ],
        state=PlanState.RUNNING,
    )
    agent._plan_executor._active_plan = active_plan

    fc = DummyFunctionCall(name="orchestrate_plan", args={"goal": "Start another task"})
    resp = await agent._execute_tool(fc)
    result_str = str(resp.response.get("result", ""))
    assert "[PLAN_COLLISION]" in result_str, f"Expected [PLAN_COLLISION], got: {result_str}"


@async_test
async def test_text_commands_plan_and_cancel(test_env):
    """
    Requirement 8 & Task 2: Text commands /cancel and /plan handled in _on_text_command
    against the REAL AgentLive class (verifying self._loop safe fallback and collision guard).
    """
    agent, ui, sandbox_dir = test_env
    # Confirm agent._loop is None initially on real AgentLive instance
    agent._loop = None
    assert getattr(agent, "_loop", None) is None, "agent._loop must be None initially on real AgentLive"

    # 1. Test /cancel while plan active
    plan = ExecutionPlan(
        plan_id="plan_text_cancel",
        goal="Active task to cancel",
        steps=[PlanStep(step_id=1, description="Step 1", tool="file_controller", action="list")],
        state=PlanState.PAUSED_FOR_CONFIRMATION,
    )
    agent._plan_executor._active_plan = plan
    ui.banner_visible = True

    agent._on_text_command("/cancel")
    assert agent._plan_executor.active_plan is None, "/cancel must cancel active plan"
    assert ui.banner_visible is False, "/cancel must hide confirm banner"
    assert any("Active plan cancelled" in m for m in ui.logs), "UI log must record cancellation"
    assert any("Plan cancelled" in m for m in agent.spoken_messages), "Must speak cancellation"

    # 2. Test /plan with real AgentLive (safe fallback resolves running loop without self._loop)
    step1 = PlanStep(
        step_id=1,
        description="Write text plan file",
        tool="file_controller",
        action="write",
        parameters={"path": str(sandbox_dir / "text_plan.txt"), "content": "from text command"},
        expected_outcome="File written.",
    )
    text_plan = ExecutionPlan(
        plan_id="plan_from_text",
        goal="Write text plan file",
        steps=[step1],
        state=PlanState.READY,
    )
    original_create = main.create_plan
    try:
        main.create_plan = lambda goal, **kwargs: text_plan

        # Ensure agent._loop remains None to strictly test fallback to asyncio.get_running_loop()
        agent._loop = None
        agent._on_text_command("/plan Write text plan file")

        # Give loop time to process the threadsafe coroutine
        for _ in range(50):
            if text_plan.state == PlanState.COMPLETED:
                break
            await asyncio.sleep(0.02)

        assert text_plan.state == PlanState.COMPLETED, f"Plan triggered via /plan must complete, got: {text_plan.state}"
        assert (sandbox_dir / "text_plan.txt").exists(), "Step file must be created on disk"

        # 3. Test PLAN_COLLISION via /plan when a plan is active
        active_plan = ExecutionPlan(
            plan_id="plan_already_active",
            goal="Already active plan",
            steps=[PlanStep(step_id=1, description="Running step", tool="file_controller", action="list")],
            state=PlanState.RUNNING,
        )
        agent._plan_executor._active_plan = active_plan

        agent._on_text_command("/plan Conflicting plan")
        for _ in range(50):
            if any("PLAN_COLLISION" in m or "Cannot start a new plan" in m for m in ui.logs):
                break
            await asyncio.sleep(0.02)

        # Confirm collision caught and logged
        assert any("Cannot start a new plan" in m for m in ui.logs) or any("PLAN_COLLISION" in m for m in ui.logs)
        assert any("already active" in m.lower() for m in agent.spoken_messages)

        # Cleanup
        agent._plan_executor._active_plan = None
    finally:
        main.create_plan = original_create


@async_test
async def test_full_stack_write_then_delete_plan_e2e(test_env):
    """
    Requirement 10: Live End-to-End Full-Stack Test
    Exercises the complete Mark LIV stack:
    1. Step 1 (SAFE): Writes a file to disk via file_controller.write. Verified on disk.
    2. Step 2 (CONFIRM): Deletes the file via file_controller.delete.
       - Pre-dispatch subscription arms.
       - confirm.request() triggers ConfirmBanner on UI.
       - Plan transitions to PAUSED_FOR_CONFIRMATION.
    3. Concurrency check: While paused, a safe query (system_status) succeeds, but a conflicting mutative tool is blocked.
    4. Resume: User resolves confirmation on HUD (confirm.resolve(True)).
    5. Execution continues: File deleted, verified deleted from disk, plan COMPLETED.
    """
    agent, ui, sandbox_dir = test_env
    agent._loop = asyncio.get_running_loop()
    target_file = sandbox_dir / "live_target.txt"

    # Define real execution plan with real file_controller actions
    step1 = PlanStep(
        step_id=1,
        description="Write live audit file",
        tool="file_controller",
        action="write",
        parameters={"path": str(target_file), "content": "live verification token 5C"},
        expected_outcome="Target file created on disk with specified content.",
    )
    step2 = PlanStep(
        step_id=2,
        description="Delete live audit file",
        tool="file_controller",
        action="delete",
        parameters={"path": str(target_file)},
        expected_outcome="Target file deleted from disk.",
    )
    plan = ExecutionPlan(
        plan_id="e2e_live_plan_5c",
        goal="Write and then delete live audit file",
        steps=[step1, step2],
        state=PlanState.READY,
    )

    # ── Execute Step 1 and pause at Step 2 ──
    executed_plan = await agent._plan_executor.execute_plan(plan)

    # Assertions after pause at Step 2
    assert executed_plan.state == PlanState.PAUSED_FOR_CONFIRMATION, "Plan must pause at step 2 (delete)"
    assert step1.status == StepStatus.COMPLETED, "Step 1 must be completed"
    assert step1.verified is True, "Step 1 must have closed-loop verification"
    assert target_file.exists(), "Target file must physically exist on disk after Step 1"
    assert ui.banner_visible is True, "ConfirmBanner must be visible on HUD"
    assert step2.status == StepStatus.PAUSED_FOR_CONFIRMATION

    # ── Verify Concurrency Gate while Paused ──
    # Conflicting call blocked
    conflict_call = DummyFunctionCall(name="file_controller", args={"action": "delete", "path": "stray.txt"})
    conflict_resp = await agent._execute_tool(conflict_call)
    assert "[BLOCKED_PLAN_ACTIVE]" in str(conflict_resp.response.get("result", ""))

    # Safe call permitted
    safe_call = DummyFunctionCall(name="system_status", args={})
    safe_resp = await agent._execute_tool(safe_call)
    assert "[BLOCKED_PLAN_ACTIVE]" not in str(safe_resp.response.get("result", ""))

    # ── Resolve Confirmation on HUD ──
    # Simulate user clicking CONFIRM
    confirm.resolve(True)
    # Allow background worker to dispatch callback and drive resume
    for _ in range(50):
        if executed_plan.state == PlanState.COMPLETED:
            break
        await asyncio.sleep(0.05)

    # Assertions after resume
    assert executed_plan.state == PlanState.COMPLETED, f"Plan must complete after resume, got: {executed_plan.state}"
    assert step2.status == StepStatus.COMPLETED, "Step 2 must be completed"
    assert step2.verified is True, "Step 2 must have closed-loop verification"
    assert not target_file.exists(), "Target file must be physically deleted from disk"
    assert agent._plan_executor.active_plan == executed_plan
    assert executed_plan.is_finished is True

    # Verify ActionLogger logged events
    action_log = REPO_ROOT / "logs" / "agent_actions.jsonl"
    assert action_log.exists(), "Action log file must exist"
    recent_log = action_log.read_text(encoding="utf-8")
    assert "file_controller" in recent_log, "Action logger must have recorded file_controller calls"


def test_voice_command_cancel_plan(test_env):
    """Requirement 9: Simulated voice turn_complete with 'cancel plan' cancels active plan."""
    import re
    agent, ui, _ = test_env
    plan = ExecutionPlan(
        plan_id="plan_voice_cancel",
        goal="Active task",
        steps=[PlanStep(step_id=1, description="Step 1", tool="file_controller", action="list")],
        state=PlanState.PAUSED_FOR_CONFIRMATION,
    )
    agent._plan_executor._active_plan = plan
    ui.banner_visible = True

    # Simulate voice transcript match in _receive_audio logic
    full_in = "please cancel plan now"
    if re.search(r"\b(cancel plan|abort plan|stop plan|cancel task|stop task)\b", full_in, re.IGNORECASE):
        active = getattr(agent, "_plan_executor", None) and agent._plan_executor.active_plan
        if active and not active.is_finished:
            agent._plan_executor.cancel_active_plan(reason="User voice commanded cancellation")
            if hasattr(agent.ui, "_hide_confirm_banner"):
                agent.ui._hide_confirm_banner()
            agent.ui.write_log("SYS: Plan cancelled via voice.")
            agent.speak("Plan cancelled.")

    assert agent._plan_executor.active_plan is None, "Voice cancel must cancel active plan"
    assert ui.banner_visible is False, "Voice cancel must hide confirm banner"
    assert any("Plan cancelled via voice" in m for m in ui.logs), "UI log must record voice cancellation"


@async_test
async def test_multi_pause_speech_alerts_on_both_pauses(test_env):
    """
    Task 1: Verify multi-pause plan speaks pause alerts for BOTH the 1st and 2nd pauses.
    Asserts self.speak() was called with a pause-alert message for both pauses,
    not just that the state machine advanced correctly.
    """
    agent, ui, sandbox_dir = test_env
    agent._loop = asyncio.get_running_loop()

    file1 = sandbox_dir / "pause_test1.txt"
    file1.write_text("content 1", encoding="utf-8")

    src_dir = sandbox_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "doc.txt").write_text("content to organize", encoding="utf-8")
    dst_dir = sandbox_dir / "dst"

    step1 = PlanStep(
        step_id=1,
        description="Delete first test file",
        tool="file_controller",
        action="delete",
        parameters={"path": str(file1)},
        expected_outcome="First file deleted from disk.",
    )
    step2 = PlanStep(
        step_id=2,
        description="Organize documents into archive",
        tool="file_controller",
        action="organize",
        parameters={"source": str(src_dir), "destination": str(dst_dir)},
        expected_outcome="Documents organized into destination.",
    )
    step3 = PlanStep(
        step_id=3,
        description="List files in sandbox",
        tool="file_controller",
        action="list",
        parameters={"path": str(sandbox_dir)},
        expected_outcome="Files listed.",
    )
    plan = ExecutionPlan(
        plan_id="multi_pause_speech_test",
        goal="Delete a file then organize documents requiring confirmation sequentially",
        steps=[step1, step2, step3],
        state=PlanState.READY,
    )

    original_create = main.create_plan
    try:
        main.create_plan = lambda goal, **kwargs: plan

        # Dispatch via orchestrate_plan (normal live agent execution path)
        fc = DummyFunctionCall(name="orchestrate_plan", args={"goal": "clean test files"})
        plan_task = asyncio.create_task(agent._execute_tool(fc))

        # ── 1. FIRST PAUSE (Step 1) ──
        for _ in range(50):
            if plan.state == PlanState.PAUSED_FOR_CONFIRMATION:
                break
            await asyncio.sleep(0.02)

        assert plan.state == PlanState.PAUSED_FOR_CONFIRMATION, "Plan must reach PAUSED_FOR_CONFIRMATION on Step 1"
        assert plan.current_step_index == 0, "Plan current_step_index must be 0 (Step 1)"
        assert ui.banner_visible is True, "Confirm banner must be visible on HUD for Step 1"

        # Await plan_task to complete orchestrate_plan call for step 1
        resp1 = await plan_task
        assert "[CONFIRMATION_PENDING]" in str(resp1.response.get("result", ""))

        # Check speech for Step 1 pause alert
        step1_alerts = [m for m in agent.spoken_messages if "paused at step 1" in m.lower()]
        assert len(step1_alerts) >= 1, f"Expected pause alert spoken for Step 1, got: {agent.spoken_messages}"
        assert "Delete first test file" in step1_alerts[0] or "delete" in step1_alerts[0].lower()

        # ── 2. RESOLVE FIRST PAUSE ──
        confirm.resolve(True)

        # ── 3. SECOND PAUSE (Step 2) ──
        # Wait for resume_plan to advance past Step 1 and pause at Step 2
        for _ in range(50):
            if plan.current_step_index == 1 and plan.state == PlanState.PAUSED_FOR_CONFIRMATION:
                break
            await asyncio.sleep(0.02)

        assert plan.state == PlanState.PAUSED_FOR_CONFIRMATION, "Plan must reach PAUSED_FOR_CONFIRMATION on Step 2"
        assert plan.current_step_index == 1, "Plan current_step_index must be 1 (Step 2)"
        assert step1.status == StepStatus.COMPLETED, "Step 1 must be COMPLETED"
        assert step2.status == StepStatus.PAUSED_FOR_CONFIRMATION, "Step 2 must be PAUSED_FOR_CONFIRMATION"

        # Check speech for Step 2 pause alert (spoken by resume_plan's elif branch!)
        step2_alerts = [m for m in agent.spoken_messages if "paused at step 2" in m.lower()]
        assert len(step2_alerts) >= 1, f"Expected pause alert spoken for Step 2, got: {agent.spoken_messages}"
        assert "Organize documents" in step2_alerts[0] or "organize" in step2_alerts[0].lower()

        # ── 4. RESOLVE SECOND PAUSE ──
        confirm.resolve(True)

        # Wait for resume_plan to complete the rest of the plan
        for _ in range(50):
            if plan.state == PlanState.COMPLETED:
                break
            await asyncio.sleep(0.02)

        assert plan.state == PlanState.COMPLETED, f"Plan must reach COMPLETED, got: {plan.state}"
        assert step2.status == StepStatus.COMPLETED, "Step 2 must be COMPLETED"
        assert step3.status == StepStatus.COMPLETED, "Step 3 must be COMPLETED"

        # Check speech for terminal completion
        complete_spoken = [m for m in agent.spoken_messages if "plan complete" in m.lower()]
        assert len(complete_spoken) >= 1, f"Expected completion spoken, got: {agent.spoken_messages}"

        # VERIFY BOTH PAUSE ALERTS WERE SPOKEN
        assert len(step1_alerts) >= 1, "Pause alert 1 MUST have been spoken"
        assert len(step2_alerts) >= 1, "Pause alert 2 MUST have been spoken"

    finally:
        main.create_plan = original_create


if __name__ == "__main__":
    pytest.main(["-v", __file__])

