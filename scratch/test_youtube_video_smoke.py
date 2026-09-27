"""
scratch/test_youtube_video_smoke.py
===================================
Dedicated smoke test suite for actions/youtube_video.py.
Verifies:
1. Fresh module import and AgentTool subclass export integrity.
2. Signature compatibility when invoked with all 4 _CTX_KEYS (speak, player, session_memory, response).
3. Parameter handling (empty play query guard, unknown action rejection, and mocked trending execution).
"""

import sys
import importlib
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tool import AgentTool
from core.action_loader import discover_actions


def test_youtube_video_import_and_tool_export():
    """Verify fresh import and AgentTool subclass export structure."""
    if "actions.youtube_video" in sys.modules:
        del sys.modules["actions.youtube_video"]

    mod = importlib.import_module("actions.youtube_video")
    assert hasattr(mod, "ACTION"), "youtube_video module must export ACTION"
    assert hasattr(mod, "TOOL"), "youtube_video module must export TOOL"
    assert isinstance(mod.ACTION, AgentTool), "ACTION must be an AgentTool instance"
    assert mod.ACTION.name == "youtube_video"
    assert mod.TOOL["name"] == "youtube_video"
    assert callable(mod.TOOL["handler"])


def test_youtube_video_context_and_signature_compatibility():
    """Verify execute() accepts all 4 _CTX_KEYS without raising TypeError."""
    from actions.youtube_video import ACTION

    mock_speak = MagicMock()
    full_ctx = {
        "speak": mock_speak,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    # Unknown action returns graceful error without exception
    res_direct = ACTION.execute({"action": "unknown_action"}, **full_ctx)
    assert isinstance(res_direct, str)
    assert "Unknown YouTube action" in res_direct

    # Dispatch through action_loader registry with full context
    reg = discover_actions(Path(__file__).resolve().parent.parent / "actions")
    res_loader = reg.run("youtube_video", {"action": "unknown_action"}, ctx=full_ctx)
    assert isinstance(res_loader, str)
    assert "Unknown YouTube action" in res_loader


def test_youtube_video_empty_play_query_guard():
    """Verify play action with empty query returns expected guidance."""
    from actions.youtube_video import ACTION

    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    res = ACTION.execute({"action": "play", "query": ""}, **full_ctx)
    assert "Please tell me what you'd like to watch" in res


def test_youtube_video_trending_mocked_execution():
    """Verify trending action execution and speak callback dispatch."""
    from actions.youtube_video import ACTION
    import actions.youtube_video as yt_mod

    mock_speak = MagicMock()
    full_ctx = {
        "speak": mock_speak,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    fake_trending = [
        {"rank": 1, "title": "Top Tech Video", "channel": "TechChannel"},
        {"rank": 2, "title": "AI Breakthrough", "channel": "AIChannel"},
    ]

    with patch.object(yt_mod, "_scrape_trending", return_value=fake_trending):
        res = ACTION.execute({"action": "trending", "region": "US"}, **full_ctx)
        assert "Top trending videos in US:" in res
        assert "Top Tech Video" in res
        assert mock_speak.called


if __name__ == "__main__":
    pytest.main(["-v", __file__])
