"""
Test Suite: Phase 2 Item 4 (Section 8: File Operations Bulk Gating & Multi-Step Organization)

Covers:
1. Literal "put all my PDFs from Downloads into a folder called College" natural language scenario
2. Confirmation gate with itemized pre-planning & zero mutation before confirmation
3. Execution verification on confirm
4. Undo support restoring files and cleaning up empty created destination folder
5. Cancellation preserves all files untouched at filesystem level
6. Undo edge case: unrelated user file in destination folder preserves file & folder
7. Bulk move operation (pre-plan, gate, execute, undo)
8. Bulk rename operation (pre-plan, gate, execute, undo)
9. No-op handling (zero matching files returns cleanly without prompt)
10. Concurrent confirmation collision protection
11. POLICY_RULES classification as STRONG_CONFIRM & verify_permission_gates static audit
"""

import sys
import time
import shutil
import tempfile
from pathlib import Path

try:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from actions.file_controller import file_controller, organize_files, bulk_move, bulk_rename
import actions.file_controller as fc_mod
from core import confirm, undo
from core.permission_manager import (
    check_permission,
    PermissionLevel,
    verify_permission_gates,
    resolve_action_handler,
    has_confirm_gate,
)


class MockConfirmHUD:
    def __init__(self):
        self.shown = []
        self.hidden = 0
        self.logs = []

    def show(self, title: str, detail: str):
        self.shown.append({"title": title, "detail": detail})

    def hide(self):
        self.hidden += 1

    def log(self, msg: str):
        self.logs.append(msg)

    def last_prompt(self):
        return self.shown[-1] if self.shown else None


def setup_mock_downloads():
    tmp_dir = Path(tempfile.mkdtemp(prefix="test_downloads_"))
    downloads_dir = tmp_dir / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir, downloads_dir


def test_1_literal_pdfs_from_downloads_to_college():
    print("\n" + "=" * 65)
    print("TEST 1: Literal 'PDFs from Downloads to College' NL Scenario")
    print("=" * 65)

    tmp_dir, mock_downloads = setup_mock_downloads()
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    try:
        # Override downloads folder resolver
        orig_get_downloads = fc_mod._get_downloads
        fc_mod._get_downloads = lambda: mock_downloads

        # Populate Downloads with test files
        (mock_downloads / "syllabus.pdf").write_text("Syllabus content", encoding="utf-8")
        (mock_downloads / "assignment1.pdf").write_text("Assignment 1 content", encoding="utf-8")
        (mock_downloads / "lecture_notes.pdf").write_text("Notes content", encoding="utf-8")
        (mock_downloads / "receipt.txt").write_text("Receipt content", encoding="utf-8")
        (mock_downloads / "photo.png").write_text("Photo content", encoding="utf-8")

        # Call with natural language prompt
        res = file_controller({
            "action": "organize",
            "task": "put all my PDFs from Downloads into a folder called College",
        })

        # 1. Verify confirmation pending
        assert "[CONFIRMATION_PENDING]" in res, f"Expected confirmation pending, got: {res}"

        # 2. Verify HUD prompt detail
        lp = hud.last_prompt()
        assert lp is not None, "HUD prompt was not recorded!"
        print(f"HUD Title : {lp['title']}")
        print(f"HUD Detail:\n{lp['detail']}")

        assert "Move 3 file(s) to 'College'" in lp["title"]
        assert "syllabus.pdf" in lp["detail"]
        assert "assignment1.pdf" in lp["detail"]
        assert "lecture_notes.pdf" in lp["detail"]
        assert "Total files to move: 3" in lp["detail"]

        # 3. Verify zero filesystem mutation before confirmation
        assert (mock_downloads / "syllabus.pdf").exists(), "File moved before confirmation!"
        assert (mock_downloads / "assignment1.pdf").exists(), "File moved before confirmation!"
        assert (mock_downloads / "lecture_notes.pdf").exists(), "File moved before confirmation!"
        assert not (mock_downloads / "College").exists(), "Destination folder created prematurely!"

        # 4. Confirm execution
        confirm.resolve(True)
        time.sleep(0.3)

        college_dir = mock_downloads / "College"
        assert college_dir.exists() and college_dir.is_dir(), "College directory was not created!"
        assert (college_dir / "syllabus.pdf").exists(), "syllabus.pdf missing from College/"
        assert (college_dir / "assignment1.pdf").exists(), "assignment1.pdf missing from College/"
        assert (college_dir / "lecture_notes.pdf").exists(), "lecture_notes.pdf missing from College/"

        # Unmatched files remain in root
        assert (mock_downloads / "receipt.txt").exists(), "receipt.txt moved incorrectly!"
        assert (mock_downloads / "photo.png").exists(), "photo.png moved incorrectly!"
        print("  -> Confirmed: Matching files moved into College/ and non-matching remained.")

        # 5. Test Undo
        assert len(undo._stack) > 0, "No undo record was created!"
        last_undo = undo._stack[-1]
        print(f"  -> Triggering undo: '{last_undo.label}'")
        undo_res = last_undo.undo()
        print(f"  -> Undo result: {undo_res}")

        assert (mock_downloads / "syllabus.pdf").exists(), "syllabus.pdf not restored!"
        assert (mock_downloads / "assignment1.pdf").exists(), "assignment1.pdf not restored!"
        assert (mock_downloads / "lecture_notes.pdf").exists(), "lecture_notes.pdf not restored!"
        assert not college_dir.exists(), "College directory was not removed after empty restore!"
        print("  -> Confirmed: Undo cleanly restored all files and cleaned up empty destination directory.")

    finally:
        fc_mod._get_downloads = orig_get_downloads
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_2_cancellation_preserves_files():
    print("\n" + "=" * 65)
    print("TEST 2: User Cancellation Leaves ALL Files Untouched")
    print("=" * 65)

    tmp_dir, mock_downloads = setup_mock_downloads()
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    try:
        orig_get_downloads = fc_mod._get_downloads
        fc_mod._get_downloads = lambda: mock_downloads

        (mock_downloads / "test_a.pdf").write_text("A", encoding="utf-8")
        (mock_downloads / "test_b.pdf").write_text("B", encoding="utf-8")

        res = file_controller({
            "action": "organize",
            "task": "put all my PDFs from Downloads into a folder called College",
        })
        assert "[CONFIRMATION_PENDING]" in res

        # Simulate user pressing CANCEL
        confirm.resolve(False)
        time.sleep(0.1)

        assert (mock_downloads / "test_a.pdf").exists(), "test_a.pdf modified after cancel!"
        assert (mock_downloads / "test_b.pdf").exists(), "test_b.pdf modified after cancel!"
        assert not (mock_downloads / "College").exists(), "Destination folder created after cancel!"
        print("  -> Confirmed: 100% filesystem integrity preserved on user cancellation.")

    finally:
        fc_mod._get_downloads = orig_get_downloads
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_3_undo_edge_case_unrelated_file():
    print("\n" + "=" * 65)
    print("TEST 3: Undo Edge Case — Unrelated User File in Destination Folder")
    print("=" * 65)

    tmp_dir, mock_downloads = setup_mock_downloads()
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    try:
        orig_get_downloads = fc_mod._get_downloads
        fc_mod._get_downloads = lambda: mock_downloads

        (mock_downloads / "doc1.pdf").write_text("PDF 1", encoding="utf-8")

        # Organize
        file_controller({
            "action": "organize",
            "task": "put all my PDFs from Downloads into a folder called College",
        })
        confirm.resolve(True)
        time.sleep(0.3)

        college_dir = mock_downloads / "College"
        assert (college_dir / "doc1.pdf").exists()

        # User adds an unrelated file directly into College/
        unrelated = college_dir / "unrelated_user_file.txt"
        unrelated.write_text("User personal notes", encoding="utf-8")

        # Trigger undo
        last_undo = undo._stack[-1]
        undo_res = last_undo.undo()
        print(f"  -> Undo result: {undo_res}")

        # Condition A: Original file restored
        assert (mock_downloads / "doc1.pdf").exists(), "doc1.pdf was not restored to Downloads root!"
        # Condition B: Unrelated file preserved
        assert unrelated.exists(), "Unrelated user file was accidentally deleted during undo!"
        assert unrelated.read_text(encoding="utf-8") == "User personal notes"
        # Condition C: College folder safely preserved
        assert college_dir.exists(), "College folder was deleted despite containing user file!"
        print("  -> Condition A, B, C Passed: Restored original, preserved user file, retained non-empty folder.")

    finally:
        fc_mod._get_downloads = orig_get_downloads
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_4_bulk_move():
    print("\n" + "=" * 65)
    print("TEST 4: Bulk Move Operation (Pre-planning, Gate, Execution & Undo)")
    print("=" * 65)

    tmp_dir, mock_downloads = setup_mock_downloads()
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    try:
        target_sub = mock_downloads / "Archive"

        (mock_downloads / "data1.log").write_text("log 1", encoding="utf-8")
        (mock_downloads / "data2.log").write_text("log 2", encoding="utf-8")
        (mock_downloads / "other.txt").write_text("txt", encoding="utf-8")

        res = file_controller({
            "action": "bulk_move",
            "path": str(mock_downloads),
            "destination": str(target_sub),
            "pattern": "*.log",
        })

        assert "[CONFIRMATION_PENDING]" in res
        lp = hud.last_prompt()
        assert "Bulk Move: 2 file(s)" in lp["title"]
        assert "data1.log" in lp["detail"]
        assert "data2.log" in lp["detail"]

        # Confirm
        confirm.resolve(True)
        time.sleep(0.3)

        assert (target_sub / "data1.log").exists()
        assert (target_sub / "data2.log").exists()
        assert (mock_downloads / "other.txt").exists()
        print("  -> Bulk move confirmed and verified.")

        # Undo
        last_undo = undo._stack[-1]
        last_undo.undo()
        assert (mock_downloads / "data1.log").exists()
        assert (mock_downloads / "data2.log").exists()
        print("  -> Bulk move undo verified.")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_5_bulk_rename():
    print("\n" + "=" * 65)
    print("TEST 5: Bulk Rename Operation (Pre-planning, Gate, Execution & Undo)")
    print("=" * 65)

    tmp_dir, mock_downloads = setup_mock_downloads()
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    try:
        (mock_downloads / "draft_one.txt").write_text("one", encoding="utf-8")
        (mock_downloads / "draft_two.txt").write_text("two", encoding="utf-8")

        res = file_controller({
            "action": "bulk_rename",
            "path": str(mock_downloads),
            "find": "draft_",
            "replace": "final_",
        })

        assert "[CONFIRMATION_PENDING]" in res
        lp = hud.last_prompt()
        assert "Bulk Rename: 2 file(s)" in lp["title"]
        assert "draft_one.txt → final_one.txt" in lp["detail"]
        assert "draft_two.txt → final_two.txt" in lp["detail"]

        # Confirm
        confirm.resolve(True)
        time.sleep(0.3)

        assert (mock_downloads / "final_one.txt").exists()
        assert (mock_downloads / "final_two.txt").exists()
        assert not (mock_downloads / "draft_one.txt").exists()
        print("  -> Bulk rename confirmed and verified.")

        # Undo
        last_undo = undo._stack[-1]
        last_undo.undo()
        assert (mock_downloads / "draft_one.txt").exists()
        assert (mock_downloads / "draft_two.txt").exists()
        print("  -> Bulk rename undo verified.")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_6_empty_match_clean_return():
    print("\n" + "=" * 65)
    print("TEST 6: Zero Matching Files Returns Cleanly Without Confirmation")
    print("=" * 65)

    tmp_dir, mock_downloads = setup_mock_downloads()
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    try:
        orig_get_downloads = fc_mod._get_downloads
        fc_mod._get_downloads = lambda: mock_downloads

        # Downloads has only images, no PDFs
        (mock_downloads / "photo.png").write_text("Photo", encoding="utf-8")

        res = file_controller({
            "action": "organize",
            "task": "put all my PDFs from Downloads into a folder called College",
        })

        assert "[CONFIRMATION_PENDING]" not in res, "Should not gate when 0 files match!"
        assert "No matching" in res
        assert hud.last_prompt() is None, "HUD prompt should not appear for empty match!"
        print(f"  -> Clean response: '{res}'")

    finally:
        fc_mod._get_downloads = orig_get_downloads
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_7_collision_protection():
    print("\n" + "=" * 65)
    print("TEST 7: Concurrent Confirmation Collision Protection")
    print("=" * 65)

    tmp_dir, mock_downloads = setup_mock_downloads()
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    try:
        orig_get_downloads = fc_mod._get_downloads
        fc_mod._get_downloads = lambda: mock_downloads

        (mock_downloads / "a.pdf").write_text("A", encoding="utf-8")
        (mock_downloads / "b.pdf").write_text("B", encoding="utf-8")

        res1 = file_controller({
            "action": "organize",
            "task": "put all my PDFs from Downloads into a folder called College",
        })
        assert "[CONFIRMATION_PENDING]" in res1

        res2 = file_controller({
            "action": "organize",
            "task": "put all my PDFs from Downloads into a folder called College",
        })
        assert "There is already a confirmation waiting on screen" in res2

        confirm.resolve(False)
        print("  -> Collision protection cleanly handled.")

    finally:
        fc_mod._get_downloads = orig_get_downloads
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_8_policy_rules_and_static_audit():
    print("\n" + "=" * 65)
    print("TEST 8: POLICY_RULES Classification & verify_permission_gates Audit")
    print("=" * 65)

    bulk_actions = ["organize", "organize_files", "bulk_move", "bulk_rename", "organize_desktop"]
    for act in bulk_actions:
        perm = check_permission("file_controller", act, {})
        assert perm.level == PermissionLevel.STRONG_CONFIRM, f"{act} should be STRONG_CONFIRM, got {perm.level}"
        print(f"  -> check_permission('file_controller', '{act}') = {perm.level.value} (key: {perm.key})")

        handler = resolve_action_handler(file_controller, act)
        assert has_confirm_gate(handler) is True, f"Handler '{handler.__name__}' for '{act}' lacks confirm.request() gate!"
        print(f"     Resolved implementation '{handler.__name__}' statically verified with confirm.request().")

    verify_permission_gates()
    print("  -> verify_permission_gates() passed with 0 errors across ALL registered tools!")


if __name__ == "__main__":
    print("=" * 70)
    print("RUNNING SECTION 8 FILE OPERATIONS BULK GATING TEST SUITE")
    print("=" * 70)

    test_1_literal_pdfs_from_downloads_to_college()
    test_2_cancellation_preserves_files()
    test_3_undo_edge_case_unrelated_file()
    test_4_bulk_move()
    test_5_bulk_rename()
    test_6_empty_match_clean_return()
    test_7_collision_protection()
    test_8_policy_rules_and_static_audit()

    print("\n" + "=" * 70)
    print("ALL SECTION 8 BULK GATING TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)
