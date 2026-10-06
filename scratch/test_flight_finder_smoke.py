"""
scratch/test_flight_finder_smoke.py
===================================
Dedicated smoke test suite for actions/flight_finder.py.
Verifies:
1. Fresh module import and AgentTool subclass export integrity.
2. Signature compatibility when invoked with all 4 _CTX_KEYS (speak, player, session_memory, response).
3. Parameter handling (missing parameter guards).
4. Network layer isolation: mocks browser search and Gemini parser to guarantee zero live endpoint traffic.
"""

import sys
import importlib
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tool import AgentTool
from core.action_loader import discover_actions


def test_flight_finder_import_and_tool_export():
    """Verify fresh import and AgentTool subclass export structure."""
    if "actions.flight_finder" in sys.modules:
        del sys.modules["actions.flight_finder"]

    mod = importlib.import_module("actions.flight_finder")
    assert hasattr(mod, "ACTION"), "flight_finder module must export ACTION"
    assert hasattr(mod, "TOOL"), "flight_finder module must export TOOL"
    assert isinstance(mod.ACTION, AgentTool), "ACTION must be an AgentTool instance"
    assert mod.ACTION.name == "flight_finder"
    assert mod.TOOL["name"] == "flight_finder"
    assert callable(mod.TOOL["handler"])


def test_flight_finder_context_and_signature_compatibility():
    """Verify execute() accepts all 4 _CTX_KEYS without raising TypeError."""
    from actions.flight_finder import ACTION

    mock_speak = MagicMock()
    full_ctx = {
        "speak": mock_speak,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    # Missing origin/destination returns safe prompt without error
    res_direct = ACTION.execute({}, **full_ctx)
    assert isinstance(res_direct, str)
    assert "Please provide both origin and destination" in res_direct

    # Dispatch through action_loader registry with full context
    reg = discover_actions(Path(__file__).resolve().parent.parent / "actions")
    res_loader = reg.run("flight_finder", {}, ctx=full_ctx)
    assert isinstance(res_loader, str)
    assert "Please provide both origin and destination" in res_loader


def test_flight_finder_mocked_network_execution():
    """Verify execution logic with mocked browser search and parser (zero network traffic)."""
    from actions.flight_finder import ACTION
    import actions.flight_finder as ff_mod

    mock_speak = MagicMock()
    full_ctx = {
        "speak": mock_speak,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    sample_flights = [
        {
            "airline": "British Airways",
            "price": "$650",
            "departure": "08:00",
            "arrival": "20:00",
            "duration": "7h 0m",
            "stops": 0,
        }
    ]

    with patch.object(ff_mod, "_search_flights_browser", return_value=("mock html text", "https://flights.google.com/test")), \
         patch.object(ff_mod, "_parse_flights_with_gemini", return_value=sample_flights):
        res = ACTION.execute(
            {"origin": "JFK", "destination": "LHR", "date": "2026-10-01"},
            **full_ctx
        )
        assert "British Airways" in res
        assert mock_speak.called


if __name__ == "__main__":
    pytest.main(["-v", __file__])
