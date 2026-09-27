"""
scratch/test_agent_tool_ast_regression.py
=========================================
Regression test confirming:
1. AgentTool subclass with bound-method execute() parses cleanly via AST
   without IndentationError when processed by verify_permission_gates().
2. Dual-discovery path in action_loader properly validates and registers AgentTool instances.
3. verify_permission_gates() correctly resolves the module-level target function from
   the bound method and verifies confirm.request() gates and key alignment.
4. All 17 existing module-level actions pass verify_permission_gates() unchanged.
"""

import ast
import inspect
import sys
import textwrap
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.action_loader import discover_actions, ActionRegistry
from core.permission_manager import (
    PermissionLevel,
    PolicyRule,
    SecurityPolicyError,
    verify_permission_gates,
    resolve_action_handler,
    has_confirm_gate,
    get_confirm_keys,
    POLICY_RULES,
)
from core.tool import AgentTool, ToolResult
from core import confirm


# Module-level worker function with confirmation gate
def _mock_worker_action(param: str = ""):
    return confirm.request(
        key="mock_tool_confirm_key",
        title="Mock Tool Action",
        detail=f"Param: {param}",
        run=lambda: "Action Executed",
    )


def _mock_worker_unguarded(param: str = ""):
    return "Unguarded Execution"


class MockClassTool(AgentTool):
    @property
    def name(self) -> str:
        return "mock_class_tool"

    @property
    def description(self) -> str:
        return "Mock class-based tool for AST regression testing."

    @property
    def parameters(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "enum": ["guarded", "unguarded"]},
                "param": {"type": "STRING"},
            },
        }

    def execute(self, parameters: dict, **context) -> ToolResult:
        action = str(parameters.get("action") or "").lower().strip()
        if action == "guarded":
            res = _mock_worker_action(parameters.get("param", ""))
            return ToolResult(success=True, tool=self.name, action=action, value=res)
        elif action == "unguarded":
            res = _mock_worker_unguarded(parameters.get("param", ""))
            return ToolResult(success=True, tool=self.name, action=action, value=res)
        return ToolResult(success=False, tool=self.name, action=action, error="Unknown action")


def test_indentation_poc_direct():
    """Confirms that inspect.getsource on bound method has leading indent and fails ast.parse without dedent."""
    tool = MockClassTool()
    bound_execute = tool.execute

    raw_src = inspect.getsource(bound_execute)
    # The source should start with whitespace indentation because execute() is inside class MockClassTool
    assert raw_src.startswith(" ") or raw_src.startswith("\t")

    with pytest.raises(IndentationError) as exc_info:
        ast.parse(raw_src)
    assert "unexpected indent" in str(exc_info.value)

    # With textwrap.dedent, it must parse without error
    dedented_src = textwrap.dedent(raw_src)
    parsed = ast.parse(dedented_src)
    assert isinstance(parsed, ast.Module)


def test_dedent_noop_on_module_functions():
    """Confirms that textwrap.dedent safely handles both bound methods and module functions."""
    reg = discover_actions(actions_dir=Path(__file__).resolve().parent.parent / "actions")
    assert len(reg.names()) == 17

    for name in sorted(reg.names()):
        rec = reg._actions[name]
        raw_src = inspect.getsource(rec.handler)
        dedented_src = textwrap.dedent(raw_src)
        if inspect.ismethod(rec.handler):
            # Migrated class-based tool: raw source is indented; dedent enables clean AST parsing
            assert raw_src.startswith(" ") or raw_src.startswith("\t")
            tree = ast.parse(dedented_src)
            assert isinstance(tree, ast.Module)
        else:
            # Plain module-level function: raw_src == dedented_src strictly holds
            assert raw_src == dedented_src, f"Module-level function {name} was unexpectedly changed by dedent!"
            tree1 = ast.dump(ast.parse(raw_src))
            tree2 = ast.dump(ast.parse(dedented_src))
            assert tree1 == tree2


def test_dual_discovery_and_permission_gate_audit(tmp_path):
    """
    Creates a temporary action file with MockClassTool exported as TOOL.
    Discovers it via action_loader, tests execution, and runs verify_permission_gates.
    """
    tool_file = tmp_path / "mock_class_action.py"
    tool_file.write_text(
        textwrap.dedent('''
        from core.tool import AgentTool, ToolResult
        from core import confirm

        def _execute_guarded(param: str = ""):
            return confirm.request(
                key="mock_perm_key",
                title="Guarded Operation",
                detail="Run guarded test",
                run=lambda: "OK",
            )

        def _execute_unguarded(param: str = ""):
            return "Unguarded OK"

        class FileBackedClassTool(AgentTool):
            @property
            def name(self) -> str:
                return "file_backed_tool"

            @property
            def description(self) -> str:
                return "Test file backed AgentTool."

            @property
            def parameters(self) -> dict:
                return {"type": "OBJECT", "properties": {"action": {"type": "STRING"}}}

            def execute(self, parameters: dict, **context):
                act = str(parameters.get("action") or "").lower().strip()
                if act == "guarded":
                    return _execute_guarded(parameters.get("param", ""))
                elif act == "unguarded":
                    return _execute_unguarded(parameters.get("param", ""))
                return "Unknown"

        TOOL = FileBackedClassTool()
        '''),
        encoding="utf-8",
    )

    reg = discover_actions(actions_dir=tmp_path)
    assert "file_backed_tool" in reg.names()
    rec = reg._actions["file_backed_tool"]
    assert rec.valid is True
    assert rec.error == ""

    # Test execution
    res = reg.run("file_backed_tool", {"action": "unguarded"})
    assert res == "Unguarded OK"

    # Test verify_permission_gates with CONFIRM rule pointing to 'guarded' action
    valid_rule = PolicyRule(
        tool="file_backed_tool",
        action="guarded",
        level=PermissionLevel.CONFIRM,
        reason="Test Guarded",
        key="mock_perm_key",
    )
    # Must succeed with zero error and verify key alignment
    verify_permission_gates(action_registry=reg, rules=[valid_rule], exempt_unmigrated=set())

    # Test key mismatch detection: policy expects wrong key
    bad_key_rule = PolicyRule(
        tool="file_backed_tool",
        action="guarded",
        level=PermissionLevel.CONFIRM,
        reason="Wrong Key Test",
        key="wrong_policy_key",
    )
    with pytest.raises(SecurityPolicyError) as exc_key:
        verify_permission_gates(action_registry=reg, rules=[bad_key_rule], exempt_unmigrated=set())
    assert "key-alignment invariant violated" in str(exc_key.value)

    # Test missing gate detection: policy expects confirm on unguarded action
    missing_gate_rule = PolicyRule(
        tool="file_backed_tool",
        action="unguarded",
        level=PermissionLevel.CONFIRM,
        reason="Missing Gate Test",
        key="mock_perm_key",
    )
    with pytest.raises(SecurityPolicyError) as exc_gate:
        verify_permission_gates(action_registry=reg, rules=[missing_gate_rule], exempt_unmigrated=set())
    assert "lacks a required 'confirm.request()' gate" in str(exc_gate.value)


def test_full_17_actions_permission_audit_passes():
    """Verify that all 17 default tools in actions/ pass verify_permission_gates() completely."""
    reg = discover_actions(actions_dir=Path(__file__).resolve().parent.parent / "actions")
    assert len(reg.names()) == 17
    # Must pass without raising SecurityPolicyError
    verify_permission_gates(action_registry=reg, rules=POLICY_RULES)


if __name__ == "__main__":
    pytest.main(["-v", __file__])
