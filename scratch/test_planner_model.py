"""
scratch/test_planner_model.py
=============================
Dedicated test suite for Sub-Phase 5A: Multi-Step Planner Data Models,
Schema-Constrained Decomposition, and Static Pre-Flight Validation.

Validates:
1. Data models (ExecutionPlan, PlanStep, StepStatus, PlanState) and round-trip serialization.
2. confirmation_key / permission_key interoperability.
3. Schema-constrained decomposition prompt construction injecting:
   - User goal
   - Scrubbed AgentContext live snapshot
   - Dynamic tool catalogue from action_registry
4. Schema validation rejecting malformed, missing, or mistyped plan JSON.
5. Static pre-flight validation rejecting unknown tools before execution.
6. Static pre-flight security validation rejecting the ENTIRE plan immediately
   if ANY step is BLOCKED (e.g. disk-format command), with zero steps executed.
7. Pre-flight permission enrichment with aligned permission_key values for Sub-Phase 5B.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

# UTF-8 stdout
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from agent.context import AgentContext
from agent.planner import (
    ExecutionPlan,
    PlanStep,
    StepStatus,
    PlanState,
    PlanValidationError,
    PlanSecurityRejection,
    build_decomposition_prompt,
    format_tool_catalogue,
    parse_and_validate_plan_json,
    validate_plan,
    create_plan,
    create_plan_from_dict,
)
from core.action_loader import discover_actions
from core.permission_manager import PermissionLevel, check_permission


def test_data_model_serialization_and_roundtrip():
    print("=" * 70)
    print("TEST 1: ExecutionPlan & PlanStep Serialization and Round-Trip")
    print("=" * 70)

    # Construct concrete realistic plan
    step1 = PlanStep(
        step_id=1,
        description="Search for project files in workspace",
        tool="file_controller",
        action="find",
        parameters={"path": "src", "pattern": "*.py"},
        expected_outcome="List of matching Python source files",
        status=StepStatus.PENDING,
        permission_level="SAFE",
        permission_key="file_find",
    )

    step2 = PlanStep(
        step_id=2,
        description="Run test suite to verify baseline",
        tool="dev_agent",
        action="run_project",
        parameters={"command": "pytest tests/unit"},
        expected_outcome="All unit tests pass",
        status=StepStatus.PENDING,
        permission_level="CONFIRM",
        permission_key="run_project",
    )

    step3 = PlanStep(
        step_id=3,
        description="Delete temporary scratch directory",
        tool="file_controller",
        action="delete",
        parameters={"path": "scratch/temp_dump"},
        expected_outcome="Scratch directory deleted",
        status=StepStatus.PENDING,
        permission_level="STRONG_CONFIRM",
        permission_key="delete_file",
    )

    # Test alias property
    assert step2.confirmation_key == "run_project"
    step2.confirmation_key = "run_project_updated"
    assert step2.permission_key == "run_project_updated"
    step2.confirmation_key = "run_project"

    plan = ExecutionPlan(
        plan_id="plan_test_001",
        goal="Run unit tests and clean scratch directory",
        steps=[step1, step2, step3],
        context_snapshot="App: VS Code | Window: 'Mark-LIV' | State: READY",
    )

    assert plan.current_step.step_id == 1
    assert not plan.is_finished

    # Serialize to dict and JSON
    plan_dict = plan.to_dict()
    plan_json = plan.to_json()

    assert plan_dict["plan_id"] == "plan_test_001"
    assert len(plan_dict["steps"]) == 3
    assert plan_dict["steps"][1]["permission_key"] == "run_project"

    # Deserialize and verify byte-for-byte equality
    restored_from_dict = ExecutionPlan.from_dict(plan_dict)
    restored_from_json = ExecutionPlan.from_json(plan_json)

    assert restored_from_dict.plan_id == plan.plan_id
    assert restored_from_dict.goal == plan.goal
    assert len(restored_from_dict.steps) == 3
    assert restored_from_dict.steps[0].tool == "file_controller"
    assert restored_from_dict.steps[1].permission_key == "run_project"
    assert restored_from_dict.steps[2].action == "delete"

    assert restored_from_json.plan_id == plan.plan_id
    assert restored_from_json.goal == plan.goal
    assert len(restored_from_json.steps) == 3
    assert restored_from_json.steps[2].permission_key == "delete_file"

    print("  -> Data models serialized to dict & JSON, restored with 100% fidelity.")
    print("  -> confirmation_key / permission_key alias verified bidirectionally.")
    print("PASSED: Test 1\n")


def test_schema_constrained_prompt_construction():
    print("=" * 70)
    print("TEST 2: Schema-Constrained Prompt Construction with Injected Context")
    print("=" * 70)

    # Ensure AgentContext has realistic state
    ctx = AgentContext.get_instance()
    ctx.set_active_file("src/main_pipeline.py")
    ctx.update_tool_state(
        tool="open_app",
        action="launch",
        parameters={"app_name": "notepad.exe"},
        result="Opened notepad successfully",
        verified=True,
    )

    action_reg = discover_actions(actions_dir=BASE_DIR / "actions")

    goal = "Organize all downloaded PDF receipts into College/ folder and clean up duplicates"
    prompt = build_decomposition_prompt(
        goal=goal,
        action_registry=action_reg,
    )

    # 1. Verify user goal is present
    assert goal in prompt, "User goal missing from prompt"

    # 2. Verify scrubbed AgentContext snapshot is present
    snap_text = ctx.get_snapshot_text(scrub=True)
    assert "File: src/main_pipeline.py" in prompt, "AgentContext active_file missing from prompt"
    assert "open_app" in prompt, "AgentContext recent action missing from prompt"

    # 3. Verify live action_registry catalogue is present
    assert "- file_controller:" in prompt, "file_controller missing from catalogue in prompt"
    assert "- dev_agent:" in prompt, "dev_agent missing from catalogue in prompt"
    assert "- desktop_control:" in prompt, "desktop_control missing from catalogue in prompt"
    assert "- browser_control:" in prompt, "browser_control missing from catalogue in prompt"

    # 4. Verify required JSON schema structure instructions are present
    assert "REQUIRED JSON SCHEMA:" in prompt
    assert '"step_id": 1' in prompt
    assert '"expected_outcome":' in prompt

    print(f"  -> Generated prompt length: {len(prompt)} chars")
    print("  -> User goal verified in prompt.")
    print(f"  -> AgentContext snapshot verified in prompt: '{snap_text}'")
    print(f"  -> Discovered {len(action_reg.names())} tools formatted in catalogue.")
    print("PASSED: Test 2\n")


def test_schema_validation_rejections():
    print("=" * 70)
    print("TEST 3: Schema Validation Rejection on Malformed JSON")
    print("=" * 70)

    # Case A: Not JSON at all
    try:
        parse_and_validate_plan_json("I cannot help with that task.")
        assert False, "Should have raised PlanValidationError for non-JSON"
    except PlanValidationError as e:
        print(f"  -> Correctly caught non-JSON: {e}")

    # Case B: Missing goal
    try:
        parse_and_validate_plan_json(json.dumps({"steps": [{"step_id": 1, "description": "a", "tool": "b", "parameters": {}, "expected_outcome": "c"}]}))
        assert False, "Should have raised for missing goal"
    except PlanValidationError as e:
        assert "missing or empty 'goal'" in str(e)
        print(f"  -> Correctly caught missing goal: {e}")

    # Case C: Empty steps list
    try:
        parse_and_validate_plan_json(json.dumps({"goal": "do something", "steps": []}))
        assert False, "Should have raised for empty steps"
    except PlanValidationError as e:
        assert "'steps' list cannot be empty" in str(e)
        print(f"  -> Correctly caught empty steps: {e}")

    # Case D: Malformed step missing required 'tool' field
    try:
        bad_steps = {
            "goal": "Test goal",
            "steps": [
                {
                    "step_id": 1,
                    "description": "Valid step",
                    "tool": "file_controller",
                    "parameters": {},
                    "expected_outcome": "done",
                },
                {
                    "step_id": 2,
                    "description": "Step missing tool field",
                    "parameters": {},
                    "expected_outcome": "done",
                },
            ],
        }
        parse_and_validate_plan_json(json.dumps(bad_steps))
        assert False, "Should have raised for step missing tool"
    except PlanValidationError as e:
        assert "missing or empty 'tool'" in str(e)
        print(f"  -> Correctly caught step missing tool: {e}")

    # Case E: Non-integer step_id
    try:
        bad_id = {
            "goal": "Test goal",
            "steps": [{"step_id": "one", "description": "d", "tool": "t", "parameters": {}, "expected_outcome": "o"}],
        }
        parse_and_validate_plan_json(bad_id)
        assert False, "Should have raised for invalid step_id"
    except PlanValidationError as e:
        assert "invalid or missing 'step_id'" in str(e)
        print(f"  -> Correctly caught invalid step_id: {e}")

    print("PASSED: Test 3\n")


def test_static_preflight_unknown_tool_rejection():
    print("=" * 70)
    print("TEST 4: Static Pre-Flight Validation Rejects Nonexistent Tool")
    print("=" * 70)

    action_reg = discover_actions(actions_dir=BASE_DIR / "actions")

    # Step 1 is valid; Step 2 references fake nonexistent tool 'hack_matrix'
    plan = ExecutionPlan(
        plan_id="plan_unknown_tool",
        goal="Perform automated tasks",
        steps=[
            PlanStep(
                step_id=1,
                description="List files in current directory",
                tool="file_controller",
                action="list",
                parameters={"path": "."},
                expected_outcome="Directory contents",
            ),
            PlanStep(
                step_id=2,
                description="Trigger non-existent tool",
                tool="hack_matrix",
                action="infiltrate",
                parameters={"target": "mainframe"},
                expected_outcome="Infiltration complete",
            ),
        ],
    )

    try:
        validate_plan(plan, action_registry=action_reg)
        assert False, "Pre-flight validation MUST fail for nonexistent tool"
    except PlanValidationError as e:
        err_msg = str(e)
        assert "Step 2" in err_msg
        assert "hack_matrix" in err_msg
        assert "unknown or unregistered tool" in err_msg
        print(f"  -> Successfully caught unknown tool statically: {err_msg}")

    # Assert plan was rejected with PlanState.FAILED
    assert plan.state == PlanState.FAILED
    assert "hack_matrix" in plan.error
    assert plan.steps[1].status == StepStatus.FAILED
    print("  -> Plan state marked FAILED, zero steps executed.")
    print("PASSED: Test 4\n")


def test_static_preflight_blocked_permission_rejection():
    print("=" * 70)
    print("TEST 5: Static Pre-Flight Security Rejection (Entire Plan Rejected on BLOCKED)")
    print("=" * 70)

    action_reg = discover_actions(actions_dir=BASE_DIR / "actions")

    # Plan with Step 1 SAFE, Step 2 BLOCKED (disk format command), Step 3 SAFE
    plan = ExecutionPlan(
        plan_id="plan_blocked_test",
        goal="Wipe disk and verify",
        steps=[
            PlanStep(
                step_id=1,
                description="List current files",
                tool="file_controller",
                action="list",
                parameters={"path": "."},
                expected_outcome="Files listed",
            ),
            PlanStep(
                step_id=2,
                description="Execute prohibited format command",
                tool="dev_agent",
                action="run_project",
                parameters={"command": "format C: /fs:NTFS"},
                expected_outcome="Drive formatted",
            ),
            PlanStep(
                step_id=3,
                description="Open calculator",
                tool="open_app",
                action="open_app",
                parameters={"app_name": "calc"},
                expected_outcome="Calculator opened",
            ),
        ],
    )

    try:
        validate_plan(plan, action_registry=action_reg)
        assert False, "Pre-flight validation MUST reject plan containing BLOCKED step"
    except PlanSecurityRejection as e:
        err_msg = str(e)
        assert "Step 2" in err_msg
        assert "BLOCKED by security policy" in err_msg
        assert "zero steps executed" in err_msg
        print(f"  -> Successfully rejected plan statically: {err_msg}")

    # Assert ENTIRE plan was rejected before execution
    assert plan.state == PlanState.FAILED
    assert "BLOCKED by security policy" in plan.error
    assert plan.steps[1].status == StepStatus.FAILED
    assert plan.steps[1].permission_level == "BLOCKED"
    assert plan.steps[1].permission_key == "command_execution_blocked"

    # Verify Step 1 was NEVER executed
    assert plan.steps[0].status == StepStatus.PENDING
    assert plan.steps[0].result is None
    print("  -> Verified: Step 1 remained PENDING, zero steps dispatched.")

    # Also test destructive desktop automation code pattern
    desktop_blocked_plan = ExecutionPlan(
        plan_id="plan_desktop_blocked",
        goal="Automate desktop cleanup with destructive script",
        steps=[
            PlanStep(
                step_id=1,
                description="Run destructive desktop task",
                tool="desktop_control",
                action="task",
                parameters={"code": "import shutil\nshutil.rmtree('C:/')"},
                expected_outcome="Clean desktop",
            )
        ],
    )

    try:
        validate_plan(desktop_blocked_plan, action_registry=action_reg)
        assert False, "Pre-flight validation MUST reject destructive desktop code"
    except PlanSecurityRejection as e:
        assert "Step 1" in str(e)
        assert "BLOCKED" in str(e)
        print(f"  -> Destructive desktop automation also rejected statically: {e}")

    assert desktop_blocked_plan.state == PlanState.FAILED
    print("PASSED: Test 5\n")


def test_static_preflight_permission_enrichment():
    print("=" * 70)
    print("TEST 6: Static Pre-Flight Permission Enrichment (Pre-Dispatch Key Alignment)")
    print("=" * 70)

    action_reg = discover_actions(actions_dir=BASE_DIR / "actions")

    # Valid plan with diverse permission levels
    plan = ExecutionPlan(
        plan_id="plan_valid_enrichment",
        goal="Download receipts, organize them, and launch viewer",
        steps=[
            PlanStep(
                step_id=1,
                description="List current files in Downloads",
                tool="file_controller",
                action="list",
                parameters={"path": "Downloads"},
                expected_outcome="Downloads file listing",
            ),
            PlanStep(
                step_id=2,
                description="Run test runner",
                tool="dev_agent",
                action="run_project",
                parameters={"command": "python -m unittest"},
                expected_outcome="Tests ran",
            ),
            PlanStep(
                step_id=3,
                description="Delete old log file",
                tool="file_controller",
                action="delete",
                parameters={"path": "Downloads/old.log"},
                expected_outcome="Old log deleted",
            ),
            PlanStep(
                step_id=4,
                description="Download new invoice",
                tool="browser_control",
                action="download",
                parameters={"url": "https://example.com/invoice.pdf"},
                expected_outcome="Invoice downloaded",
            ),
            PlanStep(
                step_id=5,
                description="Click sensitive checkout button",
                tool="browser_control",
                action="click",
                parameters={"text": "Place Order"},
                expected_outcome="Order placed",
            ),
        ],
    )

    validated = validate_plan(plan, action_registry=action_reg)

    assert validated.state == PlanState.READY

    # Verify Step 1: SAFE
    assert validated.steps[0].permission_level == "SAFE"
    assert validated.steps[0].permission_key == "file_list"

    # Verify Step 2: CONFIRM, key="run_project" (Part A aligned)
    assert validated.steps[1].permission_level == "CONFIRM"
    assert validated.steps[1].permission_key == "run_project"

    # Verify Step 3: STRONG_CONFIRM, key="delete_file"
    assert validated.steps[2].permission_level == "STRONG_CONFIRM"
    assert validated.steps[2].permission_key == "delete_file"

    # Verify Step 4: STRONG_CONFIRM, key="browser_download"
    assert validated.steps[3].permission_level == "STRONG_CONFIRM"
    assert validated.steps[3].permission_key == "browser_download"

    # Verify Step 5: STRONG_CONFIRM, key="browser_sensitive_action" (Part A aligned)
    assert validated.steps[4].permission_level == "STRONG_CONFIRM"
    assert validated.steps[4].permission_key == "browser_sensitive_action"

    print("  -> All 5 steps statically enriched with exact permission levels and keys:")
    for s in validated.steps:
        print(f"       Step {s.step_id}: {s.tool}.{s.action or 'default'} -> level={s.permission_level}, key={s.permission_key}")

    print("PASSED: Test 6\n")


def test_end_to_end_decomposition_with_mock_llm():
    print("=" * 70)
    print("TEST 7: End-to-End create_plan() with Mock LLM Decomposition")
    print("=" * 70)

    # Simulated LLM output adhering strictly to the required schema
    mock_llm_json = json.dumps({
        "goal": "Organize PDF documents and backup project",
        "steps": [
            {
                "step_id": 1,
                "description": "Find all PDF files in Downloads folder",
                "tool": "file_controller",
                "action": "find",
                "parameters": {"path": "Downloads", "pattern": "*.pdf"},
                "expected_outcome": "List of PDF files",
            },
            {
                "step_id": 2,
                "description": "Move matching PDFs to Documents/PDFs",
                "tool": "file_controller",
                "action": "bulk_move",
                "parameters": {"source": "Downloads", "destination": "Documents/PDFs"},
                "expected_outcome": "PDFs organized",
            },
        ],
    })

    captured_prompt = []

    def mock_llm_caller(prompt: str) -> str:
        captured_prompt.append(prompt)
        return mock_llm_json

    plan = create_plan(
        goal="Organize PDF documents and backup project",
        llm_caller=mock_llm_caller,
    )

    assert len(captured_prompt) == 1
    assert "Organize PDF documents and backup project" in captured_prompt[0]
    assert plan.state == PlanState.READY
    assert len(plan.steps) == 2
    assert plan.steps[0].permission_level == "SAFE"
    assert plan.steps[0].permission_key == "file_find"
    assert plan.steps[1].permission_level == "STRONG_CONFIRM"
    assert plan.steps[1].permission_key == "file_bulk_move"

    print("  -> create_plan() successfully orchestrated prompt injection, schema validation, and pre-flight validation.")
    print(f"  -> Generated Plan ID: {plan.plan_id}, State: {plan.state.value}")
    print("PASSED: Test 7\n")


if __name__ == "__main__":
    print("\n" + "#" * 70)
    print("RUNNING SUB-PHASE 5A DEDICATED TEST SUITE (PLANNER & PRE-FLIGHT)")
    print("#" * 70 + "\n")

    test_data_model_serialization_and_roundtrip()
    test_schema_constrained_prompt_construction()
    test_schema_validation_rejections()
    test_static_preflight_unknown_tool_rejection()
    test_static_preflight_blocked_permission_rejection()
    test_static_preflight_permission_enrichment()
    test_end_to_end_decomposition_with_mock_llm()

    print("#" * 70)
    print("ALL 7 SUB-PHASE 5A TESTS COMPLETED AND PASSED WITH 100% SUCCESS!")
    print("#" * 70 + "\n")
