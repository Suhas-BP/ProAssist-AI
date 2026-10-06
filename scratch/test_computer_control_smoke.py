"""
scratch/test_computer_control_smoke.py
=======================================
Dedicated smoke test suite for actions/computer_control.py.
Verifies:
1. Fresh module import and AgentTool subclass export integrity.
2. Signature compatibility when invoked with all 4 _CTX_KEYS (speak, player, session_memory, response),
   verifying that 'speak' (which worker rejects) is cleanly omitted without TypeError.
3. Safe parameter execution (wait and random_data actions) and action_loader registry dispatch.
"""

import sys
import importlib
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tool import AgentTool
from core.action_loader import discover_actions


def test_computer_control_import_and_tool_export():
    """Verify fresh import and AgentTool subclass export structure."""
    if "actions.computer_control" in sys.modules:
        del sys.modules["actions.computer_control"]

    mod = importlib.import_module("actions.computer_control")
    assert hasattr(mod, "ACTION"), "computer_control module must export ACTION"
    assert hasattr(mod, "TOOL"), "computer_control module must export TOOL"
    assert isinstance(mod.ACTION, AgentTool), "ACTION must be an AgentTool instance"
    assert mod.ACTION.name == "computer_control"
    assert mod.TOOL["name"] == "computer_control"
    assert callable(mod.TOOL["handler"])


def test_computer_control_context_and_signature_compatibility():
    """Verify execute() accepts all 4 _CTX_KEYS without raising TypeError."""
    from actions.computer_control import ACTION

    full_ctx = {
        "speak": lambda text: None,  # Not accepted by computer_control worker
        "player": None,
        "session_memory": None,
        "response": None,
    }

    # Direct tool execution with all 4 _CTX_KEYS
    res_direct = ACTION.execute({"action": "wait", "seconds": 0.01}, **full_ctx)
    assert isinstance(res_direct, str)
    assert "Waited" in res_direct

    # Dispatch through action_loader registry with full context
    reg = discover_actions(Path(__file__).resolve().parent.parent / "actions")
    res_loader = reg.run("computer_control", {"action": "wait", "seconds": 0.01}, ctx=full_ctx)
    assert isinstance(res_loader, str)
    assert "Waited" in res_loader


def test_computer_control_safe_action_execution():
    """Verify safe non-hardware actions like random_data and error handling."""
    from actions.computer_control import ACTION

    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    # random_data generates synthetic name
    res_name = ACTION.execute({"action": "random_data", "type": "name"}, **full_ctx)
    assert isinstance(res_name, str)
    assert len(res_name) > 0

    # Unknown action returns graceful message rather than unhandled exception
    res_unknown = ACTION.execute({"action": "nonexistent_action_xyz"}, **full_ctx)
    assert "Unknown action" in res_unknown or "failed" in res_unknown


if __name__ == "__main__":
    pytest.main(["-v", __file__])
