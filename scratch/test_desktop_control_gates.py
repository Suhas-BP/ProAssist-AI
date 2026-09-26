"""
Dedicated test suite for Phase 2 Item 1: Section 5 (Desktop Control — organize_desktop / clean_desktop confirmation gates).

Validates:
1. organize_desktop() is gated behind confirm.request() at STRONG_CONFIRM level.
2. clean_desktop() is gated behind confirm.request() at STRONG_CONFIRM level.
3. Confirmation details explicitly show source files, target directories, and counts.
4. Files are NOT moved until the user explicitly confirms (resolve(True)).
5. User cancellation (resolve(False)) leaves all files untouched.
6. Empty desktop or already-organized desktop returns immediately without prompting.
7. Concurrent pending confirmation collisions are rejected cleanly.
8. Undo integration successfully reverses confirmed organize and clean operations.
9. POLICY_RULES registers organize and clean as STRONG_CONFIRM.
10. EXEMPT_DEFERRED_ACTIONS is empty and verify_permission_gates() passes with 0 exemptions.
"""
import os
import sys
import shutil
import tempfile
from pathlib import Path
from datetime import datetime

# UTF-8 stdout/stderr safety
for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from actions.desktop import desktop_control, organize_desktop, clean_desktop
import actions.desktop as desktop_mod
from core import confirm, undo
from core.permission_manager import (
    check_permission,
    PermissionLevel,
    verify_permission_gates,
    EXEMPT_DEFERRED_ACTIONS,
    POLICY_RULES,
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


def setup_mock_desktop():
    tmp_dir = Path(tempfile.mkdtemp(prefix="test_desktop_"))
    desktop_dir = tmp_dir / "Desktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir, desktop_dir


def test_organize_desktop_confirmation_and_execution():
    print("\n" + "=" * 60)
    print("TEST 1: organize_desktop Pre-planning, Confirmation Gate & Execution")
    print("=" * 60)

    tmp_dir, mock_desktop = setup_mock_desktop()
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    try:
        desktop_mod._get_desktop = lambda: mock_desktop

        # Populate desktop with diverse files
        (mock_desktop / "doc1.pdf").write_text("pdf content", encoding="utf-8")
        (mock_desktop / "notes.txt").write_text("text content", encoding="utf-8")
        (mock_desktop / "photo.png").write_text("image content", encoding="utf-8")
        (mock_desktop / "song.mp3").write_text("music content", encoding="utf-8")
        (mock_desktop / "video.mp4").write_text("video content", encoding="utf-8")
        (mock_desktop / "archive.zip").write_text("zip content", encoding="utf-8")
        (mock_desktop / "script.py").write_text("python content", encoding="utf-8")
        (mock_desktop / "random.xyz").write_text("other content", encoding="utf-8")

        # Directories and shortcuts should be ignored
        (mock_desktop / "Projects").mkdir(exist_ok=True)
        (mock_desktop / "shortcut.lnk").write_text("shortcut", encoding="utf-8")

        # 1. Trigger organize_desktop via desktop_control
        res = desktop_control({"action": "organize", "mode": "by_type"})
        print(f"desktop_control response: {res}")
        assert "[CONFIRMATION_PENDING]" in res, "Expected [CONFIRMATION_PENDING] instruction"

        # 2. Verify confirmation dialog state
        assert len(hud.shown) == 1, "Expected confirmation banner to be shown on HUD"
        banner = hud.shown[-1]
        print(f"HUD Title : {banner['title']}")
        print(f"HUD Detail:\n{banner['detail']}")

        assert "Organize Desktop: Move 8 file(s)" in banner["title"]
        assert "Mode: by_type" in banner["detail"]
        assert "Total files to move: 8" in banner["detail"]
        assert "• photo.png → Images/" in banner["detail"]
        assert "• doc1.pdf → Documents/" in banner["detail"]

        # 3. Verify files have NOT moved yet
        assert (mock_desktop / "photo.png").exists(), "Files must NOT move before confirmation!"
        assert not (mock_desktop / "Images" / "photo.png").exists()

        # 4. Simulate user pressing CONFIRM
        confirm.resolve(True)
        import time
        time.sleep(0.3)  # Wait for worker thread

        # 5. Verify files were properly organized into type folders
        assert (mock_desktop / "Documents" / "doc1.pdf").exists()
        assert (mock_desktop / "Documents" / "notes.txt").exists()
        assert (mock_desktop / "Images" / "photo.png").exists()
        assert (mock_desktop / "Music" / "song.mp3").exists()
        assert (mock_desktop / "Videos" / "video.mp4").exists()
        assert (mock_desktop / "Archives" / "archive.zip").exists()
        assert (mock_desktop / "Code" / "script.py").exists()
        assert (mock_desktop / "Others" / "random.xyz").exists()
        assert (mock_desktop / "Projects").exists()  # Folder stayed at root
        assert (mock_desktop / "shortcut.lnk").exists()  # LNK stayed at root
        print("  -> Confirmed: All files moved to designated category folders.")

        # 6. Verify undo support
        assert len(undo._stack) > 0, "Expected organize operation to push an undo entry"
        last_undo = undo._stack[-1]
        print(f"  -> Testing undo: '{last_undo.label}'")
        undo_res = last_undo.undo()
        print(f"  -> Undo result: {undo_res}")
        assert "Restored 8 file(s)" in undo_res
        assert (mock_desktop / "photo.png").exists()
        assert (mock_desktop / "doc1.pdf").exists()
        assert not (mock_desktop / "Images").exists()  # Empty folder cleaned up
        print("✅ organize_desktop confirmation, move, and undo fully verified.")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_clean_desktop_confirmation_and_execution():
    print("\n" + "=" * 60)
    print("TEST 2: clean_desktop Pre-planning, Confirmation Gate & Execution")
    print("=" * 60)

    tmp_dir, mock_desktop = setup_mock_desktop()
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    try:
        desktop_mod._get_desktop = lambda: mock_desktop

        # Populate files
        (mock_desktop / "fileA.txt").write_text("A", encoding="utf-8")
        (mock_desktop / "fileB.jpg").write_text("B", encoding="utf-8")
        (mock_desktop / "fileC.pdf").write_text("C", encoding="utf-8")

        # 1. Trigger clean_desktop
        res = desktop_control({"action": "clean"})
        print(f"desktop_control response: {res}")
        assert "[CONFIRMATION_PENDING]" in res

        # 2. Verify confirmation dialog details
        banner = hud.shown[-1]
        print(f"HUD Title : {banner['title']}")
        print(f"HUD Detail:\n{banner['detail']}")

        today = datetime.now().strftime("%Y-%m-%d")
        archive_name = f"Desktop Archive {today}"
        assert f"Clean Desktop: Archive 3 file(s)" in banner["title"]
        assert archive_name in banner["detail"]
        assert "Total files to archive: 3" in banner["detail"]
        assert f"• fileA.txt → {archive_name}/" in banner["detail"]

        # 3. Verify files not moved yet
        assert (mock_desktop / "fileA.txt").exists()

        # 4. User confirms
        confirm.resolve(True)
        import time
        time.sleep(0.3)

        # 5. Verify archive folder created and files moved
        archive_dir = mock_desktop / archive_name
        assert archive_dir.exists() and archive_dir.is_dir()
        assert (archive_dir / "fileA.txt").exists()
        assert (archive_dir / "fileB.jpg").exists()
        assert (archive_dir / "fileC.pdf").exists()
        assert not (mock_desktop / "fileA.txt").exists()
        print(f"  -> Confirmed: 3 files archived into '{archive_name}'.")

        # 6. Verify undo
        last_undo = undo._stack[-1]
        print(f"  -> Testing undo: '{last_undo.label}'")
        undo_res = last_undo.undo()
        print(f"  -> Undo result: {undo_res}")
        assert "Restored 3 file(s)" in undo_res
        assert (mock_desktop / "fileA.txt").exists()
        assert not archive_dir.exists()  # Empty archive folder cleaned up
        print("✅ clean_desktop confirmation, move, and undo fully verified.")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_user_cancellation_preserves_files():
    print("\n" + "=" * 60)
    print("TEST 3: User Cancellation Leaves ALL Files Untouched (Filesystem Check)")
    print("=" * 60)

    tmp_dir, mock_desktop = setup_mock_desktop()
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    try:
        desktop_mod._get_desktop = lambda: mock_desktop

        # Populate a multi-file batch across different types
        test_files = {
            "report.pdf": "PDF content 123",
            "notes.txt": "Notes content 456",
            "picture.png": "Binary-like PNG 789",
            "track.mp3": "Audio content ABC",
            "app.py": "Python code DEF",
        }
        for name, content in test_files.items():
            (mock_desktop / name).write_text(content, encoding="utf-8")

        # 1. Test cancellation for organize_desktop
        res_org = desktop_control({"action": "organize", "mode": "by_type"})
        assert "[CONFIRMATION_PENDING]" in res_org
        assert bool(confirm.pending_title()) is True

        # Simulate user pressing CANCEL on HUD
        confirm.resolve(False)
        import time
        time.sleep(0.1)

        # Filesystem-level validation: EVERY single planned file must still exist at Desktop root
        for name, expected_content in test_files.items():
            file_path = mock_desktop / name
            assert file_path.exists(), f"File '{name}' missing from Desktop after cancellation!"
            assert file_path.read_text(encoding="utf-8") == expected_content, f"Content mismatch for '{name}'!"

        # Ensure NO category folders were created
        for cat in ["Documents", "Images", "Music", "Code", "Others"]:
            assert not (mock_desktop / cat).exists(), f"Folder '{cat}' should NOT exist after cancellation!"

        print("  -> Confirmed organize cancellation: 5/5 files remain in place, 0 folders created.")

        # 2. Test cancellation for clean_desktop
        res_clean = desktop_control({"action": "clean"})
        assert "[CONFIRMATION_PENDING]" in res_clean
        confirm.resolve(False)
        time.sleep(0.1)

        # Filesystem-level validation: ALL files still present at Desktop root
        for name, expected_content in test_files.items():
            file_path = mock_desktop / name
            assert file_path.exists(), f"File '{name}' missing after clean cancellation!"
            assert file_path.read_text(encoding="utf-8") == expected_content

        # Ensure NO archive folder was created
        today = datetime.now().strftime("%Y-%m-%d")
        assert not (mock_desktop / f"Desktop Archive {today}").exists()
        print("  -> Confirmed clean cancellation: 5/5 files remain in place, 0 archive folders created.")
        print("✅ User cancellation rigorously verified at filesystem level.")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_undo_edge_case_user_file_in_dest_folder():
    print("\n" + "=" * 60)
    print("TEST 7: Undo Edge Case — Unrelated User File in Destination Folder")
    print("=" * 60)

    tmp_dir, mock_desktop = setup_mock_desktop()
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    try:
        desktop_mod._get_desktop = lambda: mock_desktop

        # 1. Create original files to organize
        doc_file = mock_desktop / "original_doc.pdf"
        doc_file.write_text("Original PDF content", encoding="utf-8")

        # 2. Run organize and confirm
        res = desktop_control({"action": "organize", "mode": "by_type"})
        assert "[CONFIRMATION_PENDING]" in res
        confirm.resolve(True)
        import time
        time.sleep(0.3)

        docs_folder = mock_desktop / "Documents"
        assert docs_folder.exists() and (docs_folder / "original_doc.pdf").exists()
        assert not (mock_desktop / "original_doc.pdf").exists()
        print("  -> Organize moved original_doc.pdf into Documents/.")

        # 3. User adds an unrelated new file directly into Documents/ BEFORE calling undo
        user_file = docs_folder / "user_secret_file.docx"
        user_content = "User private confidential notes created after organize"
        user_file.write_text(user_content, encoding="utf-8")
        print("  -> User placed new unrelated file directly into Documents/.")

        # 4. Trigger undo on the organize operation
        assert len(undo._stack) > 0
        undo_entry = undo._stack[-1]
        print(f"  -> Triggering undo: '{undo_entry.label}'")
        undo_msg = undo_entry.undo()
        print(f"  -> Undo returned: {undo_msg}")

        # 5. Verify the edge case conditions:
        # A. The originally-moved files are correctly restored to Desktop
        assert (mock_desktop / "original_doc.pdf").exists(), "Original file must be restored to Desktop!"
        assert (mock_desktop / "original_doc.pdf").read_text(encoding="utf-8") == "Original PDF content"
        assert not (docs_folder / "original_doc.pdf").exists(), "Original file must no longer be in Documents/!"
        print("  -> Condition A Passed: original_doc.pdf cleanly restored to Desktop root.")

        # B. The new unrelated file the user added is NOT deleted or disturbed
        assert user_file.exists(), "User's unrelated file must NOT be deleted!"
        assert user_file.read_text(encoding="utf-8") == user_content, "User file content must be intact!"
        print("  -> Condition B Passed: user_secret_file.docx is untouched with 100% data integrity.")

        # C. The destination folder is kept because it still contains the user's file
        assert docs_folder.exists(), "Destination folder Documents/ must NOT be deleted because it contains user files!"
        assert docs_folder.is_dir()
        remaining_items = [f.name for f in docs_folder.iterdir()]
        assert remaining_items == ["user_secret_file.docx"], f"Expected only user file in Documents/, got {remaining_items}"
        print(f"  -> Condition C Passed: Documents/ folder safely retained holding: {remaining_items}")
        print("✅ Undo edge case verified: user files safely preserved, folder not prematurely deleted.")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_empty_desktop_no_unnecessary_prompt():
    print("\n" + "=" * 60)
    print("TEST 4: Empty Desktop Returns Cleanly Without Confirmation Prompt")
    print("=" * 60)

    tmp_dir, mock_desktop = setup_mock_desktop()
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    try:
        desktop_mod._get_desktop = lambda: mock_desktop

        # Empty desktop organize
        res_org = desktop_control({"action": "organize"})
        print(f"Empty organize response: {res_org}")
        assert "already organized" in res_org
        assert len(hud.shown) == 0, "Must not prompt confirmation when no files to move"

        # Empty desktop clean
        res_clean = desktop_control({"action": "clean"})
        print(f"Empty clean response: {res_clean}")
        assert "already clean" in res_clean
        assert len(hud.shown) == 0, "Must not prompt confirmation when no files to clean"

        print("✅ Empty desktop handled cleanly without unnecessary HUD banners.")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_concurrent_pending_confirmation_collision():
    print("\n" + "=" * 60)
    print("TEST 5: Concurrent Confirmation Collision Check")
    print("=" * 60)

    tmp_dir, mock_desktop = setup_mock_desktop()
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    try:
        desktop_mod._get_desktop = lambda: mock_desktop
        (mock_desktop / "file1.txt").write_text("1", encoding="utf-8")
        (mock_desktop / "file2.txt").write_text("2", encoding="utf-8")

        # 1. Trigger first confirmation
        res1 = desktop_control({"action": "organize"})
        assert "[CONFIRMATION_PENDING]" in res1
        assert bool(confirm.pending_title()) is True

        # 2. Trigger second confirmation while first is still waiting
        res2 = desktop_control({"action": "clean"})
        print(f"Collision response: {res2}")
        assert "already a confirmation waiting on screen" in res2
        print("  -> Collision cleanly rejected without stacking banners.")

        # Clean up
        confirm.resolve(False)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_permission_rules_and_verify_gates_audit():
    print("\n" + "=" * 60)
    print("TEST 6: POLICY_RULES Classification & verify_permission_gates Audit")
    print("=" * 60)

    # 1. Check permissions in policy manager
    dec_org = check_permission("desktop_control", "organize")
    print(f"desktop_control.organize -> {dec_org.level.value} ('{dec_org.reason}')")
    assert dec_org.level == PermissionLevel.STRONG_CONFIRM

    dec_clean = check_permission("desktop_control", "clean")
    print(f"desktop_control.clean    -> {dec_clean.level.value} ('{dec_clean.reason}')")
    assert dec_clean.level == PermissionLevel.STRONG_CONFIRM

    # 2. Check EXEMPT_DEFERRED_ACTIONS is empty
    print(f"EXEMPT_DEFERRED_ACTIONS: {EXEMPT_DEFERRED_ACTIONS}")
    assert len(EXEMPT_DEFERRED_ACTIONS) == 0, f"Expected 0 exemptions, got {EXEMPT_DEFERRED_ACTIONS}"

    # 3. Run verify_permission_gates audit
    from core.action_loader import discover_actions
    registry = discover_actions(actions_dir=BASE_DIR / "actions")
    verify_permission_gates(registry)
    print("✅ Static audit passed across ALL registered tools with ZERO exemptions!")


if __name__ == "__main__":
    test_organize_desktop_confirmation_and_execution()
    test_clean_desktop_confirmation_and_execution()
    test_user_cancellation_preserves_files()
    test_empty_desktop_no_unnecessary_prompt()
    test_concurrent_pending_confirmation_collision()
    test_permission_rules_and_verify_gates_audit()
    test_undo_edge_case_user_file_in_dest_folder()
    print("\n" + "=" * 60)
    print("ALL PHASE 2 ITEM 1 (SECTION 5 DESKTOP GATES) TESTS PASSED!")
    print("=" * 60)
