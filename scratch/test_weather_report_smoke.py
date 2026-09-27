"""
scratch/test_weather_report_smoke.py
====================================
Dedicated smoke test suite for actions/weather_report.py.
Verifies:
1. Fresh module import and AgentTool subclass export integrity.
2. Signature compatibility when invoked with all 4 _CTX_KEYS (speak, player, session_memory, response).
3. Parameter handling (missing city guard, query generation, and mocked execution).
"""

import sys
import importlib
from pathlib import Path
from unittest.mock import patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tool import AgentTool
from core.action_loader import discover_actions


def test_weather_report_import_and_tool_export():
    """Verify fresh import and AgentTool subclass export structure."""
    if "actions.weather_report" in sys.modules:
        del sys.modules["actions.weather_report"]

    mod = importlib.import_module("actions.weather_report")
    assert hasattr(mod, "ACTION"), "weather_report module must export ACTION"
    assert hasattr(mod, "TOOL"), "weather_report module must export TOOL"
    assert isinstance(mod.ACTION, AgentTool), "ACTION must be an AgentTool instance"
    assert mod.ACTION.name == "weather_report"
    assert mod.TOOL["name"] == "weather_report"
    assert callable(mod.TOOL["handler"])


def test_weather_report_context_and_signature_compatibility():
    """Verify execute() accepts all 4 _CTX_KEYS without raising TypeError."""
    from actions.weather_report import ACTION

    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    # Missing city returns safe prompt without error
    res_direct = ACTION.execute({}, **full_ctx)
    assert isinstance(res_direct, str)
    assert "city is missing" in res_direct

    # Dispatch through action_loader registry with full context
    reg = discover_actions(Path(__file__).resolve().parent.parent / "actions")
    res_loader = reg.run("weather_report", {}, ctx=full_ctx)
    assert isinstance(res_loader, str)
    assert "city is missing" in res_loader


def test_weather_report_mocked_execution():
    """Verify execution logic with mocked browser open."""
    from actions.weather_report import ACTION

    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    with patch("actions.weather_report.webbrowser.open", return_value=True):
        res = ACTION.execute({"city": "Tokyo", "time": "tomorrow"}, **full_ctx)
        assert "Showing the weather for Tokyo, tomorrow, sir." in res


if __name__ == "__main__":
    pytest.main(["-v", __file__])
