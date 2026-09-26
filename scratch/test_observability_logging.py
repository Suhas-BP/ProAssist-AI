"""
scratch/test_observability_logging.py — Comprehensive Test Suite for Item 1 (Observability / logs/)

Covers:
1. Field completeness of logged records.
2. Secret scrubbing (Part A: 0 false positives on safe codebase strings, 100% redaction of real secrets).
3. Explicit verification semantics (Part B: real evidence -> verified=True, plain/query -> verified=None/null, blocked/error -> verified=False).
4. Thread safety under concurrent executor threads (Part C: 25 threads x 10 writes = 250 concurrent events, 0 corrupted/interleaved).
5. Rotation and retention (size cap rollover and backup count limit).
6. End-to-end integration via ActionLogger.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.logger import ActionLogger, scrub_text, scrub_secrets, determine_verification
from core.permission_manager import check_permission, PermissionLevel


def test_part_a_secret_scrubbing_and_false_positives():
    print("\n--- Test 1: Part A Secret Scrubbing & False-Positive Avoidance ---")
    
    # 1. Safe codebase strings (must NOT be redacted)
    safe_strings = [
        "AGENTReminder_20260925_175222_9b39",
        "rem_20260925_175222_9b39",
        "PID 21964",
        "ref='PID 11148'",
        "pid_or_window='Target Service - Main Window'",
        r"C:\Users\santh\AppData\Local\Temp\test_downloads_zqz7ceul\Downloads\College",
        r"data/captures/capture_20260926_174000.jpg",
        "Desktop Archive 2026-09-26",
        "reminders.json",
        "https://example.com/images/nature_mountain.png",
        "Master volume is at 80%.",
        "Successfully opened Calculator (PID 21964).",
    ]

    for s in safe_strings:
        scrubbed = scrub_text(s)
        assert scrubbed == s, f"False positive! '{s}' was modified to '{scrubbed}'"

    print("  -> Passed: 0 false positives across all real codebase artifacts.")

    # 2. Real secret patterns (MUST be redacted)
    secrets_to_test = [
        ("AIzaSyD-1234567890abcdefghijklmnopqrstuv", "[REDACTED_API_KEY]"),
        ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdefg12345", "Bearer [REDACTED_TOKEN]"),
        ("sk-proj-abc123xyz45678901234567890", "[REDACTED_TOKEN]"),
        ("ghp_123456789012345678901234567890123456", "[REDACTED_TOKEN]"),
        ("4532-1234-5678-9012", "[REDACTED_CARD]"),
        ("4532 1234 5678 9012", "[REDACTED_CARD]"),
        ("api_key=my_super_secret_production_key_12345", 'api_key="[REDACTED_SECRET]"'),
        ("password='super_secure_password_99'", 'password="[REDACTED_SECRET]"'),
    ]

    for raw, expected_substr in secrets_to_test:
        scrubbed = scrub_text(raw)
        assert expected_substr in scrubbed, f"Secret not redacted! Expected {expected_substr} in '{scrubbed}'"
        assert raw not in scrubbed, f"Raw secret leaked into scrubbed output: '{scrubbed}'"

    # 3. Recursive dictionary scrubbing
    nested_data = {
        "user": "alice",
        "api_key": "raw_sensitive_key_9999",
        "auth": {"token": "secret_token_12345678"},
        "details": ["normal text", "sk-live-1234567890abcdefghijklmn"],
    }
    scrubbed_dict = scrub_secrets(nested_data)
    assert scrubbed_dict["api_key"] == "[REDACTED_SECRET]"
    assert scrubbed_dict["auth"]["token"] == "[REDACTED_SECRET]"
    assert scrubbed_dict["details"][1] == "[REDACTED_TOKEN]"
    assert scrubbed_dict["user"] == "alice"

    print("  -> Passed: 100% of real secret patterns correctly redacted.")


def test_part_b_verification_semantics():
    print("\n--- Test 2: Part B Verification Semantics ---")

    # Case 1: Genuine evidence -> verified: True
    # open_app with PID lifecycle
    v1, src1, det1 = determine_verification(
        tool="open_app",
        action="open",
        result={"success": True, "pid_or_window": "PID 12345", "message": "Successfully launched"},
    )
    assert v1 is True
    assert src1 == "psutil_pid_check"
    assert "PID 12345" in det1

    # file_controller create_file
    v2, src2, det2 = determine_verification(
        tool="file_controller",
        action="create_file",
        result="File created: notes.txt",
    )
    assert v2 is True
    assert src2 == "file_exists_check"

    # reminder create
    v3, src3, det3 = determine_verification(
        tool="reminder",
        action="create",
        result={"success": True, "value": {"task_name": "AGENTReminder_20260926_010203_abcd"}},
    )
    assert v3 is True
    assert src3 == "task_scheduler_query"
    assert "AGENTReminder" in det3

    # browser_control download
    v4, src4, det4 = determine_verification(
        tool="browser_control",
        action="download",
        result="Download complete: report.pdf (204800 bytes)",
    )
    assert v4 is True
    assert src4 == "download_file_size_check"

    print("  -> Passed: Genuine evidence correctly yields verified=True and specific source.")

    # Case 2: Plain query/result with no evidence -> verified: None (null in JSON)
    v5, src5, det5 = determine_verification(
        tool="web_search",
        action="search",
        result="Results for quantum computing...",
    )
    assert v5 is None
    assert src5 == "none_available"

    v6, src6, det6 = determine_verification(
        tool="reminder",
        action="list",
        result={"success": True, "value": []},
    )
    assert v6 is None
    assert src6 == "none_available"

    print("  -> Passed: Plain queries yield verified=None (null in JSON) and none_available.")

    # Case 3: Blocked call -> verified: False, source: policy_gate
    v7, src7, det7 = determine_verification(
        tool="dev_agent",
        action="execute_shell",
        result="[BLOCKED] Operation not permitted: Format command is strictly blocked",
        is_blocked=True,
    )
    assert v7 is False
    assert src7 == "policy_gate"

    # Case 4: Exception -> verified: False, source: exception
    v8, src8, det8 = determine_verification(
        tool="file_controller",
        action="write",
        result="Tool 'file_controller' failed: Permission denied",
        error="Permission denied",
    )
    assert v8 is False
    assert src8 == "exception"

    print("  -> Passed: Blocked and error calls yield verified=False with explicit failure source.")


def test_part_c_thread_safety_concurrency():
    print("\n--- Test 3: Part C Concurrency & Thread-Safety ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_log_path = Path(tmp_dir) / "test_concurrent.jsonl"
        ActionLogger.set_log_path(test_log_path)

        num_threads = 25
        calls_per_thread = 10
        total_expected = num_threads * calls_per_thread

        def worker(thread_idx: int):
            for i in range(calls_per_thread):
                ActionLogger.log_event(
                    tool="test_tool",
                    action=f"action_{i}",
                    parameters={"thread": thread_idx, "call": i, "token": "sk-test123456789012345678"},
                    result={"status": "ok", "thread": thread_idx, "i": i},
                    user_request=f"Thread {thread_idx} request {i}",
                )

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Check results
        assert test_log_path.exists(), "Log file was not created!"
        with open(test_log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == total_expected, f"Expected {total_expected} lines, got {len(lines)}"

        # Validate that every single line is clean, valid, non-corrupted JSON
        for idx, line in enumerate(lines):
            try:
                record = json.loads(line)
            except Exception as e:
                raise AssertionError(f"Corrupted/interleaved JSON at line {idx + 1}: {line}") from e

            assert record["tool"] == "test_tool"
            assert record["parameters"]["token"] in ("[REDACTED_SECRET]", "[REDACTED_TOKEN]")
            assert "verified" in record
            assert "verification_source" in record

        print(f"  -> Passed: {total_expected} concurrent events written across {num_threads} threads.")
        print("  -> Passed: 100% of lines are intact, valid JSON with zero corruption/interleaving.")
        ActionLogger.reset_default_path()


def test_rotation_and_retention():
    print("\n--- Test 4: Log File Rotation and Disk Cap Retention ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_log_path = Path(tmp_dir) / "rotate_test.jsonl"
        # Set a small 2 KB cap with 3 backups (max ~8 KB total)
        cap = 2 * 1024
        backups = 3
        ActionLogger.set_log_path(test_log_path, max_bytes=cap, backup_count=backups)

        # Write enough lines to trigger multiple rollovers
        for i in range(80):
            ActionLogger.log_event(
                tool="stress_tool",
                action="write_data",
                parameters={"index": i, "payload": "A" * 150},
                result={"status": "ok", "i": i},
                user_request="stress rotation test",
            )

        # Verify main log exists
        assert test_log_path.exists(), "Main log file does not exist"
        assert test_log_path.stat().st_size <= cap + 500  # within margin of 1 line

        # Verify rotated backup files exist
        b1 = Path(f"{test_log_path}.1")
        b2 = Path(f"{test_log_path}.2")
        b3 = Path(f"{test_log_path}.3")
        b4 = Path(f"{test_log_path}.4")

        assert b1.exists(), "Backup .1 does not exist"
        assert b2.exists(), "Backup .2 does not exist"
        assert b3.exists(), "Backup .3 does not exist"
        assert not b4.exists(), "Backup .4 should not exist (backup_count=3 limit exceeded)"

        # Verify every line in all files parses as valid JSON
        for fpath in [test_log_path, b1, b2, b3]:
            with open(fpath, "r", encoding="utf-8") as f:
                for line_idx, line in enumerate(f):
                    assert line.endswith("\n")
                    record = json.loads(line)
                    assert record["tool"] == "stress_tool"

        print("  -> Passed: Size cap rotation triggers cleanly, backup files .1, .2, .3 intact.")
        print("  -> Passed: Max backup count respected (backup .4 does not exist).")
        ActionLogger.reset_default_path()


def test_field_completeness_and_sample_records():
    print("\n--- Test 5: Field Completeness & Sample Record Generation ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_log_path = Path(tmp_dir) / "sample_records.jsonl"
        ActionLogger.set_log_path(test_log_path)

        # Sample 1: Genuine verification evidence (open_app)
        rec1 = ActionLogger.log_event(
            tool="open_app",
            action="launch",
            parameters={"app_name": "notepad"},
            permission={"level": "SAFE", "reason": "Application launch"},
            result={"success": True, "app": "notepad.exe", "pid_or_window": "PID 31415", "message": "Successfully opened notepad"},
            user_request="Open notepad for me",
        )

        # Sample 2: Plain result / no verification evidence (web_search)
        rec2 = ActionLogger.log_event(
            tool="web_search",
            action="search",
            parameters={"query": "weather forecast"},
            permission={"level": "SAFE", "reason": "Web query"},
            result="Sunny with high of 24C",
            user_request="What's the weather today?",
        )

        # Sample 3: Blocked call (dev_agent)
        rec3 = ActionLogger.log_event(
            tool="dev_agent",
            action="execute_shell",
            parameters={"command": "format c:"},
            permission={"level": "BLOCKED", "reason": "Drive formatting is prohibited"},
            result="[BLOCKED] Operation not permitted: Drive formatting is prohibited",
            user_request="Format my drive",
        )

        with open(test_log_path, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f.readlines()]

        assert len(lines) == 3

        # Check required fields
        required_fields = [
            "timestamp", "user_request", "plan", "tool", "action",
            "parameters", "permission", "result", "error",
            "verified", "verification_source", "verification_details"
        ]
        for line in lines:
            for field in required_fields:
                assert field in line, f"Missing field '{field}' in log record!"

        # Check specific semantics
        assert lines[0]["verified"] is True
        assert lines[0]["verification_source"] == "psutil_pid_check"
        assert "PID 31415" in lines[0]["verification_details"]

        assert lines[1]["verified"] is None
        assert lines[1]["verification_source"] == "none_available"

        assert lines[2]["verified"] is False
        assert lines[2]["verification_source"] == "policy_gate"

        print("  -> Passed: All 12 required fields present in every record.")
        print("\n--- PART B Sample Logged JSON Lines ---")
        for i, l in enumerate(lines, 1):
            print(f"Sample {i} ({l['tool']}):")
            print(json.dumps(l, indent=2))

        ActionLogger.reset_default_path()


def test_main_execute_tool_hook():
    print("\n--- Test 6: main.py::_execute_tool Hook Integration ---")
    import asyncio
    from unittest.mock import MagicMock
    from main import AgentLive

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_log_path = Path(tmp_dir) / "hook_test.jsonl"
        ActionLogger.set_log_path(test_log_path)

        # Create minimal mock of AgentLive instance
        assistant = MagicMock()
        assistant.ui = MagicMock()
        assistant.ui.muted = True
        assistant._action_registry = MagicMock()
        assistant._action_registry.scheduling.return_value = None
        assistant._plugin_registry = MagicMock()
        assistant._plugin_registry.scheduling.return_value = None
        assistant._current_user_request = "Remember that I like tea"
        assistant._action_in_flight = False
        assistant._action_cooldown_until = 0

        # Test: save_memory call through _execute_tool
        fc_save = MagicMock()
        fc_save.name = "save_memory"
        fc_save.args = {"category": "notes", "key": "beverage", "value": "tea"}
        fc_save.id = "call_save_1"

        resp = asyncio.run(AgentLive._execute_tool(assistant, fc_save))
        assert resp.response["result"] == "ok"

        # Check that log was written to disk
        with open(test_log_path, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f.readlines()]

        assert len(lines) == 1
        assert lines[0]["tool"] == "save_memory"
        assert lines[0]["user_request"] == "Remember that I like tea"
        assert lines[0]["result"] == "ok"
        print("  -> Passed: AgentLive._execute_tool correctly logged event via ActionLogger hook.")
        ActionLogger.reset_default_path()


if __name__ == "__main__":
    print("======================================================================")
    print("RUNNING ITEM 1 (OBSERVABILITY / LOGS/) DEDICATED TEST SUITE")
    print("======================================================================")
    test_part_a_secret_scrubbing_and_false_positives()
    test_part_b_verification_semantics()
    test_part_c_thread_safety_concurrency()
    test_rotation_and_retention()
    test_field_completeness_and_sample_records()
    test_main_execute_tool_hook()
    print("\n======================================================================")
    print("ALL ITEM 1 OBSERVABILITY TESTS PASSED CLEANLY!")
    print("======================================================================")

