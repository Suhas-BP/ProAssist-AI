"""
Comprehensive test suite for actions/reminder.py Section 13 additions.

Validates:
1. Relative-time and recurrence parsing showing REAL computed datetimes for:
   - "in 30 minutes"
   - "20 minutes rolling into next hour"
   - "20 minutes rolling past midnight"
   - "set a timer for 20 minutes"
   - "tomorrow at 9 AM"
   - "every Monday at 8 AM"
   - "daily at 5 PM"
   - "fixed YYYY-MM-DD HH:MM"
2. Local JSON storage (data/reminders.json)
3. Full CRUD operations with structured returns {"success", "action", "value", "message"}
4. Actual Windows Task Scheduler registration AND un-registration on update & deletion
   (confirming schtasks /Query fails for OLD task after update, and fails after delete)
5. Permission manager SAFE classification
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

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

from actions.reminder import (
    reminder,
    parse_reminder_spec,
    _storage_file,
    _load_reminders,
    TOOL,
)
from core.permission_manager import check_permission, PermissionLevel, verify_permission_gates


def test_parsing_real_datetimes():
    print("\n" + "=" * 60)
    print("TEST 1: Relative-Time & Recurrence Parsing (REAL DATETIMES)")
    print("=" * 60)

    now_ref = datetime(2026, 9, 25, 17, 30, 0)  # Friday 5:30 PM
    print(f"Reference Baseline 'Now': {now_ref.strftime('%Y-%m-%d %H:%M:%S (%A)')}\n")

    test_cases = [
        ("in 30 minutes", {"time_str": "in 30 minutes", "now": now_ref}),
        (
            "20 minutes rolling into next hour",
            {"time_str": "20 minutes", "now": datetime(2026, 9, 25, 17, 45, 0)},
        ),
        (
            "20 minutes rolling past midnight",
            {"time_str": "20 minutes", "now": datetime(2026, 9, 25, 23, 50, 0)},
        ),
        ("set a timer for 20 minutes", {"message": "set a timer for 20 minutes", "now": now_ref}),
        ("in 1.5 hours", {"time_str": "in 1.5 hours", "now": now_ref}),
        ("tomorrow at 9 AM", {"date_str": "tomorrow", "time_str": "9 AM", "now": now_ref}),
        ("today at 6 PM", {"date_str": "today", "time_str": "6 PM", "now": now_ref}),
        ("every Monday at 8 AM", {"time_str": "8 AM", "message": "every Monday", "now": now_ref}),
        ("daily at 5 PM", {"time_str": "5 PM", "recurrence": "daily", "now": now_ref}),
        ("fixed YYYY-MM-DD HH:MM", {"date_str": "2026-10-01", "time_str": "14:30", "now": now_ref}),
    ]

    for label, kwargs in test_cases:
        target, rec = parse_reminder_spec(**kwargs)
        base = kwargs.get("now", now_ref)
        print(f"Input Spec : '{label}'")
        print(f"  Base Time: {base.strftime('%Y-%m-%d %H:%M:%S (%A)')}")
        print(f"  -> COMPUTED DATETIME: {target.strftime('%Y-%m-%d %H:%M:%S (%A)')}")
        print(f"  -> Recurrence Rule  : {rec}")
        print()

    # Assertions on computed datetimes
    t1, _ = parse_reminder_spec(time_str="in 30 minutes", now=now_ref)
    assert t1 == datetime(2026, 9, 25, 18, 0, 0), f"Mismatch: {t1}"

    t2, _ = parse_reminder_spec(time_str="20 minutes", now=datetime(2026, 9, 25, 17, 45, 0))
    assert t2 == datetime(2026, 9, 25, 18, 5, 0), f"Hour roll mismatch: {t2}"

    t3, _ = parse_reminder_spec(time_str="20 minutes", now=datetime(2026, 9, 25, 23, 50, 0))
    assert t3 == datetime(2026, 9, 26, 0, 10, 0), f"Midnight roll mismatch: {t3}"

    t4, _ = parse_reminder_spec(date_str="tomorrow", time_str="9 AM", now=now_ref)
    assert t4 == datetime(2026, 9, 26, 9, 0, 0), f"Tomorrow mismatch: {t4}"

    t5, rec5 = parse_reminder_spec(time_str="8 AM", message="every Monday", now=now_ref)
    assert t5 == datetime(2026, 9, 28, 8, 0, 0) and rec5 == "weekly:Monday", f"Weekly mismatch: {t5}, {rec5}"

    t6, rec6 = parse_reminder_spec(time_str="5 PM", recurrence="daily", now=now_ref)
    assert t6 == datetime(2026, 9, 26, 17, 0, 0) and rec6 == "daily", f"Daily mismatch: {t6}, {rec6}"

    print("✅ All relative time & recurrence real datetimes verified correctly.")


def test_crud_and_task_scheduler():
    print("\n" + "=" * 60)
    print("TEST 2: Full CRUD Operations & Task Scheduler Integration")
    print("=" * 60)

    # 1. CREATE
    create_res = reminder({
        "action": "create",
        "message": "Drink water reminder test",
        "time": "in 15 minutes",
    })
    print(f"CREATE result: {create_res}")
    assert create_res["success"] is True, "Create failed"
    assert create_res["action"] == "create"
    assert "value" in create_res and "id" in create_res["value"]
    assert "message" in create_res

    rem_id = create_res["value"]["id"]
    task_name = create_res["value"]["task_name"]
    print(f"Created reminder ID: {rem_id}, Task Scheduler Name: {task_name}")

    # Verify JSON file has it
    storage_path = _storage_file()
    assert storage_path.exists(), "reminders.json not found"
    items = _load_reminders()
    assert any(r["id"] == rem_id for r in items), f"Reminder {rem_id} not saved to {storage_path}"

    # Verify schtasks /Query found it
    q_create = subprocess.run(["schtasks", "/Query", "/TN", task_name], capture_output=True, text=True)
    print(f"Task Scheduler Query AFTER CREATE: returncode={q_create.returncode}")
    assert q_create.returncode == 0, f"Task {task_name} was NOT found in Windows Task Scheduler!"

    # 2. LIST
    list_res = reminder({"action": "list"})
    print(f"LIST result: {list_res['message']} (total: {list_res['value']['total']})")
    assert list_res["success"] is True
    assert list_res["action"] == "list"
    assert any(r["id"] == rem_id for r in list_res["value"]["reminders"])

    # 3. UPDATE
    update_res = reminder({
        "action": "update",
        "id": rem_id,
        "message": "Drink hot green tea",
        "time": "in 25 minutes",
    })
    print(f"UPDATE result: {update_res['message']}")
    assert update_res["success"] is True
    assert update_res["action"] == "update"
    new_task_name = update_res["value"]["task_name"]
    print(f"Updated Task Scheduler Name: {new_task_name}")

    # Explicit check: Old task name MUST be un-registered from Task Scheduler
    q_old = subprocess.run(["schtasks", "/Query", "/TN", task_name], capture_output=True, text=True)
    err_old = (q_old.stderr or q_old.stdout).strip()
    print(f"Task Scheduler Query for OLD TASK ({task_name}) AFTER UPDATE: returncode={q_old.returncode} -> Output: '{err_old}'")
    assert q_old.returncode != 0, f"Old task {task_name} was still present in Task Scheduler after update!"
    print(f"  -> [OK] Confirmed OLD task ({task_name}) was successfully un-scheduled on update.")

    # New task name should exist
    q_new = subprocess.run(["schtasks", "/Query", "/TN", new_task_name], capture_output=True, text=True)
    print(f"Task Scheduler Query for NEW TASK ({new_task_name}) AFTER UPDATE: returncode={q_new.returncode}")
    assert q_new.returncode == 0, f"New task {new_task_name} not found after update!"

    # 4. DELETE
    delete_res = reminder({
        "action": "delete",
        "id": rem_id,
    })
    print(f"DELETE result: {delete_res}")
    assert delete_res["success"] is True
    assert delete_res["action"] == "delete"
    assert delete_res["value"]["unscheduled"] is True

    # Confirm removed from JSON
    items_after = _load_reminders()
    assert not any(r["id"] == rem_id for r in items_after), "Reminder still in JSON after delete!"

    # Confirm Task Scheduler entry is ACTUALLY REMOVED (not just from JSON)
    q_after_del = subprocess.run(["schtasks", "/Query", "/TN", new_task_name], capture_output=True, text=True)
    err_del = (q_after_del.stderr or q_after_del.stdout).strip()
    print(f"Task Scheduler Query AFTER DELETE: returncode={q_after_del.returncode} -> Output: '{err_del}'")
    assert q_after_del.returncode != 0, f"Task {new_task_name} STILL EXISTS in Windows Task Scheduler after delete!"
    print("✅ Verified: Deleted reminder's Windows Task Scheduler entry is completely removed from OS!")


def test_recurring_reminder_lifecycle():
    print("\n" + "=" * 60)
    print("TEST 3: Recurring Reminder Lifecycle (Weekly / Daily)")
    print("=" * 60)

    # Weekly recurring creation
    create_rec = reminder({
        "action": "create",
        "message": "Weekly Monday Sync",
        "time": "8 AM",
        "recurrence": "weekly:Monday",
    })
    print(f"Recurring CREATE: {create_rec['message']}")
    assert create_rec["success"] is True
    rec_id = create_rec["value"]["id"]
    rec_task = create_rec["value"]["task_name"]

    # Verify task exists in scheduler
    q_rec = subprocess.run(["schtasks", "/Query", "/TN", rec_task], capture_output=True, text=True)
    assert q_rec.returncode == 0, f"Recurring task {rec_task} not found in Task Scheduler!"

    # Delete recurring reminder
    del_rec = reminder({"action": "delete", "id": rec_id})
    print(f"Recurring DELETE: {del_rec['message']}")
    assert del_rec["success"] is True

    # Confirm task un-registered
    q_rec_del = subprocess.run(["schtasks", "/Query", "/TN", rec_task], capture_output=True, text=True)
    assert q_rec_del.returncode != 0, f"Recurring task {rec_task} was not removed from Task Scheduler!"
    print("✅ Recurring reminder created and un-scheduled cleanly.")


def test_tool_declaration_and_permissions():
    print("\n" + "=" * 60)
    print("TEST 4: TOOL Declaration & POLICY_RULES Permission Classification")
    print("=" * 60)

    # TOOL declaration checks
    assert TOOL["name"] == "reminder"
    assert callable(TOOL["handler"])
    assert "action" in TOOL["parameters"]["properties"]
    assert "create" in TOOL["parameters"]["properties"]["action"]["description"]
    print("✅ TOOL declaration is discoverable and complete.")

    # POLICY_RULES checks
    for act in ["create", "list", "update", "delete", None]:
        dec = check_permission("reminder", act)
        print(f"Permission check for reminder.{act} -> Level: {dec.level.value}, Reason: '{dec.reason}'")
        assert dec.level == PermissionLevel.SAFE, f"Expected SAFE for {act}, got {dec.level}"

    print("✅ All reminder CRUD actions confirmed SAFE in POLICY_RULES.")


if __name__ == "__main__":
    test_parsing_real_datetimes()
    test_crud_and_task_scheduler()
    test_recurring_reminder_lifecycle()
    test_tool_declaration_and_permissions()
    print("\n" + "=" * 60)
    print("ALL SECTION 13 REMINDER TESTS PASSED!")
    print("=" * 60)
