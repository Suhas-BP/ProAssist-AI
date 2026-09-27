"""
scratch/test_dev_agent_smoke.py
===============================
Dedicated smoke test suite for actions/dev_agent.py.
Verifies:
1. Fresh module import and AgentTool export integrity.
2. Command classification logic (_classify_command).
3. Shell builtin intercepts ("ver", "cd") exercising platform and sys calls without NameError.
4. Top-level action handler entry point validation.
"""

import sys
import importlib
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tool import AgentTool


def test_dev_agent_import_and_tool_export():
    """Verify fresh import and AgentTool subclass export structure."""
    if "actions.dev_agent" in sys.modules:
        del sys.modules["actions.dev_agent"]

    dev_agent_mod = importlib.import_module("actions.dev_agent")

    assert hasattr(dev_agent_mod, "ACTION"), "dev_agent module must export ACTION"
    assert hasattr(dev_agent_mod, "TOOL"), "dev_agent module must export TOOL"
    assert isinstance(dev_agent_mod.ACTION, AgentTool), "ACTION must be an AgentTool instance"
    assert dev_agent_mod.ACTION.name == "dev_agent"
    assert dev_agent_mod.TOOL["name"] == "dev_agent"
    assert callable(dev_agent_mod.TOOL["handler"])


def test_dev_agent_command_classification():
    """Verify _classify_command categorizes safe, confirm, and blocked commands."""
    import actions.dev_agent as da

    # Blocked commands
    assert da._classify_command("rmdir /s /q c:\\") == "BLOCKED"
    assert da._classify_command("del /f /q *.*") == "BLOCKED"
    assert da._classify_command("format d:") == "BLOCKED"

    # Confirmation required commands
    assert da._classify_command("pip install requests") == "REQUIRES_CONFIRMATION"
    assert da._classify_command("python main.py") == "REQUIRES_CONFIRMATION"

    # Safe commands
    assert da._classify_command("dir") == "SAFE"
    assert da._classify_command("ver") == "SAFE"
    assert da._classify_command("python --version") == "SAFE"


def test_dev_agent_ver_builtin_intercept(tmp_path):
    """
    Verify 'ver' builtin interception executes without NameError (validating 'platform' import)
    and returns valid platform/windows version output.
    """
    import actions.dev_agent as da

    result = da._run_project("ver", project_dir=tmp_path, timeout=5)
    assert isinstance(result, str)
    assert result.startswith("STDOUT:\n")
    if sys.platform == "win32":
        assert "Microsoft Windows" in result
    else:
        assert len(result) > len("STDOUT:\n")


def test_dev_agent_cd_builtin_intercept(tmp_path):
    """Verify 'cd' builtin interception executes and returns project dir path."""
    import actions.dev_agent as da

    result = da._run_project("cd", project_dir=tmp_path, timeout=5)
    assert isinstance(result, str)
    assert result.startswith("STDOUT:\n")
    assert str(tmp_path.resolve()) in result


def test_dev_agent_empty_description_guard():
    """Verify dev_agent entry point safely handles empty description parameter."""
    import actions.dev_agent as da

    res_func = da.dev_agent({})
    assert "Please describe the project you want me to build" in res_func

    res_tool = da.ACTION.execute({})
    assert "Please describe the project you want me to build" in res_tool


if __name__ == "__main__":
    pytest.main(["-v", __file__])
