"""
scratch/test_send_message_smoke.py
==================================
Dedicated smoke test suite for actions/send_message.py.
Verifies:
1. Fresh module import and AgentTool subclass export integrity.
2. Signature compatibility when invoked with all 4 _CTX_KEYS (speak, player, session_memory, response).
3. Parameter handling (missing recipient/message guards, and contact resolution guard).
"""

import sys
import importlib
from pathlib import Path
from unittest.mock import patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tool import AgentTool
from core.action_loader import discover_actions


def test_send_message_import_and_tool_export():
    """Verify fresh import and AgentTool subclass export structure."""
    if "actions.send_message" in sys.modules:
        del sys.modules["actions.send_message"]

    mod = importlib.import_module("actions.send_message")
    assert hasattr(mod, "ACTION"), "send_message module must export ACTION"
    assert hasattr(mod, "TOOL"), "send_message module must export TOOL"
    assert isinstance(mod.ACTION, AgentTool), "ACTION must be an AgentTool instance"
    assert mod.ACTION.name == "send_message"
    assert mod.TOOL["name"] == "send_message"
    assert callable(mod.TOOL["handler"])


def test_send_message_context_and_signature_compatibility():
    """Verify execute() accepts all 4 _CTX_KEYS without raising TypeError."""
    from actions.send_message import ACTION

    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    # Missing recipient returns safe prompt without error
    res_direct = ACTION.execute({}, **full_ctx)
    assert isinstance(res_direct, str)
    assert "Please specify a recipient" in res_direct

    # Dispatch through action_loader registry with full context
    reg = discover_actions(Path(__file__).resolve().parent.parent / "actions")
    res_loader = reg.run("send_message", {}, ctx=full_ctx)
    assert isinstance(res_loader, str)
    assert "Please specify a recipient" in res_loader


def test_send_message_parameter_guards():
    """Verify missing message guard and contact resolution validation."""
    from actions.send_message import ACTION

    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    # Recipient provided but message missing
    res_no_msg = ACTION.execute({"receiver": "Alice"}, **full_ctx)
    assert "Please specify the message content" in res_no_msg

    # Both provided but pyautogui simulated as uninstalled or mock dispatch
    with patch("actions.send_message._PYAUTOGUI", False):
        res_no_gui = ACTION.execute(
            {"receiver": "Alice", "message_text": "Hello", "platform": "whatsapp"},
            **full_ctx
        )
        assert "PyAutoGUI is not installed" in res_no_gui


if __name__ == "__main__":
    pytest.main(["-v", __file__])
