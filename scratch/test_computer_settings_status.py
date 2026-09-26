"""
scratch/test_computer_settings_status.py
Dedicated test suite for Section 4 (Computer Settings):
1. Structured return format: {"success", "action", "value", "message"}
2. Wi-Fi status query (wifi_status)
3. Battery status/power info query (battery_status)
4. Bluetooth status query (bluetooth_status)
5. Volume & Brightness status queries (volume_get, brightness_get)
6. Error & fallback structured returns
7. Permission check & verify_permission_gates compatibility
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Console must survive non-UTF-8 code pages
for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from actions.computer_settings import (
    computer_settings,
    wifi_status,
    battery_status,
    bluetooth_status,
    volume_get,
    brightness_get,
)
from core.permission_manager import (
    PermissionLevel,
    check_permission,
    verify_permission_gates,
)


def assert_structured_result(res: dict, expected_action: str = None, expected_success: bool = None):
    assert isinstance(res, dict), f"Expected dict, got {type(res)}: {res}"
    assert "success" in res, f"Missing 'success' key in {res}"
    assert "action" in res, f"Missing 'action' key in {res}"
    assert "value" in res, f"Missing 'value' key in {res}"
    assert "message" in res, f"Missing 'message' key in {res}"
    assert isinstance(res["success"], bool), f"'success' must be bool, got {type(res['success'])}"
    assert isinstance(res["action"], str), f"'action' must be str, got {type(res['action'])}"
    assert isinstance(res["message"], str), f"'message' must be str, got {type(res['message'])}"
    if expected_action is not None:
        assert res["action"] == expected_action, f"Expected action '{expected_action}', got '{res['action']}'"
    if expected_success is not None:
        assert res["success"] is expected_success, f"Expected success={expected_success}, got {res['success']}"


def test_wifi_status_live_and_dispatch():
    print("Testing Wi-Fi status query...")
    # Direct function call
    direct = wifi_status()
    assert isinstance(direct, dict)
    assert "connected" in direct
    assert "state" in direct
    assert "message" in direct
    print(f"  -> Direct wifi_status output: {direct}")

    # Tool dispatch call
    res = computer_settings({"action": "wifi_status"})
    assert_structured_result(res, expected_action="wifi_status", expected_success=True)
    assert isinstance(res["value"], dict)
    assert res["value"]["state"] == direct["state"]
    assert len(res["message"]) > 0
    print(f"  -> Dispatched wifi_status result: {res}")


def test_battery_status_live_and_dispatch():
    print("Testing Battery status query...")
    direct = battery_status()
    assert isinstance(direct, dict)
    assert "has_battery" in direct
    assert "plugged" in direct
    assert "message" in direct
    print(f"  -> Direct battery_status output: {direct}")

    res = computer_settings({"action": "battery_status"})
    assert_structured_result(res, expected_action="battery_status", expected_success=True)
    assert isinstance(res["value"], dict)
    assert len(res["message"]) > 0
    print(f"  -> Dispatched battery_status result: {res}")


def test_bluetooth_status_live_and_dispatch():
    print("Testing Bluetooth status query...")
    direct = bluetooth_status()
    assert isinstance(direct, dict)
    assert "enabled" in direct
    assert "service" in direct
    assert "devices" in direct
    assert "message" in direct
    print(f"  -> Direct bluetooth_status output: {direct}")

    res = computer_settings({"action": "bluetooth_status"})
    assert_structured_result(res, expected_action="bluetooth_status", expected_success=True)
    assert isinstance(res["value"], dict)
    assert len(res["message"]) > 0
    print(f"  -> Dispatched bluetooth_status result: {res}")


def test_volume_and_brightness_queries():
    print("Testing Volume & Brightness queries...")
    res_vol = computer_settings({"action": "volume_get"})
    assert_structured_result(res_vol, expected_action="volume_get", expected_success=True)
    print(f"  -> volume_get result: {res_vol}")

    res_br = computer_settings({"action": "brightness_get"})
    assert_structured_result(res_br, expected_action="brightness_get", expected_success=True)
    print(f"  -> brightness_get result: {res_br}")


def test_structured_error_and_suggestions():
    print("Testing structured error & suggestion responses...")
    # Missing action and description
    res_empty = computer_settings({})
    assert_structured_result(res_empty, expected_success=False)
    assert "I could not match" in res_empty["message"] or "exact" in res_empty["message"]

    # Unknown invalid action
    res_invalid = computer_settings({"action": "fly_to_the_moon"})
    assert_structured_result(res_invalid, expected_action="fly_to_the_moon", expected_success=False)
    assert "fly_to_the_moon" in res_invalid["message"]
    print("  -> Errors and suggestions successfully formatted as structured dictionaries.")


def test_permission_rules_and_audit():
    print("Testing permission rules for Section 4 queries...")
    # Check permissions
    d_wifi = check_permission("computer_settings", "wifi_status")
    assert d_wifi.level == PermissionLevel.SAFE
    assert d_wifi.key == "computer_settings_wifi_status"

    d_batt = check_permission("computer_settings", "battery_status")
    assert d_batt.level == PermissionLevel.SAFE
    assert d_batt.key == "computer_settings_battery_status"

    d_bt = check_permission("computer_settings", "bluetooth_status")
    assert d_bt.level == PermissionLevel.SAFE
    assert d_bt.key == "computer_settings_bluetooth_status"

    # Static permission gate audit
    from core.action_loader import discover_actions
    registry = discover_actions(actions_dir=Path.cwd() / "actions")
    verify_permission_gates(registry)
    print("  -> Permission checks and verify_permission_gates audit passed cleanly.")


if __name__ == "__main__":
    print("=== RUNNING SECTION 4 TEST SUITE ===")
    test_wifi_status_live_and_dispatch()
    test_battery_status_live_and_dispatch()
    test_bluetooth_status_live_and_dispatch()
    test_volume_and_brightness_queries()
    test_structured_error_and_suggestions()
    test_permission_rules_and_audit()
    print("\nALL SECTION 4 TESTS PASSED SUCCESSFULLY!")
