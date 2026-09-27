"""
scratch/test_multi_pause_race.py
================================
Validates multi-pause index consistency under REAL concurrent threading
with randomized timing jitter across 100 iterations.

Tests:
1. 5-step plan with 2 separate confirmation steps (Step 2 and Step 4).
2. Background resolver thread calling actual confirm.resolve(True) with random jitter.
3. Pre-dispatch subscription handles both resolutions cleanly.
4. Real result strings threaded through to step.result.
5. Exact index progression: 0 -> 1 -> 2 -> 3 -> 4 -> 5 with zero off-by-one or double-increments.
"""

import asyncio
import os
import random
import sys
import threading
import time
from dataclasses import dataclass
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


class PlanExecutor:
    def __init__(self, agent: Any):
        self._agent = agent
        self._active_plan: Optional[ExecutionPlan] = None
        self._active_unregister_fn: Optional[Callable[[], None]] = None
        self._execution_generation: int = 0

    @property
    def active_plan(self) -> Optional[ExecutionPlan]:
        return self._active_plan

    def _verify_step_outcome(self, step: PlanStep, raw_result: str) -> tuple[bool, str]:
        ctx = AgentContext.get_instance()
        prev = ctx.previous_action_result or {}

        if prev.get("verified") is False:
            return False, f"Action verification failed ({prev.get('verification_source', 'driver')})"

        failure_prefixes = (
            "[FAILURE:",
            "[BLOCKED]",
            "Tool '",
            "Unknown tool:",
            "Error:",
            "Could not ",
        )
        if any(str(raw_result).startswith(p) for p in failure_prefixes):
            return False, str(raw_result)

        if step.tool == "file_controller" and step.action in ("write", "create", "download"):
            target_path = step.parameters.get("path") or step.parameters.get("file_path")
            if target_path and not Path(os.path.expanduser(target_path)).exists():
                return False, f"Target file '{target_path}' does not exist on disk."

        if step.tool == "open_app":
            app_target = step.parameters.get("app_name", "").lower()
            active_app = (ctx.current_active_application or "").lower()
            open_windows = [w.lower() for w in ctx.open_applications]

            if app_target and (app_target in active_app or any(app_target in w for w in open_windows)):
                return True, f"Application '{app_target}' window detected."
            elif prev.get("verified") is True:
                return True, f"Application '{app_target}' process verified."
            else:
                return False, f"Application '{app_target}' not found in active windows or processes."

        return True, "Step output verified successfully."

    def _handle_failure(self, step: PlanStep, error_message: str) -> None:
        step.status = StepStatus.FAILED
        step.error = error_message
        if self._active_plan:
            self._active_plan.state = PlanState.FAILED
            self._active_plan.error = f"Step {step.step_id} failed: {error_message}"
            self._active_plan.updated_at = time.time()
        if self._active_unregister_fn:
            try:
                self._active_unregister_fn()
            except Exception:
                pass
            self._active_unregister_fn = None

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
                raise PlanCollisionError(
                    f"Plan collision: Cannot start plan '{plan.plan_id}' while plan "
                    f"'{self._active_plan.plan_id}' is active in state '{self._active_plan.state.value}'."
                )

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

            # Increment and snapshot generation for this step dispatch
            self._execution_generation += 1
            gen = self._execution_generation

            step.status = StepStatus.RUNNING
            plan.updated_at = time.time()

            # Pre-flight permission check
            perm = check_permission(step.tool, step.action or "", step.parameters)
            step.permission_level = perm.level.value
            step.permission_key = perm.key

            if perm.level == PermissionLevel.BLOCKED:
                self._handle_failure(step, f"Security Policy BLOCKED: {perm.reason}")
                return plan

            # Pre-dispatch subscription if confirmation required
            if perm.level in (PermissionLevel.CONFIRM, PermissionLevel.STRONG_CONFIRM):
                self._active_unregister_fn = confirm.add_resolution_listener(
                    callback=self._make_resolution_handler(plan.plan_id, step.step_id),
                    target_key=perm.key,
                    oneshot=True,
                )

            # Dispatch tool
            step_call = StepCall(name=step.tool, args=dict(step.parameters, action=step.action))
            try:
                fn_resp = await self._agent._execute_tool(step_call)
                raw_result = fn_resp.response if hasattr(fn_resp, "response") else str(fn_resp)
            except Exception as exc:
                if gen != self._execution_generation:
                    return plan
                self._handle_failure(step, f"Tool execution exception: {exc}")
                return plan

            # ── REENTRANCY GUARD CHECK POST-AWAIT ──────────────────────
            # If another driver (e.g. resume_plan) superseded this coroutine while it was awaiting,
            # abandon execution immediately to prevent stale mutation or double-increment.
            if gen != self._execution_generation:
                return plan

            if "[CONFIRMATION_PENDING]" in str(raw_result):
                step.status = StepStatus.PAUSED_FOR_CONFIRMATION
                plan.state = PlanState.PAUSED_FOR_CONFIRMATION
                plan.updated_at = time.time()
                return plan

            # Verify outcome
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
            plan.error = f"Step {step.step_id} cancelled: {step.result}"
            plan.updated_at = time.time()
            return

        raw_result = result or "Done."
        step.result = raw_result

        # Real verification on resumed step
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

        await self.execute_plan(plan)


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


async def run_single_multi_pause_iteration(iter_num: int) -> tuple[bool, str]:
    reset_confirm_state()

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
            # Add small jitter during dispatch to test pre-dispatch vs in-flight resolve races
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

    agent_mock = type("MockAgent", (), {
        "_execute_tool": mock_execute_tool,
        "loop": asyncio.get_running_loop(),
    })()

    executor = PlanExecutor(agent=agent_mock)

    steps = [
        PlanStep(step_id=1, tool="file_controller", action="list", parameters={"path": "."}, description="List A"),
        PlanStep(step_id=2, tool="file_controller", action="delete", parameters={"path": "dummy.txt"}, description="Delete Dummy"),
        PlanStep(step_id=3, tool="open_app", action="launch", parameters={"app_name": "notepad"}, description="Launch Notepad"),
        PlanStep(step_id=4, tool="file_controller", action="organize", parameters={"path": "."}, description="Organize Files"),
        PlanStep(step_id=5, tool="file_controller", action="list", parameters={"path": "."}, description="List B"),
    ]
    plan = ExecutionPlan(plan_id=f"plan_iter_{iter_num}", goal="Multi-pause test", steps=steps)

    # Spawn real background thread that monitors confirm._pending and calls confirm.resolve(True)
    stop_resolver = threading.Event()
    resolved_keys = []

    def ui_resolver_thread():
        resolutions_done = 0
        while not stop_resolver.is_set() and resolutions_done < 2:
            time.sleep(0.0001)
            with confirm._lock:
                pending = confirm._pending
            if pending is not None:
                # Add randomized jitter before pressing Confirm (mimicking realistic user/HUD latency)
                time.sleep(random.uniform(0.0001, 0.002))
                resolved_keys.append(pending.key)
                confirm.resolve(True)
                resolutions_done += 1

    resolver_t = threading.Thread(target=ui_resolver_thread, daemon=True)
    resolver_t.start()

    try:
        # Start initial plan execution
        p = await executor.execute_plan(plan)

        # Wait until plan reaches a terminal state (COMPLETED or FAILED) or timeout
        start_wait = time.monotonic()
        while not plan.is_finished and (time.monotonic() - start_wait < 3.0):
            await asyncio.sleep(0.002)

        stop_resolver.set()
        resolver_t.join(timeout=1.0)

        # Invariant checks:
        if plan.state != PlanState.COMPLETED:
            return False, f"Plan state is {plan.state.value}, expected COMPLETED. Error: {plan.error}"

        if plan.current_step_index != 5:
            return False, f"current_step_index is {plan.current_step_index}, expected 5"

        if not all(s.status == StepStatus.COMPLETED for s in plan.steps):
            statuses = [s.status.value for s in plan.steps]
            return False, f"Step statuses: {statuses}"

        if not all(s.verified is True for s in plan.steps):
            return False, "Not all steps verified=True"

        # Check real result threading
        if plan.steps[1].result != "File dummy.txt deleted successfully.":
            return False, f"Step 2 result not real: {plan.steps[1].result}"

        if plan.steps[3].result != "Organized 5 files into Archive.":
            return False, f"Step 4 result not real: {plan.steps[3].result}"

        # Check exact dispatch count and order
        expected_steps = [
            ("file_controller", "list"),
            ("file_controller", "delete"),
            ("open_app", "launch"),
            ("file_controller", "organize"),
            ("file_controller", "list"),
        ]
        if executed_steps != expected_steps:
            return False, f"Executed steps {executed_steps} != {expected_steps}"

        if resolved_keys != ["delete_file", "file_organize"]:
            return False, f"Resolved keys {resolved_keys} != ['delete_file', 'file_organize']"

        return True, "OK"

    finally:
        stop_resolver.set()
        resolver_t.join(timeout=0.5)


async def main():
    iterations = 100
    print("=" * 70)
    print(f"RUNNING REAL-THREADED MULTI-PAUSE RACE TEST ({iterations} iterations)")
    print("=" * 70)

    setup_confirm_hud()

    passed = 0
    failed = 0
    failures = []

    start_time = time.monotonic()

    for i in range(1, iterations + 1):
        ok, msg = await run_single_multi_pause_iteration(i)
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append(f"Iteration {i}: {msg}")

        if i % 20 == 0:
            print(f"  -> Progress: {i}/{iterations} completed ({passed} passed, {failed} failed)...")

    duration = time.monotonic() - start_time
    pass_rate = (passed / iterations) * 100.0

    print("-" * 70)
    print(f"RESULTS ACROSS {iterations} REAL THREADED MULTI-PAUSE ITERATIONS:")
    print(f"  Total Iterations:   {iterations}")
    print(f"  Passed:             {passed}")
    print(f"  Failed:             {failed}")
    print(f"  Pass Rate:          {pass_rate:.2f}%")
    print(f"  Duration:           {duration:.3f}s (avg {duration/iterations*1000:.2f}ms/iter)")
    print("-" * 70)

    if failures:
        print("FAILURES:")
        for f in failures[:10]:
            print(f"  {f}")
        sys.exit(1)
    else:
        print("ALL REAL THREADED MULTI-PAUSE ITERATIONS PASSED WITH 100% SUCCESS!")


if __name__ == "__main__":
    asyncio.run(main())
