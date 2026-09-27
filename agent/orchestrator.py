"""
agent/orchestrator.py — Multi-Step Plan Execution Engine & State Machine.

Part of Item 5 (Multi-Step Planner / Orchestrator) for Mark LIV.
Coordinates sequential execution of decomposed ExecutionPlan steps, integrating:
1. Closed-loop verification and runtime state via AgentContext (Item 4).
2. Action and security logging via core.logger / ActionLogger (Item 1).
3. Pre-flight and pre-dispatch permission gating via core.permission_manager (Item 4 audit).
4. Non-blocking confirmation pausing and resume via core.confirm (Phase 1-2).
5. Fencing token re-entrancy protection across asynchronous suspension boundaries.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from core import confirm
from core.permission_manager import check_permission, PermissionLevel
from agent.planner import ExecutionPlan, PlanStep, PlanState, StepStatus
from agent.context import AgentContext


class PlanCollisionError(RuntimeError):
    """Raised when an attempt is made to start a plan while another plan is active."""
    pass


@dataclass
class StepCall:
    """Adaptor bridging PlanStep execution to AgentLive._execute_tool(fc)."""
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    id: str = "step_call"
    is_plan_step: bool = True


class PlanExecutor:
    """
    Asynchronous execution engine for ExecutionPlan instances.

    Guarantees:
    - Zero Parallel Dispatch Paths: All tool calls route through agent._execute_tool().
    - Plan-Level Collision Protection: Rejects execution of a new plan while one is RUNNING or PAUSED.
    - Pre-Dispatch Subscription: Registers confirmation listeners using perm.key BEFORE tool dispatch.
    - Closed-Loop Verification: Every step (both normal and resumed) is verified before completion.
    - Monotonic Fencing Token Guard: Re-entrancy protection ensures only one active driver mutates plan state.
    - Report-and-Stop Policy: On any security block, execution failure, or verification failure, halts cleanly.
    """

    def __init__(self, agent: Any):
        self._agent = agent
        self._active_plan: Optional[ExecutionPlan] = None
        self._active_unregister_fn: Optional[Callable[[], None]] = None
        self._execution_generation: int = 0

    @property
    def active_plan(self) -> Optional[ExecutionPlan]:
        """Returns the currently active ExecutionPlan, if any."""
        return self._active_plan

    @property
    def execution_generation(self) -> int:
        """Returns the current monotonic execution generation counter."""
        return self._execution_generation

    # ── Closed-Loop Verification ──────────────────────────────────────────────

    def _verify_step_outcome(self, step: PlanStep, raw_result: str) -> Tuple[bool, str]:
        """
        Verify that a step genuinely achieved its outcome before advancing.
        Consumes hardware/driver proof from AgentContext, filesystem state, and failure taxonomy.
        """
        ctx = AgentContext.get_instance()
        prev = ctx.previous_action_result or {}

        # 1. Driver/Hardware-level verification explicitly failed
        if prev.get("verified") is False:
            source = prev.get("verification_source", "driver")
            return False, f"Action verification failed ({source})"

        # 2. Standard failure prefixes
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

        # 3. Filesystem mutation verification
        if step.tool == "file_controller" and step.action in ("write", "create", "download"):
            target_path = step.parameters.get("path") or step.parameters.get("file_path")
            if target_path and not Path(os.path.expanduser(target_path)).exists():
                return False, f"Target file '{target_path}' does not exist on disk after execution."

        # 4. Application launch verification (Explicit branching, zero fallthrough)
        if step.tool == "open_app":
            app_target = step.parameters.get("app_name", "").lower()
            active_app = (ctx.current_active_application or "").lower()
            open_windows = [w.lower() for w in ctx.open_applications]

            # Branch 4A: App window detected in foreground or open application list
            if app_target and (app_target in active_app or any(app_target in w for w in open_windows)):
                return True, f"Application '{app_target}' window detected in active or open window list."

            # Branch 4B: OS process verified via psutil PID check in AgentContext
            elif prev.get("verified") is True:
                source = prev.get("verification_source", "process table")
                return True, f"Application '{app_target}' process verified via {source}."

            # Branch 4C: Neither window nor process verified
            else:
                return False, f"Application '{app_target}' not found in active windows or verified processes."

        return True, "Step output verified successfully."

    # ── Failure & Cancellation Handling ───────────────────────────────────────

    def _handle_failure(self, step: PlanStep, error_message: str) -> None:
        """Applies the report-and-stop policy upon any failure or security block."""
        step.status = StepStatus.FAILED
        step.error = error_message
        if self._active_plan:
            self._active_plan.state = PlanState.FAILED
            self._active_plan.error = f"Execution halted at step {step.step_id}: {error_message}"
            self._active_plan.updated_at = time.time()

        # Clean up any active confirmation listener
        if self._active_unregister_fn:
            try:
                self._active_unregister_fn()
            except Exception:
                pass
            self._active_unregister_fn = None

    def cancel_active_plan(self, reason: str = "Cancelled by user") -> Optional[ExecutionPlan]:
        """Explicitly cancels the active plan and unregisters any active confirmation listener."""
        plan = self._active_plan
        if plan is None or plan.is_finished:
            return None

        # Clean up listener
        if self._active_unregister_fn:
            try:
                self._active_unregister_fn()
            except Exception:
                pass
            self._active_unregister_fn = None

        if plan.current_step and plan.current_step.status == StepStatus.PAUSED_FOR_CONFIRMATION:
            plan.current_step.status = StepStatus.CANCELLED
            plan.current_step.error = reason

        plan.state = PlanState.CANCELLED
        plan.error = reason
        plan.updated_at = time.time()
        self._active_plan = None
        return plan

    # ── Resolution Callback Factory ───────────────────────────────────────────

    def _make_resolution_handler(self, plan_id: str, step_id: int) -> Callable[[str, bool, Optional[str]], None]:
        """Factory creating an isolated resolution callback accepting (key, accepted, result)."""
        def on_resolved(key: str, accepted: bool, result: Optional[str] = None) -> None:
            loop = getattr(self._agent, "loop", None) or getattr(self._agent, "_loop", None)
            if loop is None:
                try:
                    loop = asyncio.get_event_loop()
                except Exception:
                    loop = None
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.resume_plan(plan_id, step_id, accepted, result),
                    loop,
                )
        return on_resolved

    # ── Primary Execution Loop ────────────────────────────────────────────────

    async def execute_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """
        Execute or continue an ExecutionPlan.

        Protected by:
        1. Plan-Level Collision Guard
        2. Monotonic Execution Generation Counter (fencing token)
        3. Pre-Dispatch Confirmation Subscription
        """
        # --- PLAN-LEVEL COLLISION GUARD ---
        if self._active_plan is not None and self._active_plan.plan_id != plan.plan_id:
            if not self._active_plan.is_finished:
                active = self._active_plan
                curr_desc = active.current_step.description if active.current_step else "unknown"
                raise PlanCollisionError(
                    f"Plan collision: Cannot start plan '{plan.plan_id}' while plan "
                    f"'{active.plan_id}' is active in state '{active.state.value}' "
                    f"(Step {active.current_step_index + 1}/{len(active.steps)}: '{curr_desc}'). "
                    f"Complete or cancel active plan before starting a new one."
                )

        self._active_plan = plan
        if plan.state == PlanState.READY:
            plan.state = PlanState.RUNNING
            plan.updated_at = time.time()

        while plan.current_step_index < len(plan.steps):
            step = plan.current_step
            if not step:
                break

            # If already marked completed by a prior driver, advance cleanly
            if step.status == StepStatus.COMPLETED:
                plan.current_step_index += 1
                continue

            # ── 1. BUMP & CAPTURE GENERATION FENCING TOKEN ──
            self._execution_generation += 1
            gen = self._execution_generation

            step.status = StepStatus.RUNNING
            plan.updated_at = time.time()

            # Pre-flight security permission check
            perm = check_permission(step.tool, step.action or "", step.parameters)
            step.permission_level = perm.level.value
            step.permission_key = perm.key

            if perm.level == PermissionLevel.BLOCKED:
                self._handle_failure(step, f"Security Policy BLOCKED: {perm.reason}")
                return plan

            # Pre-dispatch listener subscription if confirmation required
            if perm.level in (PermissionLevel.CONFIRM, PermissionLevel.STRONG_CONFIRM):
                self._active_unregister_fn = confirm.add_resolution_listener(
                    callback=self._make_resolution_handler(plan.plan_id, step.step_id),
                    target_key=perm.key,
                    oneshot=True,
                )

            # ── 2. ASYNC SUSPENSION POINT: Tool Dispatch ──
            step_args = dict(step.parameters)
            if step.action and "action" not in step_args:
                step_args["action"] = step.action

            step_call = StepCall(name=step.tool, args=step_args)
            try:
                fn_resp = await self._agent._execute_tool(step_call)
                if hasattr(fn_resp, "response"):
                    if isinstance(fn_resp.response, dict):
                        raw_result = str(fn_resp.response.get("result", fn_resp.response))
                    else:
                        raw_result = str(fn_resp.response)
                else:
                    raw_result = str(fn_resp)
            except Exception as exc:
                # If superseded during await, discard stale exception
                if gen != self._execution_generation:
                    return plan
                self._handle_failure(step, f"Tool execution exception in '{step.tool}': {exc}")
                return plan

            # ── 3. REENTRANCY GUARD POST-AWAIT CHECK ──
            # If resume_plan superseded this coroutine while it was awaiting,
            # drop out immediately to prevent stale state overwriting or double-increments.
            if gen != self._execution_generation:
                return plan

            # Check for confirmation pause
            if "[CONFIRMATION_PENDING]" in str(raw_result):
                step.status = StepStatus.PAUSED_FOR_CONFIRMATION
                plan.state = PlanState.PAUSED_FOR_CONFIRMATION
                plan.updated_at = time.time()
                return plan

            # Post-execution closed-loop verification
            verified, verify_details = self._verify_step_outcome(step, raw_result)
            if not verified:
                self._handle_failure(step, f"Verification failed: {verify_details}")
                return plan

            # Advance step on verified success
            step.status = StepStatus.COMPLETED
            step.result = raw_result
            step.verified = True
            step.error = None
            plan.current_step_index += 1
            plan.updated_at = time.time()

        if plan.current_step_index >= len(plan.steps) and plan.state != PlanState.FAILED:
            plan.state = PlanState.COMPLETED
            plan.updated_at = time.time()

        return plan

    # ── Asynchronous Resume State Machine ──────────────────────────────────────

    async def resume_plan(
        self,
        plan_id: str,
        step_id: int,
        accepted: bool,
        result: Optional[str] = None,
    ) -> None:
        """
        Invoked asynchronously when a user confirms or cancels a pending action on the HUD.
        Executes on the main asyncio event loop.
        """
        if not self._active_plan or self._active_plan.plan_id != plan_id:
            return
        plan = self._active_plan
        step = plan.current_step

        if not step or step.step_id != step_id:
            return

        self._active_unregister_fn = None

        # ── 4. INVALIDATE ALL SUSPENDED / IN-FLIGHT DRIVERS ──
        self._execution_generation += 1

        if not accepted:
            # User cancelled or expired
            step.status = StepStatus.CANCELLED
            step.result = result or "User cancelled confirmation."
            step.error = step.result
            plan.state = PlanState.CANCELLED
            plan.error = f"Step {step.step_id} cancelled: {step.result}"
            plan.updated_at = time.time()
            if hasattr(self._agent, "speak") and callable(self._agent.speak):
                self._agent.speak("Understood. Plan has been cancelled.")
            if hasattr(self._agent, "ui") and hasattr(self._agent.ui, "write_log"):
                self._agent.ui.write_log("PLAN: Plan cancelled by user.")
            return

        # Real result returned by the confirmed action's run() closure
        raw_result = result or "Done."
        step.result = raw_result

        # Apply identical closed-loop verification to the resumed step
        verified, verify_details = self._verify_step_outcome(step, raw_result)
        if not verified:
            self._handle_failure(step, f"Resumed step verification failed: {verify_details}")
            if hasattr(self._agent, "speak") and callable(self._agent.speak):
                self._agent.speak(f"Plan stopped: resumed step verification failed.")
            return

        # Step verified successfully: advance
        step.status = StepStatus.COMPLETED
        step.verified = True
        step.error = None
        plan.current_step_index += 1
        plan.state = PlanState.RUNNING
        plan.updated_at = time.time()

        # Drive plan forward through remaining steps
        await self.execute_plan(plan)

        # Notify user of terminal outcome or subsequent pause post-resume
        if hasattr(self._agent, "speak") and callable(self._agent.speak):
            if plan.state == PlanState.COMPLETED:
                self._agent.speak(f"Plan complete. All {len(plan.steps)} steps finished successfully.")
            elif plan.state == PlanState.PAUSED_FOR_CONFIRMATION:
                curr = plan.current_step
                if curr:
                    self._agent.speak(f"I've paused at step {curr.step_id}. Please confirm on screen to {curr.description}.")
            elif plan.state == PlanState.FAILED:
                self._agent.speak(f"Plan stopped at step {plan.current_step_index + 1}: {plan.error}")
            elif plan.state == PlanState.CANCELLED:
                self._agent.speak("Plan cancelled.")
        if hasattr(self._agent, "ui") and hasattr(self._agent.ui, "write_log"):
            self._agent.ui.write_log(f"PLAN: Resumed plan reached state {plan.state.value}.")
