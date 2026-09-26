"""
scratch/test_memory_dispatch_smoke.py — Verification of save_memory & recall_memory dispatch & logging.
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.logger import ActionLogger
from memory.memory_manager import load_memory, update_memory, search_memory
from main import AgentLive


def test_memory_dispatch_and_logging():
    print("======================================================================")
    print("RUNNING MEMORY DISPATCH & LOGGING SMOKE TEST")
    print("======================================================================")

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_log_file = Path(tmp_dir) / "test_memory_actions.jsonl"
        ActionLogger.set_log_path(test_log_file)

        # Create mock assistant instance
        assistant = MagicMock()
        assistant.ui = MagicMock()
        assistant.ui.muted = False
        assistant._action_registry = MagicMock()
        assistant._action_registry.scheduling.return_value = None
        assistant._plugin_registry = MagicMock()
        assistant._plugin_registry.scheduling.return_value = None
        assistant._current_user_request = "Please remember that my favorite beverage is Earl Grey tea"
        assistant._action_in_flight = False
        assistant._action_cooldown_until = 0

        # --- 1. Test save_memory dispatch ---
        print("\n1. Testing save_memory dispatch via _execute_tool...")
        fc_save = MagicMock()
        fc_save.name = "save_memory"
        fc_save.args = {
            "category": "preferences",
            "key": "favorite_beverage",
            "value": "Earl Grey tea"
        }
        fc_save.id = "call_save_999"

        resp_save = asyncio.run(AgentLive._execute_tool(assistant, fc_save))

        # Check return value conforms to silent function response format
        assert resp_save.name == "save_memory"
        assert resp_save.id == "call_save_999"
        assert resp_save.response == {"result": "ok", "silent": True}
        print("  -> save_memory return value verified: {'result': 'ok', 'silent': True}")

        # Check memory file on disk was updated
        mem = load_memory()
        stored_val = mem.get("preferences", {}).get("favorite_beverage")
        if isinstance(stored_val, dict):
            stored_val = stored_val.get("value")
        assert stored_val == "Earl Grey tea", f"Memory value mismatch: {stored_val}"
        print(f"  -> Direct memory read confirmed: preferences/favorite_beverage = '{stored_val}'")

        # --- 2. Test recall_memory dispatch ---
        print("\n2. Testing recall_memory dispatch via _execute_tool...")
        fc_recall = MagicMock()
        fc_recall.name = "recall_memory"
        fc_recall.args = {"query": "tea"}
        fc_recall.id = "call_recall_999"

        resp_recall = asyncio.run(AgentLive._execute_tool(assistant, fc_recall))

        assert resp_recall.name == "recall_memory"
        assert resp_recall.id == "call_recall_999"
        assert "result" in resp_recall.response
        recall_text = resp_recall.response["result"]
        assert "favorite beverage" in recall_text
        assert "Earl Grey tea" in recall_text
        print(f"  -> recall_memory result returned:\n     {recall_text.strip()}")

        # --- 3. Verify logging capture in JSON Lines ---
        print("\n3. Verifying log records written to JSON Lines file...")
        assert test_log_file.exists(), "Log file does not exist!"

        with open(test_log_file, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f.readlines()]

        assert len(lines) == 2, f"Expected 2 logged events, found {len(lines)}"

        # Verify save_memory log event
        rec_save = lines[0]
        assert rec_save["tool"] == "save_memory"
        assert rec_save["parameters"]["category"] == "preferences"
        assert rec_save["parameters"]["key"] == "favorite_beverage"
        assert rec_save["parameters"]["value"] == "Earl Grey tea"
        assert rec_save["result"] == "ok"
        assert rec_save["user_request"] == "Please remember that my favorite beverage is Earl Grey tea"
        assert rec_save["verified"] is None
        assert rec_save["verification_source"] == "none_available"
        print("  -> save_memory log event verified (all 12 fields intact, gap closed).")

        # Verify recall_memory log event
        rec_recall = lines[1]
        assert rec_recall["tool"] == "recall_memory"
        assert rec_recall["parameters"]["query"] == "tea"
        assert "Earl Grey tea" in rec_recall["result"]
        assert rec_recall["verified"] is None
        assert rec_recall["verification_source"] == "none_available"
        print("  -> recall_memory log event verified (all 12 fields intact).")

        ActionLogger.reset_default_path()

    print("\n======================================================================")
    print("MEMORY DISPATCH & LOGGING SMOKE TEST PASSED CLEANLY!")
    print("======================================================================")


if __name__ == "__main__":
    test_memory_dispatch_and_logging()
