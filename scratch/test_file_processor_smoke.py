"""
scratch/test_file_processor_smoke.py
====================================
Dedicated smoke test suite for actions/file_processor.py.
Verifies:
1. Fresh module import and AgentTool subclass export integrity.
2. Signature compatibility when invoked with all 4 _CTX_KEYS (speak, player, session_memory, response).
3. Parameter handling (missing file path, non-existent file path, and text file processing).
"""

import sys
import importlib
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tool import AgentTool
from core.action_loader import discover_actions


def test_file_processor_import_and_tool_export():
    """Verify fresh import and AgentTool subclass export structure."""
    if "actions.file_processor" in sys.modules:
        del sys.modules["actions.file_processor"]

    mod = importlib.import_module("actions.file_processor")
    assert hasattr(mod, "ACTION"), "file_processor module must export ACTION"
    assert hasattr(mod, "TOOL"), "file_processor module must export TOOL"
    assert isinstance(mod.ACTION, AgentTool), "ACTION must be an AgentTool instance"
    assert mod.ACTION.name == "file_processor"
    assert mod.TOOL["name"] == "file_processor"
    assert callable(mod.TOOL["handler"])


def test_file_processor_context_and_signature_compatibility():
    """Verify execute() accepts all 4 _CTX_KEYS without raising TypeError."""
    from actions.file_processor import ACTION

    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    # Missing file path returns safe prompt without error
    res_direct = ACTION.execute({}, **full_ctx)
    assert isinstance(res_direct, str)
    assert "No file path provided" in res_direct

    # Dispatch through action_loader registry with full context
    reg = discover_actions(Path(__file__).resolve().parent.parent / "actions")
    res_loader = reg.run("file_processor", {}, ctx=full_ctx)
    assert isinstance(res_loader, str)
    assert "No file path provided" in res_loader


def test_file_processor_file_guards_and_text_processing(tmp_path):
    """Verify missing file guard and execution on text file."""
    from actions.file_processor import ACTION

    full_ctx = {
        "speak": lambda text: None,
        "player": None,
        "session_memory": None,
        "response": None,
    }

    # Non-existent file
    res_missing = ACTION.execute({"file_path": "non_existent_file_98765.txt"}, **full_ctx)
    assert "File not found" in res_missing

    # Valid text file
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("Hello world from Mark LIV file processor test.", encoding="utf-8")

    res_valid = ACTION.execute({"file_path": str(sample_file), "action": "word_count"}, **full_ctx)
    assert isinstance(res_valid, str)
    assert "words" in res_valid.lower() or "character" in res_valid.lower() or "Done" in res_valid


if __name__ == "__main__":
    pytest.main(["-v", __file__])
