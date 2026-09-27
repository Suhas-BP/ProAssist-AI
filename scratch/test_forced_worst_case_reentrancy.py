"""
scratch/test_forced_worst_case_reentrancy.py
============================================
Forces the worst-case asyncio interleaving:
1. Coroutine A calls await _execute_tool() for Step 2.
2. Inside _execute_tool, confirm.request() is posted, confirm.resolve(True) is triggered.
3. _execute_tool injects an artificial sleep (e.g. 50ms) so Coroutine A remains suspended.
4. Coroutine B (resume_plan) executes on the event loop while Coroutine A is asleep.
5. Coroutine B completes Step 2, executes Step 3, Step 4, Step 5, and marks the plan COMPLETED.
6. Coroutine A finally wakes up.
7. We verify:
   - WITHOUT the guard: Coroutine A corrupts state (re-pauses plan, double-increments, or loops).
   - WITH the generation guard: Coroutine A detects gen != current_gen and cleanly abandons execution, preserving COMPLETED state.
"""

import asyncio
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

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


class PlanCollisionError(RuntimeError):
    pass


class StepCall:
    def __init__(self, name: str, args: dict[str, Any]):
        self.name = name
        self.args = args


class GuardedPlanExecutor:
    """PlanExecutor equipped with monotonic execution generation reentrancy guard."""

    def __init__(self, agent: Any):
        self._agent = agent
        self._active_plan: Optional[ExecutionPlan] = None
        self._active_unregister_fn: Optional[Callable[[], None]] = None
        self._execution_generation: int = 0
        self.coroutine_a_abandoned: bool = False

    @property
    def active_plan(self) -> Optional[ExecutionPlan]:
        return self._active_plan

    def _verify_step_outcome(self, step: PlanStep, raw_result: str) -> tuple[bool, str]:
        failure_prefixes = ("[FAILURE:", "[BLOCKED]", "Error:")
        if any(str(raw_result).startswith(p) for p in failure_prefixes):
            return False, str(raw_result)
        return True, "Verified"

    def _handle_failure(self, step: PlanStep, error_message: str) -> None:
        step.status = StepStatus.FAILED
        step.error = error_message
        if self._active_plan:
            self._active_plan.state = PlanState.FAILED
            self._active_plan.error = error_message

    def _make_resolution_handler(self, plan_id: str, step_id: int):
        def on_resolved(key: str, accepted: bool, result: Optional[str] = None):
            loop = self._agent.loop if hasattr(self._agent, "loop") else asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(
                self.resume_plan(plan_id, step_id, accepted, result),
                loop,
            )
        return on_resolved

    async def execute_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        if self._active_plan is not None and self._active_plan.plan_id != plan.plan_id:
            if not self._active_plan.is_finished:
                raise PlanCollisionError("Plan collision")

        self._active_plan = plan
        if plan.state == PlanState.READY:
            plan.state = PlanState.RUNNING
            plan.updated_at = time.time()

        while plan.current_step_index < len(plan.steps):
            step = plan.current_step
            if not step:
                break

            if step.status == StepStatus.COMPLETED:
                plan.current_step_index += 1
                continue

            # ── GENERATION GUARD: Capture monotonic generation token ──
            self._execution_generation += 1
            gen = self._execution_generation

            step.status = StepStatus.RUNNING
            plan.updated_at = time.time()

            perm = check_permission(step.tool, step.action or "", step.parameters)
            step.permission_level = perm.level.value
            step.permission_key = perm.key

            if perm.level in (PermissionLevel.CONFIRM, PermissionLevel.STRONG_CONFIRM):
                self._active_unregister_fn = confirm.add_resolution_listener(
                    callback=self._make_resolution_handler(plan.plan_id, step.step_id),
                    target_key=perm.key,
                    oneshot=True,
                )

            # SUSPENSION POINT: Await tool execution
            step_call = StepCall(name=step.tool, args=dict(step.parameters, action=step.action))
            try:
                fn_resp = await self._agent._execute_tool(step_call)
                raw_result = fn_resp.response if hasattr(fn_resp, "response") else str(fn_resp)
            except Exception as exc:
                if gen != self._execution_generation:
                    self.coroutine_a_abandoned = True
                    return plan
                self._handle_failure(step, f"Tool execution exception: {exc}")
                return plan

            # ── REENTRANCY GUARD CHECK POST-AWAIT ──────────────────────
            # If another driver (e.g. resume_plan) superseded this coroutine while it was awaiting,
            # abandon execution immediately to prevent stale mutation or double-increment.
            if gen != self._execution_generation:
                self.coroutine_a_abandoned = True
                return plan

            if "[CONFIRMATION_PENDING]" in str(raw_result):
                step.status = StepStatus.PAUSED_FOR_CONFIRMATION
                plan.state = PlanState.PAUSED_FOR_CONFIRMATION
                plan.updated_at = time.time()
                return plan

            verified, verify_details = self._verify_step_outcome(step, raw_result)
            if not verified:
                self._handle_failure(step, f"Verification failed: {verify_details}")
                return plan

            step.status = StepStatus.COMPLETED
            step.result = raw_result
            step.verified = True
            plan.current_step_index += 1
            plan.updated_at = time.time()

        if plan.current_step_index >= len(plan.steps) and plan.state != PlanState.FAILED:
            plan.state = PlanState.COMPLETED
            plan.updated_at = time.time()

        return plan

    async def resume_plan(
        self,
        plan_id: str,
        step_id: int,
        accepted: bool,
        result: Optional[str] = None,
    ) -> None:
        if not self._active_plan or self._active_plan.plan_id != plan_id:
            return
        plan = self._active_plan
        step = plan.current_step

        if not step or step.step_id != step_id:
            return

        self._active_unregister_fn = None

        # ── GENERATION GUARD: Invalidate any suspended/stale execute_plan coroutines ──
        self._execution_generation += 1

        if not accepted:
            step.status = StepStatus.CANCELLED
            step.result = result or "User cancelled confirmation."
            step.error = step.result
            plan.state = PlanState.CANCELLED
            return

        raw_result = result or "Done."
        step.result = raw_result

        verified, verify_details = self._verify_step_outcome(step, raw_result)
        if not verified:
            self._handle_failure(step, f"Resumed step verification failed: {verify_details}")
            return

        step.status = StepStatus.COMPLETED
        step.verified = True
        step.error = None
        plan.current_step_index += 1
        plan.state = PlanState.RUNNING
        plan.updated_at = time.time()

        # Drive plan forward
        await self.execute_plan(plan)


class UnguardedPlanExecutor(GuardedPlanExecutor):
    """Identical executor but WITHOUT the generation guard post-await check."""

    async def execute_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        if self._active_plan is not None and self._active_plan.plan_id != plan.plan_id:
            if not self._active_plan.is_finished:
                raise PlanCollisionError("Plan collision")

        self._active_plan = plan
        if plan.state == PlanState.READY:
            plan.state = PlanState.RUNNING
            plan.updated_at = time.time()

        while plan.current_step_index < len(plan.steps):
            step = plan.current_step
            if not step:
                break

            if step.status == StepStatus.COMPLETED:
                plan.current_step_index += 1
                continue

            step.status = StepStatus.RUNNING
            plan.updated_at = time.time()

            perm = check_permission(step.tool, step.action or "", step.parameters)
            step.permission_level = perm.level.value
            step.permission_key = perm.key

            if perm.level in (PermissionLevel.CONFIRM, PermissionLevel.STRONG_CONFIRM):
                self._active_unregister_fn = confirm.add_resolution_listener(
                    callback=self._make_resolution_handler(plan.plan_id, step.step_id),
                    target_key=perm.key,
                    oneshot=True,
                )

            # SUSPENSION POINT: Await tool execution
            step_call = StepCall(name=step.tool, args=dict(step.parameters, action=step.action))
            try:
                fn_resp = await self._agent._execute_tool(step_call)
                raw_result = fn_resp.response if hasattr(fn_resp, "response") else str(fn_resp)
            except Exception as exc:
                self._handle_failure(step, f"Tool execution exception: {exc}")
                return plan

            # NO GUARD HERE! Proceeds blindly even if superseded!
            if "[CONFIRMATION_PENDING]" in str(raw_result):
                step.status = StepStatus.PAUSED_FOR_CONFIRMATION
                plan.state = PlanState.PAUSED_FOR_CONFIRMATION
                plan.updated_at = time.time()
                return plan

            verified, verify_details = self._verify_step_outcome(step, raw_result)
            if not verified:
                self._handle_failure(step, f"Verification failed: {verify_details}")
                return plan

            step.status = StepStatus.COMPLETED
            step.result = raw_result
            step.verified = True
            plan.current_step_index += 1
            plan.updated_at = time.time()

        if plan.current_step_index >= len(plan.steps) and plan.state != PlanState.FAILED:
            plan.state = PlanState.COMPLETED
            plan.updated_at = time.time()

        return plan


def setup_confirm_hud():
    confirm.bind(
        show=lambda title, detail: None,
        hide=lambda: None,
        log=lambda msg: None,
    )


def reset_confirm_state():
    with confirm._lock:
        confirm._pending = None
        confirm._listeners.clear()
        confirm._recent_resolutions.clear()


async def test_forced_interleaving_comparison():
    print("=" * 70)
    print("RUNNING FORCED WORST-CASE ASYNCIO INTERLEAVING TEST")
    print("=" * 70)

    setup_confirm_hud()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. RUN WITH UNGUARDED EXECUTOR TO DEMONSTRATE THE BUG
    # ─────────────────────────────────────────────────────────────────────────
    print("\n--- 1. Testing UNGUARDED Executor Under Forced Interleaving ---")
    reset_confirm_state()

    async def mock_tool_unguarded(self_agent, step_call):
        name = step_call.name
        action = step_call.args.get("action")

        if name == "file_controller" and action == "delete":
            # Post confirmation
            res = confirm.request(
                key="delete_file",
                title="Delete",
                detail="Delete dummy.txt",
                run=lambda: "File dummy.txt deleted.",
            )
            # Resolve immediately in background thread
            threading.Thread(target=lambda: confirm.resolve(True), daemon=True).start()

            # DELIBERATELY DELAY COROUTINE A RESUMPTION by 60ms!
            # This allows resume_plan to run to completion first!
            await asyncio.sleep(0.06)
            return type("Resp", (), {"response": res})()

        return type("Resp", (), {"response": f"Tool {name}:{action} OK"})()

    agent_unguarded = type("MockAgent", (), {
        "_execute_tool": mock_tool_unguarded,
        "loop": asyncio.get_running_loop(),
    })()

    executor_unguarded = UnguardedPlanExecutor(agent=agent_unguarded)

    steps_unguarded = [
        PlanStep(step_id=1, tool="file_controller", action="list", parameters={"path": "."}, description="Step 1"),
        PlanStep(step_id=2, tool="file_controller", action="delete", parameters={"path": "dummy.txt"}, description="Step 2"),
        PlanStep(step_id=3, tool="file_controller", action="list", parameters={"path": "."}, description="Step 3"),
    ]
    plan_unguarded = ExecutionPlan(plan_id="plan_ung", goal="Test Unguarded", steps=steps_unguarded)

    # Launch Coroutine A
    task_a = asyncio.create_task(executor_unguarded.execute_plan(plan_unguarded))
    await task_a

    print(f"  Unguarded Plan final state: {plan_unguarded.state.value}")
    print(f"  Unguarded current_step_index: {plan_unguarded.current_step_index}")
    if plan_unguarded.state == PlanState.PAUSED_FOR_CONFIRMATION:
        print("  -> BUG PROVEN: Coroutine A woke up and OVERWROTE the completed plan back to PAUSED_FOR_CONFIRMATION!")
    elif plan_unguarded.current_step_index != 3:
        print(f"  -> BUG PROVEN: Coroutine A corrupted step index: {plan_unguarded.current_step_index} != 3")

    # ─────────────────────────────────────────────────────────────────────────
    # 2. RUN WITH GUARDED EXECUTOR TO PROVE THE FIX
    # ─────────────────────────────────────────────────────────────────────────
    print("\n--- 2. Testing GUARDED Executor Under Forced Interleaving ---")
    reset_confirm_state()

    async def mock_tool_guarded(self_agent, step_call):
        name = step_call.name
        action = step_call.args.get("action")

        if name == "file_controller" and action == "delete":
            res = confirm.request(
                key="delete_file",
                title="Delete",
                detail="Delete dummy.txt",
                run=lambda: "File dummy.txt deleted.",
            )
            # Resolve immediately in background thread
            threading.Thread(target=lambda: confirm.resolve(True), daemon=True).start()

            # DELIBERATELY DELAY COROUTINE A RESUMPTION by 60ms!
            # resume_plan will finish advancing the plan completely while Coroutine A sleeps.
            await asyncio.sleep(0.06)
            return type("Resp", (), {"response": res})()

        return type("Resp", (), {"response": f"Tool {name}:{action} OK"})()

    agent_guarded = type("MockAgent", (), {
        "_execute_tool": mock_tool_guarded,
        "loop": asyncio.get_running_loop(),
    })()

    executor_guarded = GuardedPlanExecutor(agent=agent_guarded)

    steps_guarded = [
        PlanStep(step_id=1, tool="file_controller", action="list", parameters={"path": "."}, description="Step 1"),
        PlanStep(step_id=2, tool="file_controller", action="delete", parameters={"path": "dummy.txt"}, description="Step 2"),
        PlanStep(step_id=3, tool="file_controller", action="list", parameters={"path": "."}, description="Step 3"),
    ]
    plan_guarded = ExecutionPlan(plan_id="plan_grd", goal="Test Guarded", steps=steps_guarded)

    # Launch Coroutine A
    task_a = asyncio.create_task(executor_guarded.execute_plan(plan_guarded))
    await task_a

    print(f"  Guarded Plan final state:     {plan_guarded.state.value}")
    print(f"  Guarded current_step_index:   {plan_guarded.current_step_index}")
    print(f"  Coroutine A abandoned flag:   {executor_guarded.coroutine_a_abandoned}")
    print(f"  All steps completed:          {all(s.status == StepStatus.COMPLETED for s in plan_guarded.steps)}")
    print(f"  All steps verified:           {all(s.verified is True for s in plan_guarded.steps)}")

    assert plan_guarded.state == PlanState.COMPLETED, f"Expected COMPLETED, got {plan_guarded.state.value}"
    assert plan_guarded.current_step_index == 3, f"Expected 3, got {plan_guarded.current_step_index}"
    assert executor_guarded.coroutine_a_abandoned is True, "Expected Coroutine A to abandon execution upon waking"
    assert all(s.status == StepStatus.COMPLETED for s in plan_guarded.steps)
    assert all(s.verified is True for s in plan_guarded.steps)
    assert plan_guarded.steps[1].result == "File dummy.txt deleted."

    print("\n" + "=" * 70)
    print("FORCED INTERLEAVING TEST PASSED WITH 100% SUCCESS!")
    print("The generation guard provably prevented re-entrancy corruption!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_forced_interleaving_comparison())
