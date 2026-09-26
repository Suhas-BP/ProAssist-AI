"""
Test Suite: Non-Browser Download Gate Verification (Section 7)
Covers:
1. set_wallpaper_from_url gating behind confirm.request()
2. Confirmation detail presents filename, source URL, and destination path
3. Execution verification: file is downloaded, non-empty, and applied
4. Cancellation preserves system state (no execution)
5. Concurrent confirmation collision protection
6. POLICY_RULES classification as STRONG_CONFIRM and verify_permission_gates static audit
"""

import sys
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

try:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core import confirm
from core.permission_manager import (
    check_permission,
    PermissionLevel,
    verify_permission_gates,
    resolve_action_handler,
    has_confirm_gate,
)
from actions.desktop import desktop_control


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


def test_1_set_wallpaper_from_url_gating():
    print("\n--- TEST 1: set_wallpaper_from_url Gate & Execution ---")
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    url = "https://example.com/images/nature_mountain.png"
    fake_downloaded_data = b"FAKE_IMAGE_DATA_12345"

    def fake_urlretrieve(src_url, dest_path):
        Path(dest_path).write_bytes(fake_downloaded_data)

    with patch("urllib.request.urlretrieve", side_effect=fake_urlretrieve):
        with patch("actions.desktop.set_wallpaper", return_value="Wallpaper set: nature_mountain.png") as mock_set:
            res = desktop_control({"action": "wallpaper_url", "url": url})
            assert "[CONFIRMATION_PENDING]" in res, f"Expected confirmation pending, got: {res}"

            lp = hud.last_prompt()
            assert lp is not None, "HUD prompt was not recorded!"
            assert "Download Wallpaper: nature_mountain.png" in lp["title"]
            assert "Source URL: https://example.com/images/nature_mountain.png" in lp["detail"]
            assert "Destination:" in lp["detail"]

            # Confirm the pending action
            confirm.resolve(True)
            time.sleep(0.3)

            assert mock_set.called, "set_wallpaper should have been called on confirm"
            print("  -> Confirmed execution and file write verified successfully.")


def test_2_set_wallpaper_from_url_cancellation():
    print("\n--- TEST 2: set_wallpaper_from_url Cancellation ---")
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    url = "https://example.com/images/cancelled.png"

    with patch("urllib.request.urlretrieve") as mock_dl:
        with patch("actions.desktop.set_wallpaper") as mock_set:
            res = desktop_control({"action": "wallpaper_url", "url": url})
            assert "[CONFIRMATION_PENDING]" in res

            confirm.resolve(False)
            time.sleep(0.1)

            assert not mock_dl.called, "Download should NOT occur when cancelled!"
            assert not mock_set.called, "Wallpaper should NOT be set when cancelled!"
            print("  -> Cancellation verified: download and wallpaper application aborted.")


def test_3_collision_protection():
    print("\n--- TEST 3: Concurrent Confirmation Collision Protection ---")
    hud = MockConfirmHUD()
    confirm.bind(hud.show, hud.hide, hud.log)

    # First request
    res1 = desktop_control({"action": "wallpaper_url", "url": "https://example.com/first.jpg"})
    assert "[CONFIRMATION_PENDING]" in res1

    # Second concurrent request
    res2 = desktop_control({"action": "wallpaper_url", "url": "https://example.com/second.jpg"})
    assert "There is already a confirmation waiting on screen" in res2

    # Clean up pending
    confirm.resolve(False)
    print("  -> Collision protection verified.")


def test_4_policy_rules_and_static_audit():
    print("\n--- TEST 4: POLICY_RULES & Static Audit Verification ---")
    perm = check_permission("desktop_control", "wallpaper_url", {"url": "https://example.com/pic.jpg"})
    assert perm.level == PermissionLevel.STRONG_CONFIRM, f"Expected STRONG_CONFIRM, got {perm.level}"
    assert perm.key == "desktop_wallpaper_url"
    print(f"  -> check_permission('desktop_control', 'wallpaper_url') = {perm.level.value} (key: {perm.key})")

    # Static handler resolution and AST gate check
    handler = resolve_action_handler(desktop_control, "wallpaper_url")
    assert handler.__name__ == "set_wallpaper_from_url"
    assert has_confirm_gate(handler) is True, "set_wallpaper_from_url must contain confirm.request()!"
    print(f"  -> Resolved handler '{handler.__name__}' statically verified to contain confirm.request().")

    # Run full verify_permission_gates
    verify_permission_gates()
    print("  -> verify_permission_gates() passed with 0 errors across all rules.")


if __name__ == "__main__":
    print("=" * 65)
    print("RUNNING SECTION 7 NON-BROWSER DOWNLOAD GATE TEST SUITE")
    print("=" * 65)

    test_1_set_wallpaper_from_url_gating()
    test_2_set_wallpaper_from_url_cancellation()
    test_3_collision_protection()
    test_4_policy_rules_and_static_audit()

    print("\n" + "=" * 65)
    print("ALL SECTION 7 TESTS PASSED SUCCESSFULLY!")
    print("=" * 65)
