"""
scratch/test_web_search_smoke.py
================================
Dedicated smoke test suite for actions/web_search.py.
Verifies:
1. Fresh module import and AgentTool subclass export integrity.
2. Signature compatibility when invoked with all 4 _CTX_KEYS (speak, player, session_memory, response).
3. Parameter handling (empty query guard, search mode dispatch, compare mode dispatch).
"""

import sys
import importlib
from pathlib import Path
from unittest.mock import patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tool import AgentTool
from core.action_loader import discover_actions


def test_web_search_import_and_tool_export():
    """Verify fresh import and AgentTool subclass export structure."""
    if "actions.web_search" in sys.modules:
        del sys.modules["actions.web_search"]

    mod = importlib.import_module("actions.web_search")
    assert hasattr(mod, "ACTION"), "web_search module must export ACTION"
    assert hasattr(mod, "TOOL"), "web_search module must export TOOL"
    assert isinstance(mod.ACTION, AgentTool), "ACTION must be an AgentTool instance"
    assert mod.ACTION.name == "web_search"
    assert mod.TOOL["name"] == "web_search"
    assert callable(mod.TOOL["handler"])


def test_web_search_context_and_signature_compatibility():
    """Verify execute() accepts all 4 _CTX_KEYS without raising TypeError."""
    from actions.web_search import ACTION

    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    # Empty query returns safe prompt without error
    res_direct = ACTION.execute({}, **full_ctx)
    assert isinstance(res_direct, str)
    assert "Please provide a search query" in res_direct

    # Dispatch through action_loader registry with full context
    reg = discover_actions(Path(__file__).resolve().parent.parent / "actions")
    res_loader = reg.run("web_search", {}, ctx=full_ctx)
    assert isinstance(res_loader, str)
    assert "Please provide a search query" in res_loader


def test_web_search_mocked_execution():
    """Verify search and compare modes execute properly with mocked backends."""
    from actions.web_search import ACTION
    import actions.web_search as ws_mod

    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    with patch.object(ws_mod, "_search", return_value="Mocked search result for Python"):
        res = ACTION.execute({"query": "Python 3.11"}, **full_ctx)
        assert "Mocked search result for Python" in res

    with patch.object(ws_mod, "_compare", return_value="Mocked comparison: Item A vs Item B"):
        res = ACTION.execute({"items": ["Item A", "Item B"], "aspect": "price"}, **full_ctx)
        assert "Mocked comparison: Item A vs Item B" in res


if __name__ == "__main__":
    pytest.main(["-v", __file__])
