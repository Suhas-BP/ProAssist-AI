"""
agent/planner.py
================
Multi-Step Planning Engine for Mark LIV (Sub-Phase 5A).

Defines:
1. Data models: StepStatus, PlanState, PlanStep, ExecutionPlan.
2. Schema-constrained decomposition prompt builder injecting:
   - User goal
   - Scrubbed AgentContext live snapshot text (Item 4)
   - Discovered tool catalogue from action_registry
3. Strict JSON schema validation for plan parsing.
4. Static pre-flight plan validation:
   - Verifies tool existence in action_registry
   - Evaluates check_permission() per step
   - Rejects the entire plan immediately if ANY step is BLOCKED (zero steps executed)
   - Enriches each step with validated permission_level and permission_key
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union


# ── Status and State Enums ─────────────────────────────────────────────────────

class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PAUSED_FOR_CONFIRMATION = "PAUSED_FOR_CONFIRMATION"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class PlanState(str, Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED_FOR_CONFIRMATION = "PAUSED_FOR_CONFIRMATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# ── Validation and Security Exceptions ─────────────────────────────────────────

class PlanValidationError(Exception):
    """Raised when plan structure, tool reference, or parameters fail validation."""
    pass


class PlanSecurityRejection(Exception):
    """Raised when a plan contains an operation BLOCKED by security policy."""
    pass


# ── Data Models ────────────────────────────────────────────────────────────────

@dataclass
class PlanStep:
    step_id: int
    description: str
    tool: str
    action: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    expected_outcome: str = ""
    status: StepStatus = StepStatus.PENDING
    permission_level: str = "SAFE"
    permission_key: str = ""
    result: Optional[str] = None
    error: Optional[str] = None
    verified: Optional[bool] = None

    @property
    def confirmation_key(self) -> str:
        """Alias for permission_key ensuring interoperability with race-condition fix."""
        return self.permission_key

    @confirmation_key.setter
    def confirmation_key(self, val: str) -> None:
        self.permission_key = val

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "description": self.description,
            "tool": self.tool,
            "action": self.action,
            "parameters": self.parameters,
            "expected_outcome": self.expected_outcome,
            "status": self.status.value if isinstance(self.status, StepStatus) else str(self.status),
            "permission_level": self.permission_level,
            "permission_key": self.permission_key,
            "result": self.result,
            "error": self.error,
            "verified": self.verified,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PlanStep:
        status_val = d.get("status", StepStatus.PENDING)
        if isinstance(status_val, str):
            try:
                status_val = StepStatus(status_val)
            except ValueError:
                status_val = StepStatus.PENDING

        perm_key = str(d.get("permission_key") or d.get("confirmation_key") or "")

        return cls(
            step_id=int(d["step_id"]),
            description=str(d.get("description", "")),
            tool=str(d.get("tool", "")),
            action=str(d.get("action", "") or ""),
            parameters=dict(d.get("parameters") or {}),
            expected_outcome=str(d.get("expected_outcome", "")),
            status=status_val,
            permission_level=str(d.get("permission_level", "SAFE")),
            permission_key=perm_key,
            result=d.get("result"),
            error=d.get("error"),
            verified=d.get("verified"),
        )


@dataclass
class ExecutionPlan:
    plan_id: str
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    current_step_index: int = 0
    state: PlanState = PlanState.READY
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    context_snapshot: str = ""
    error: Optional[str] = None

    @property
    def current_step(self) -> Optional[PlanStep]:
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    @property
    def is_finished(self) -> bool:
        return self.state in (PlanState.COMPLETED, PlanState.FAILED, PlanState.CANCELLED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "current_step_index": self.current_step_index,
            "state": self.state.value if isinstance(self.state, PlanState) else str(self.state),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "context_snapshot": self.context_snapshot,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ExecutionPlan:
        state_val = d.get("state", PlanState.READY)
        if isinstance(state_val, str):
            try:
                state_val = PlanState(state_val)
            except ValueError:
                state_val = PlanState.READY

        steps = [PlanStep.from_dict(s) for s in d.get("steps", [])]

        return cls(
            plan_id=str(d.get("plan_id", f"plan_{int(time.time() * 1000)}")),
            goal=str(d.get("goal", "")),
            steps=steps,
            current_step_index=int(d.get("current_step_index", 0)),
            state=state_val,
            created_at=float(d.get("created_at", time.time())),
            updated_at=float(d.get("updated_at", time.time())),
            context_snapshot=str(d.get("context_snapshot", "")),
            error=d.get("error"),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> ExecutionPlan:
        return cls.from_dict(json.loads(json_str))


# ── Tool Catalogue & Decomposition Prompt Construction ────────────────────────

def format_tool_catalogue(action_registry=None) -> str:
    """Format the discovered action registry tools and parameters as a text catalogue for the LLM."""
    if action_registry is None:
        from core.action_loader import discover_actions
        base_dir = Path(__file__).resolve().parent.parent
        action_registry = discover_actions(actions_dir=base_dir / "actions")

    catalogue_lines = []
    for name in sorted(action_registry.names()):
        rec = action_registry._actions.get(name)
        if not rec:
            continue
        desc = (rec.description or "").strip().replace("\n", " ")
        props = rec.parameters.get("properties", {}) if isinstance(rec.parameters, dict) else {}
        param_keys = list(props.keys())
        catalogue_lines.append(f"- {name}: {desc} | Parameters: {param_keys}")
    return "\n".join(catalogue_lines)


def build_decomposition_prompt(
    goal: str,
    context_snapshot: Optional[str] = None,
    action_registry=None,
) -> str:
    """
    Construct the schema-constrained prompt for multi-step plan decomposition.
    Injects:
    1. User goal
    2. Scrubbed AgentContext snapshot
    3. Live tool catalogue from action_registry
    """
    if context_snapshot is None:
        from agent.context import AgentContext
        context_snapshot = AgentContext.get_instance().get_snapshot_text(scrub=True)

    tool_catalogue = format_tool_catalogue(action_registry)

    prompt = f"""You are the Multi-Step Planning Engine for Mark LIV.
Your job is to break down the user's high-level goal into an ordered sequence of atomic execution steps.

CURRENT LIVE AGENT CONTEXT:
{context_snapshot}

AVAILABLE TOOL CATALOGUE:
{tool_catalogue}

CONSTRAINTS & RULES:
1. Every step MUST use an available tool from the catalogue.
2. Only use valid parameter keys recognized by each tool.
3. Steps must be strictly sequential and atomic.
4. Output must be strictly valid JSON matching the exact schema below. No conversational text, no markdown backticks, no markdown formatting.

REQUIRED JSON SCHEMA:
{{
  "goal": "{goal}",
  "steps": [
    {{
      "step_id": 1,
      "description": "<concise explanation of what this step achieves>",
      "tool": "<tool_name_from_catalogue>",
      "action": "<action_name_or_empty>",
      "parameters": {{ ... }},
      "expected_outcome": "<measurable/observable success criterion>"
    }}
  ]
}}

USER GOAL:
{goal}
"""
    return prompt


# ── Schema Validation & Parsing ────────────────────────────────────────────────

def parse_and_validate_plan_json(json_str_or_dict: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate the returned JSON or dict against the ExecutionPlan schema.
    Rejects malformed structures with clear descriptive error messages.
    """
    if isinstance(json_str_or_dict, str):
        cleaned = json_str_or_dict.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            data = json.loads(cleaned)
        except Exception as e:
            raise PlanValidationError(
                f"Invalid JSON received for execution plan: {e}\nRaw output: {json_str_or_dict[:200]}"
            )
    elif isinstance(json_str_or_dict, dict):
        data = json_str_or_dict
    else:
        raise PlanValidationError(
            f"Expected plan data as dict or JSON string, got {type(json_str_or_dict).__name__}"
        )

    if not isinstance(data, dict):
        raise PlanValidationError(f"Root plan object must be a dictionary, got {type(data).__name__}")

    if "goal" not in data or not isinstance(data["goal"], str) or not data["goal"].strip():
        raise PlanValidationError("Plan schema violation: missing or empty 'goal' string field.")

    if "steps" not in data or not isinstance(data["steps"], list):
        raise PlanValidationError("Plan schema violation: missing or non-list 'steps' field.")

    if len(data["steps"]) == 0:
        raise PlanValidationError("Plan schema violation: 'steps' list cannot be empty. At least one step is required.")

    for idx, s in enumerate(data["steps"]):
        if not isinstance(s, dict):
            raise PlanValidationError(f"Plan step #{idx + 1} must be an object, got {type(s).__name__}.")

        # Required fields: step_id, description, tool, parameters, expected_outcome
        if "step_id" not in s or not isinstance(s["step_id"], int) or s["step_id"] < 1:
            raise PlanValidationError(
                f"Plan step #{idx + 1} has invalid or missing 'step_id' (must be integer >= 1)."
            )

        if "description" not in s or not isinstance(s["description"], str) or not s["description"].strip():
            raise PlanValidationError(
                f"Plan step #{idx + 1} (step_id {s.get('step_id')}) has missing or empty 'description'."
            )

        if "tool" not in s or not isinstance(s["tool"], str) or not s["tool"].strip():
            raise PlanValidationError(
                f"Plan step #{idx + 1} (step_id {s.get('step_id')}) has missing or empty 'tool'."
            )

        if "parameters" not in s or not isinstance(s["parameters"], dict):
            raise PlanValidationError(
                f"Plan step #{idx + 1} (step_id {s.get('step_id')}) has missing or non-dict 'parameters'."
            )

        if "expected_outcome" not in s or not isinstance(s["expected_outcome"], str):
            raise PlanValidationError(
                f"Plan step #{idx + 1} (step_id {s.get('step_id')}) has missing or non-string 'expected_outcome'."
            )

    return data


# ── Static Pre-Flight Validation ───────────────────────────────────────────────

def validate_plan(
    plan: ExecutionPlan,
    action_registry=None,
) -> ExecutionPlan:
    """
    Perform static pre-flight validation on an ExecutionPlan before execution begins.
    Checks:
    1. Every step.tool exists in action_registry (or recognized alias).
    2. Every step passes check_permission() without returning PermissionLevel.BLOCKED.

    If ANY step fails either check:
    - Entire plan state is set to PlanState.FAILED.
    - An explanatory error message is attached naming the exact step and reason.
    - Raises PlanValidationError (or PlanSecurityRejection). Zero steps execute.

    If all steps pass:
    - Enriches each step with its validated permission_level and permission_key.
    - Returns the validated plan in PlanState.READY.
    """
    if action_registry is None:
        from core.action_loader import discover_actions
        base_dir = Path(__file__).resolve().parent.parent
        action_registry = discover_actions(actions_dir=base_dir / "actions")

    from core.permission_manager import check_permission, PermissionLevel

    for step in plan.steps:
        # Check tool existence
        tool_name = step.tool.lower().strip()
        lookup_name = "desktop_control" if tool_name == "desktop" else tool_name

        if not action_registry.has(lookup_name):
            err_msg = (
                f"Pre-flight Validation Error: Step {step.step_id} ('{step.description}') "
                f"references unknown or unregistered tool '{step.tool}'. "
                f"Valid tools: {sorted(action_registry.names())}"
            )
            plan.state = PlanState.FAILED
            plan.error = err_msg
            step.status = StepStatus.FAILED
            step.error = err_msg
            raise PlanValidationError(err_msg)

        # Check security policy gate
        perm = check_permission(step.tool, step.action or "", step.parameters)
        if perm.level == PermissionLevel.BLOCKED:
            err_msg = (
                f"Pre-flight Security Rejection: Step {step.step_id} ('{step.description}') "
                f"is BLOCKED by security policy (reason: '{perm.reason}'). "
                f"The entire plan is rejected; zero steps executed."
            )
            plan.state = PlanState.FAILED
            plan.error = err_msg
            step.status = StepStatus.FAILED
            step.error = err_msg
            step.permission_level = perm.level.value
            step.permission_key = perm.key
            raise PlanSecurityRejection(err_msg)

        # Enrich step with pre-flight permission decision
        step.permission_level = perm.level.value
        step.permission_key = perm.key

    plan.state = PlanState.READY
    plan.updated_at = time.time()
    return plan


# ── High-Level Plan Creation Pipeline ──────────────────────────────────────────

def create_plan_from_dict(
    plan_dict: Dict[str, Any],
    action_registry=None,
    context_snapshot: str = "",
) -> ExecutionPlan:
    """Validate a parsed plan dict, construct ExecutionPlan, and run static pre-flight validation."""
    validated_dict = parse_and_validate_plan_json(plan_dict)
    plan_id = f"plan_{int(time.time() * 1000)}"
    steps = [PlanStep.from_dict(s) for s in validated_dict["steps"]]
    plan = ExecutionPlan(
        plan_id=plan_id,
        goal=validated_dict["goal"],
        steps=steps,
        context_snapshot=context_snapshot,
    )
    return validate_plan(plan, action_registry=action_registry)


def create_plan(
    goal: str,
    action_registry=None,
    context_snapshot: Optional[str] = None,
    llm_caller: Optional[Callable[[str], str]] = None,
) -> ExecutionPlan:
    """
    Decompose a user goal into an ExecutionPlan using schema-constrained LLM prompting,
    validates the output JSON against the schema, and executes static pre-flight validation.
    """
    if context_snapshot is None:
        from agent.context import AgentContext
        context_snapshot = AgentContext.get_instance().get_snapshot_text(scrub=True)

    prompt = build_decomposition_prompt(
        goal=goal,
        context_snapshot=context_snapshot,
        action_registry=action_registry,
    )

    if llm_caller is not None:
        raw_output = llm_caller(prompt)
    else:
        from core import gemini
        raw_output = gemini.text(prompt, tier=gemini.SMART)
        if not raw_output:
            raise PlanValidationError("LLM planner returned empty response or failed to generate plan.")

    validated_dict = parse_and_validate_plan_json(raw_output)
    plan_id = f"plan_{int(time.time() * 1000)}"
    steps = [PlanStep.from_dict(s) for s in validated_dict["steps"]]
    plan = ExecutionPlan(
        plan_id=plan_id,
        goal=validated_dict["goal"],
        steps=steps,
        context_snapshot=context_snapshot,
    )
    return validate_plan(plan, action_registry=action_registry)
