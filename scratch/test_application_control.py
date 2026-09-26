"""
Dedicated test suite for Section 9: Application Control (actions/open_app.py).

Validates:
1. Dynamic system application discovery via AppLauncher (replacing hardcoded aliases).
2. Exact and fuzzy matching for installed applications (e.g. calc, notepad, chrome, word).
3. Rejection of nonexistent applications without blind Start-Menu keystrokes.
4. Post-launch lifecycle verification (PID or window title confirmed).
5. Target-type detection: file opening vs application launch.
6. Standardized structured return format on all paths:
   {"success", "action", "app", "pid_or_window", "value", "message"}.
7. PermissionManager SAFE classification.
"""
import os
import sys
import time
from pathlib import Path
import psutil

# ── Console must survive non-UTF-8 code pages ────────────────────────────────
for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from actions.open_app import open_app, _get_launcher, TOOL
from core.permission_manager import check_permission, PermissionLevel, verify_permission_gates


def test_dynamic_app_discovery():
    print("\n" + "=" * 60)
    print("TEST 1: Dynamic Application Discovery via AppLauncher")
    print("=" * 60)

    launcher = _get_launcher()
    assert launcher is not None, "AppLauncher failed to initialize!"
    apps = launcher.discover_system_apps()
    print(f"Total discovered system apps on machine: {len(apps)}")
    assert len(apps) > 10, f"Expected >10 discovered apps, got {len(apps)}"

    test_queries = ["notepad", "calc", "calculator", "chrome", "google chrome", "paint", "word"]
    for q in test_queries:
        info = launcher.find_system_app(q)
        assert info is not None, f"Expected to find app for query '{q}', got None"
        d_name = info.get("display_name", info.get("name"))
        atype = info.get("type", "unknown")
        print(f"  -> Query '{q:15}' resolved to: '{d_name}' (type: {atype})")

    # Nonexistent application check
    non_app = "this_app_does_not_exist_xyz_12345"
    info_none = launcher.find_system_app(non_app)
    assert info_none is None, f"Expected None for nonexistent app, got {info_none}"
    print(f"  -> Nonexistent query '{non_app}' correctly rejected (None).")
    print("✅ Dynamic discovery and matching verified.")


def test_app_launch_and_lifecycle():
    print("\n" + "=" * 60)
    print("TEST 2: Application Launch & Lifecycle Verification")
    print("=" * 60)

    # Launch Calculator
    print("Launching 'calc' via open_app()...")
    res = open_app({"app_name": "calc"})
    print(f"open_app result: {res}")

    assert res["success"] is True, f"Failed to launch calc: {res['message']}"
    assert res["action"] == "open_app"
    assert "app" in res and "Calculator" in res["app"]
    assert res["pid_or_window"] is not None, "Lifecycle verification failed: pid_or_window is None"
    assert "value" in res and isinstance(res["value"], dict)
    print(f"  -> Lifecycle confirmed: app='{res['app']}', ref='{res['pid_or_window']}'")

    # Clean up spawned process
    pid = res["value"].get("pid")
    if pid:
        try:
            p = psutil.Process(pid)
            p.terminate()
            print(f"  -> Cleaned up spawned test process (PID: {pid}).")
        except Exception:
            pass

    # Nonexistent application launch check (must NOT type into Start Menu or sleep)
    print("\nTesting launch of nonexistent application...")
    t0 = time.time()
    res_none = open_app({"app_name": "fictional_app_xyz_999"})
    dt = time.time() - t0

    print(f"Nonexistent app result (took {dt:.2f}s): {res_none}")
    assert res_none["success"] is False
    assert res_none["action"] == "open_app"
    assert "Could not find application" in res_none["message"]
    assert dt < 2.0, f"Expected quick rejection without blind Start-Menu typing, took {dt:.2f}s"
    print("✅ Lifecycle verification and quick rejection verified.")


def test_file_target_opening():
    print("\n" + "=" * 60)
    print("TEST 3: Target-Type Detection (File Open vs App Launch)")
    print("=" * 60)

    # Existing file check
    contacts_file = "primary/data/contacts.json"
    res_file = open_app({"app_name": contacts_file})
    print(f"File open result: {res_file}")

    assert res_file["success"] is True
    assert res_file["action"] == "open_file"
    assert "contacts.json" in res_file["app"]
    assert "value" in res_file and res_file["value"].get("filename") == "contacts.json"

    # Nonexistent file check
    res_missing_file = open_app({"app_name": "nonexistent_file_abc.txt"})
    print(f"Missing file result: {res_missing_file}")
    assert res_missing_file["success"] is False
    assert res_missing_file["action"] == "open_file"
    assert "File not found" in res_missing_file["message"]
    print("✅ File target opening and error handling verified.")


def test_empty_parameter_handling():
    print("\n" + "=" * 60)
    print("TEST 4: Empty Parameter & Fallback Handling")
    print("=" * 60)

    res_empty = open_app({})
    assert res_empty["success"] is False
    assert res_empty["action"] == "open_app"
    assert "No application or file name provided" in res_empty["message"]
    print("✅ Empty parameters handled cleanly.")


def test_tool_declaration_and_permissions():
    print("\n" + "=" * 60)
    print("TEST 5: TOOL Declaration & POLICY_RULES Permission Classification")
    print("=" * 60)

    assert TOOL["name"] == "open_app"
    assert callable(TOOL["handler"])
    assert "app_name" in TOOL["parameters"]["properties"]
    print("✅ TOOL declaration is discoverable.")

    for act in ["open_app", "open_file", None]:
        dec = check_permission("open_app", act)
        print(f"Permission check for open_app.{act} -> Level: {dec.level.value}, Reason: '{dec.reason}'")
        assert dec.level == PermissionLevel.SAFE, f"Expected SAFE for {act}, got {dec.level}"

    print("✅ All open_app actions confirmed SAFE in POLICY_RULES.")


def test_silent_launch_failure_with_preexisting_process():
    print("\n" + "=" * 60)
    print("TEST 6: Silent Launch Failure vs Single-Instance Focus (Step 3 Precision)")
    print("=" * 60)
    from unittest.mock import patch, MagicMock
    from actions.open_app import _verify_app_lifecycle

    # Case A: App is already running (PID 8888, started 1 hour ago).
    # Launch is invoked but fails silently (no new PIDs spawned, no focus change).
    # Step 3 must NOT report false success via bare name matching.
    t_launch = time.time()
    mock_old_proc = MagicMock()
    mock_old_proc.info = {
        "pid": 8888,
        "name": "target_service.exe",
        "create_time": t_launch - 3600.0,
    }

    with patch("psutil.pids", return_value=[8888]), \
         patch("psutil.process_iter", return_value=[mock_old_proc]), \
         patch("pygetwindow.getAllWindows", return_value=[]), \
         patch("pygetwindow.getActiveWindow", return_value=None):
        
        verified, pid, win = _verify_app_lifecycle(
            candidate_tokens=["target_service"],
            pre_pids={8888},
            launch_time=t_launch,
            timeout=0.3,
            interval=0.05,
        )
        print(f"  Case A (Silent Failure) -> verified={verified}, pid={pid}, ref={win}")
        assert verified is False, f"Expected False on silent launch failure, got {verified} (False Success bug!)"
        print("  -> Confirmed: Pre-existing process with no state change correctly rejected.")

    # Case B: Single-instance app brings its existing window to foreground focus.
    # Step 3 must preserve its original purpose and report success.
    mock_win = MagicMock()
    mock_win.title = "Target Service - Main Window"

    with patch("psutil.pids", return_value=[8888]), \
         patch("psutil.process_iter", return_value=[mock_old_proc]), \
         patch("actions.open_app.gw.getAllWindows", return_value=[]), \
         patch("actions.open_app.gw.getActiveWindow", return_value=mock_win):

        verified_b, pid_b, win_b = _verify_app_lifecycle(
            candidate_tokens=["target", "service"],
            pre_pids={8888},
            launch_time=t_launch,
            timeout=0.3,
            interval=0.05,
        )
        print(f"  Case B (Foreground Focus) -> verified={verified_b}, pid={pid_b}, ref='{win_b}'")
        assert verified_b is True, "Expected True when existing app gains foreground focus"
        assert pid_b == 8888
        assert "Target Service" in win_b
        print("  -> Confirmed: Single-instance app window focus successfully verified.")

    # Case C: End-to-end via open_app() with launcher stub returning True on silent failure
    mock_launcher = MagicMock()
    mock_launcher.find_system_app.return_value = {
        "name": "silent_stub_app",
        "display_name": "Silent Stub App",
        "target": "silent_stub.exe",
        "type": "exe",
    }
    mock_stub_proc = MagicMock()
    mock_stub_proc.info = {
        "pid": 7777,
        "name": "silent_stub.exe",
        "create_time": t_launch - 1800.0,
    }

    import actions.open_app as o
    orig_verify = o._verify_app_lifecycle

    def fast_verify(*args, **kwargs):
        kwargs["timeout"] = 0.2
        kwargs["interval"] = 0.05
        return orig_verify(*args, **kwargs)

    with patch("actions.open_app._get_launcher", return_value=mock_launcher), \
         patch("actions.open_app._launch_via_app_launcher", return_value=True), \
         patch("actions.open_app._verify_app_lifecycle", side_effect=fast_verify), \
         patch("psutil.pids", return_value=[7777]), \
         patch("psutil.process_iter", return_value=[mock_stub_proc]), \
         patch("actions.open_app.gw.getAllWindows", return_value=[]), \
         patch("actions.open_app.gw.getActiveWindow", return_value=None):

        res = open_app({"app_name": "silent_stub_app"})
        print(f"  Case C (End-to-End open_app silent failure) -> success={res['success']}, msg='{res['message']}'")
        assert res["success"] is False, f"Expected success=False on silent launch failure, got {res}"
        assert "did not appear within" in res["message"]
        print("  -> Confirmed: open_app reports failure when launch silently no-ops.")

    print("✅ Step 3 precision verified: false-positives closed while focus events preserved.")


if __name__ == "__main__":
    test_dynamic_app_discovery()
    test_app_launch_and_lifecycle()
    test_file_target_opening()
    test_empty_parameter_handling()
    test_tool_declaration_and_permissions()
    test_silent_launch_failure_with_preexisting_process()
    print("\n" + "=" * 60)
    print("ALL SECTION 9 APPLICATION CONTROL TESTS PASSED!")
    print("=" * 60)

