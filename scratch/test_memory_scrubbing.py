"""
scratch/test_memory_scrubbing.py — Dedicated Test Suite for Item 2 (Section 21: Memory Secret-Scrubbing)

Covers:
1. Secret scrubbing on update_memory, remember, and direct memory writes.
2. False-positive checks on safe personal memories (addresses, numbers, task names).
3. Secret scrubbing on session summaries (save_session_summary).
4. Scrub-on-load sanitization for pre-existing secrets in memory files.
5. Preference tracking helpers (preferred_download_dir, app_usage_frequency, automation_preferences).
6. Schema reconciliation & prompt formatting integrity (format_memory_for_prompt).
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import memory.memory_manager as mm


def test_1_secret_scrubbing_on_memory_updates():
    print("\n--- Test 1: Secret Scrubbing on Memory Updates ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_mem_file = Path(tmp_dir) / "test_memory.json"
        orig_path = mm.MEMORY_PATH
        mm.MEMORY_PATH = test_mem_file

        try:
            # 1. Update memory with various real secret patterns in values
            mm.update_memory({
                "preferences": {
                    "google_key": {"value": "My key is AIzaSyD-1234567890abcdefghijklmnopqrstuv"},
                    "bearer_header": {"value": "Use Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdefg12345"},
                    "openai_model": {"value": "Key sk-proj-abc123xyz45678901234567890 here"},
                    "card_num": {"value": "Card 4532 1234 5678 9012 for billing"},
                },
                "notes": {
                    "kv_secret": {"value": "api_key=my_super_secret_production_key_12345"},
                }
            })

            # 2. Update memory where the key itself indicates a credential
            mm.remember(key="wifi_password", value="MySecretPassword99!", category="notes")
            mm.remember(key="db_auth_token", value="custom_token_val_1234", category="notes")

            # Verify contents written to disk
            assert test_mem_file.exists(), "Memory file was not written!"
            disk_data = json.loads(test_mem_file.read_text(encoding="utf-8"))

            pref = disk_data.get("preferences", {})
            assert "[REDACTED_API_KEY]" in pref["google_key"]["value"]
            assert "AIzaSyD" not in pref["google_key"]["value"]

            assert "[REDACTED_TOKEN]" in pref["bearer_header"]["value"]
            assert "eyJhbGciOi" not in pref["bearer_header"]["value"]

            assert "[REDACTED_TOKEN]" in pref["openai_model"]["value"]
            assert "sk-proj" not in pref["openai_model"]["value"]

            assert "[REDACTED_CARD]" in pref["card_num"]["value"]
            assert "4532 1234" not in pref["card_num"]["value"]

            notes = disk_data.get("notes", {})
            assert '[REDACTED_SECRET]' in notes["kv_secret"]["value"]
            assert "my_super_secret" not in notes["kv_secret"]["value"]

            assert notes["wifi_password"]["value"] == "[REDACTED_SECRET]"
            assert notes["db_auth_token"]["value"] == "[REDACTED_SECRET]"

            print("  -> Passed: All secret patterns and sensitive keys redacted before disk write.")
        finally:
            mm.MEMORY_PATH = orig_path


def test_2_false_positive_avoidance():
    print("\n--- Test 2: False-Positive Avoidance on Safe Memories ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_mem_file = Path(tmp_dir) / "test_memory.json"
        orig_path = mm.MEMORY_PATH
        mm.MEMORY_PATH = test_mem_file

        try:
            safe_entries = {
                "identity": {
                    "address": {"value": "1234 Main St, Apt 5B"},
                    "phone_note": {"value": "office extension ends in 9b39"},
                    "favorite_food": {"value": "Margherita pizza with basil"},
                },
                "notes": {
                    "task_reference": {"value": "AGENTReminder_20260925_175222_9b39"},
                    "system_msg": {"value": "Master volume is at 80% (PID 21964)"},
                }
            }

            mm.update_memory(safe_entries)

            disk_data = json.loads(test_mem_file.read_text(encoding="utf-8"))
            for cat, items in safe_entries.items():
                for k, v in items.items():
                    actual = disk_data[cat][k]["value"]
                    expected = v["value"]
                    assert actual == expected, f"False positive! '{expected}' changed to '{actual}'"

            print("  -> Passed: 0 false positives across real non-secret memories.")
        finally:
            mm.MEMORY_PATH = orig_path


def test_3_session_summary_scrubbing():
    print("\n--- Test 3: Session Summary Secret Scrubbing ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_mem_file = Path(tmp_dir) / "test_memory.json"
        orig_path = mm.MEMORY_PATH
        mm.MEMORY_PATH = test_mem_file

        try:
            raw_summary = "User configured token sk-proj-1234567890abcdefghijklmn and asked for weather."
            mm.save_session_summary(raw_summary, language="en")

            disk_data = json.loads(test_mem_file.read_text(encoding="utf-8"))
            sessions = disk_data.get("sessions", [])
            assert len(sessions) == 1
            saved_summary = sessions[0]["summary"]

            assert "[REDACTED_TOKEN]" in saved_summary
            assert "sk-proj-1234567890" not in saved_summary
            print(f"  -> Session summary successfully scrubbed: '{saved_summary}'")
        finally:
            mm.MEMORY_PATH = orig_path


def test_4_scrub_on_load_migration():
    print("\n--- Test 4: Scrub-on-Load Sanitization & Migration Safety ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_mem_file = Path(tmp_dir) / "test_memory.json"
        orig_path = mm.MEMORY_PATH
        mm.MEMORY_PATH = test_mem_file

        try:
            # Seed file with raw unscrubbed data (simulating a legacy memory file)
            legacy_data = {
                "identity": {
                    "name": {"value": "Alice", "updated": "2026-09-01"},
                },
                "preferences": {
                    "api_key": {"value": "AIzaSyD-1234567890abcdefghijklmnopqrstuv", "updated": "2026-09-01"},
                    "db_password": {"value": "plain_password_12345", "updated": "2026-09-01"},
                },
                "sessions": [
                    {"date": "2026-09-01", "summary": "Setup key ghp_123456789012345678901234567890123456 for git"}
                ]
            }
            seeded_text = json.dumps(legacy_data, indent=2)
            test_mem_file.write_text(seeded_text, encoding="utf-8")

            # First load: triggers migration
            loaded = mm.load_memory()
            assert loaded["preferences"]["api_key"]["value"] == "[REDACTED_SECRET]"
            assert loaded["preferences"]["db_password"]["value"] == "[REDACTED_SECRET]"
            assert "[REDACTED_TOKEN]" in loaded["sessions"][0]["summary"]
            assert loaded["identity"]["name"]["value"] == "Alice"

            # (a) Proof a backup file was created matching pre-migration content exactly
            backup_file = test_mem_file.with_suffix(".json.bak")
            assert backup_file.exists(), "Backup file must be created during migration!"
            backup_content = backup_file.read_text(encoding="utf-8")
            assert backup_content == seeded_text, "Backup content must match pre-migration content byte-for-byte!"
            print(f"  -> (a) Backup file verified: {backup_file.name} matches pre-migration text byte-for-byte.")

            # (b) Migration/redaction log contents showing what was changed and why
            log_file = test_mem_file.parent / "migration_redaction.log"
            assert log_file.exists(), "Migration redaction log file must exist!"
            log_lines = log_file.read_text(encoding="utf-8").strip().splitlines()
            assert len(log_lines) >= 3, f"Expected at least 3 log entries, found {len(log_lines)}"
            print(f"  -> (b) Migration log verified ({len(log_lines)} entries):")
            for line in log_lines:
                rec = json.loads(line)
                print(f"       * {rec.get('location')}: {rec.get('reason')} -> {rec.get('redacted_to', rec.get('redacted_snippet'))}")

            # (c) Proof a second load_memory() call does NOT re-trigger migration
            backup_mtime_before = backup_file.stat().st_mtime_ns
            log_count_before = len(log_lines)

            loaded_second = mm.load_memory()
            assert loaded_second["preferences"]["api_key"]["value"] == "[REDACTED_SECRET]"
            backup_mtime_after = backup_file.stat().st_mtime_ns
            log_count_after = len(log_file.read_text(encoding="utf-8").strip().splitlines())

            assert backup_mtime_after == backup_mtime_before, "Backup file must not be overwritten on second load!"
            assert log_count_after == log_count_before, "Migration log must not receive duplicate entries on second load!"
            print("  -> (c) Verified: Second load_memory() did NOT re-trigger migration.")

        finally:
            mm.MEMORY_PATH = orig_path


def test_5_preference_tracking_helpers():
    print("\n--- Test 5: Extended Preference Tracking Helpers & Structured JSON ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_mem_file = Path(tmp_dir) / "test_memory.json"
        orig_path = mm.MEMORY_PATH
        mm.MEMORY_PATH = test_mem_file

        try:
            # 1. Preferred Download Directory
            custom_download = Path(tmp_dir) / "MyDownloads"
            custom_download.mkdir(parents=True, exist_ok=True)
            mm.set_preferred_download_dir(custom_download)
            resolved_p = mm.get_preferred_download_dir()
            assert resolved_p == custom_download.resolve()
            print(f"  -> Preferred download directory verified: {resolved_p}")

            # 2. Frequently Used Apps Tracking
            mm.record_app_launch("notepad")
            mm.record_app_launch("chrome")
            mm.record_app_launch("notepad")
            mm.record_app_launch("calc")
            mm.record_app_launch("notepad")
            mm.record_app_launch("chrome")

            top_apps = mm.get_frequently_used_apps(limit=3)
            assert top_apps == ["notepad", "chrome", "calc"], f"Unexpected top apps order: {top_apps}"
            print(f"  -> Frequently used apps ranking verified: {top_apps}")

            # 3. Automation Preferences as Structured Nested JSON
            mm.set_automation_preference("auto_confirm_safe", True)
            mm.set_automation_preference("default_browser", "msedge")
            mm.set_automation_preference("max_download_mb", 500)

            # Assert direct reads via API
            assert mm.get_automation_preference("auto_confirm_safe") is True
            assert mm.get_automation_preference("default_browser") == "msedge"
            assert mm.get_automation_preference("max_download_mb") == 500
            assert mm.get_automation_preference("nonexistent_option", "fallback") == "fallback"

            # Assert physical storage on disk in long_term.json is structured nested JSON (not a string)
            disk_data = json.loads(test_mem_file.read_text(encoding="utf-8"))
            auto_pref_entry = disk_data["preferences"]["automation_preferences"]
            assert isinstance(auto_pref_entry["value"], dict), (
                f"Expected structured nested JSON dict, got {type(auto_pref_entry['value'])}: {auto_pref_entry['value']}"
            )
            assert auto_pref_entry["value"]["auto_confirm_safe"] is True
            assert auto_pref_entry["value"]["default_browser"] == "msedge"
            assert auto_pref_entry["value"]["max_download_mb"] == 500

            print(f"  -> Automation preferences verified as native nested dict:\n"
                  f"       {json.dumps(auto_pref_entry, indent=2)}")

        finally:
            mm.MEMORY_PATH = orig_path


def test_6_prompt_formatting_and_ui_compatibility():
    print("\n--- Test 6: Prompt Formatting & UI Compatibility ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_mem_file = Path(tmp_dir) / "test_memory.json"
        orig_path = mm.MEMORY_PATH
        mm.MEMORY_PATH = test_mem_file

        try:
            mm.update_memory({
                "identity": {"name": {"value": "Santhosh"}},
                "preferences": {
                    "favorite_drink": {"value": "Earl Grey tea"},
                    "preferred_download_dir": {"value": str(Path(tmp_dir) / "Downloads")},
                },
                "projects": {"assistant": {"value": "Building Mark LIV"}},
            })

            mem = mm.load_memory()
            prompt_block = mm.format_memory_for_prompt(mem)

            assert "Santhosh" in prompt_block
            assert "Earl Grey tea" in prompt_block
            assert "Building Mark LIV" in prompt_block
            print(f"  -> Prompt block formatted successfully ({len(prompt_block)} chars):\n{prompt_block}")

            ui_rows = mm.all_entries_for_ui()
            assert len(ui_rows) >= 3
            ui_keys = [r["key"] for r in ui_rows]
            assert "favorite_drink" in ui_keys
            print(f"  -> all_entries_for_ui() returned {len(ui_rows)} valid rows for HUD display.")

        finally:
            mm.MEMORY_PATH = orig_path


if __name__ == "__main__":
    print("======================================================================")
    print("RUNNING ITEM 2 (SECTION 21: MEMORY SECRET-SCRUBBING) TEST SUITE")
    print("======================================================================")
    test_1_secret_scrubbing_on_memory_updates()
    test_2_false_positive_avoidance()
    test_3_session_summary_scrubbing()
    test_4_scrub_on_load_migration()
    test_5_preference_tracking_helpers()
    test_6_prompt_formatting_and_ui_compatibility()
    print("\n======================================================================")
    print("ALL ITEM 2 MEMORY SECRET-SCRUBBING TESTS PASSED CLEANLY!")
    print("======================================================================")
