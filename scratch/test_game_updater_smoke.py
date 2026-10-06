"""
scratch/test_game_updater_smoke.py
==================================
Dedicated smoke test suite for actions/game_updater.py.
Verifies:
1. Fresh module import and AgentTool subclass export integrity.
2. Signature compatibility when invoked with all 4 _CTX_KEYS (speak, player, session_memory, response).
3. Parameter handling (unknown action guard, schedule_status, and platform listing).
"""

import sys
import importlib
from pathlib import Path
from unittest.mock import patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tool import AgentTool
from core.action_loader import discover_actions


def test_game_updater_import_and_tool_export():
    """Verify fresh import and AgentTool subclass export structure."""
    if "actions.game_updater" in sys.modules:
        del sys.modules["actions.game_updater"]

    mod = importlib.import_module("actions.game_updater")
    assert hasattr(mod, "ACTION"), "game_updater module must export ACTION"
    assert hasattr(mod, "TOOL"), "game_updater module must export TOOL"
    assert isinstance(mod.ACTION, AgentTool), "ACTION must be an AgentTool instance"
    assert mod.ACTION.name == "game_updater"
    assert mod.TOOL["name"] == "game_updater"
    assert callable(mod.TOOL["handler"])


def test_game_updater_context_and_signature_compatibility():
    """Verify execute() accepts all 4 _CTX_KEYS without raising TypeError."""
    from actions.game_updater import ACTION

    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    # Unknown action returns graceful error message without exception
    res_direct = ACTION.execute({"action": "invalid_action"}, **full_ctx)
    assert isinstance(res_direct, str)
    assert "Unknown action" in res_direct

    # Dispatch through action_loader registry with full context
    reg = discover_actions(Path(__file__).resolve().parent.parent / "actions")
    res_loader = reg.run("game_updater", {"action": "invalid_action"}, ctx=full_ctx)
    assert isinstance(res_loader, str)
    assert "Unknown action" in res_loader


def test_game_updater_schedule_status():
    """Verify schedule_status query executes cleanly."""
    from actions.game_updater import ACTION

    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    res = ACTION.execute({"action": "schedule_status"}, **full_ctx)
    assert isinstance(res, str)
    assert "update" in res.lower() or "schedule" in res.lower()


def test_game_updater_mocked_list():
    """Verify list action executes cleanly when platforms are simulated as uninstalled."""
    from actions.game_updater import ACTION
    import actions.game_updater as gu_mod

    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    with patch.object(gu_mod, "_find_steam_path", return_value=None), \
         patch.object(gu_mod, "_find_epic_exe", return_value=None):
        res = ACTION.execute({"action": "list", "platform": "both"}, **full_ctx)
        assert "Steam: Not installed." in res


if __name__ == "__main__":
    pytest.main(["-v", __file__])
