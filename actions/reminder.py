"""
Actions: Timed Reminders with Local Storage & OS Scheduler Support.

Supports:
- Relative-time parsing ("in 30 minutes", "set a timer for 20 minutes", "tomorrow at 9 AM")
- Recurrence (daily, weekly)
- Lightweight local JSON storage (data/reminders.json)
- Full CRUD operations: create, list, update, delete (with Task Scheduler un-registration)
- Structured return format: {"success", "action", "value", "message"}
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import dateutil.parser

from core.tool import AgentTool, ToolResult

_CNW: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if platform.system() == "Windows" else {}
)

DAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6
}


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_os() -> str:
    _sys = platform.system()
    if _sys == "Darwin":
        return "mac"
    if _sys == "Linux":
        return "linux"
    return "windows"


def _scripts_dir() -> Path:
    d = Path.home() / ".jarvis" / "reminders"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _storage_file() -> Path:
    data_dir = _base_dir() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "reminders.json"


def _sanitise(text: str, max_len: int = 200) -> str:
    return (
        text.replace("\\", "")
            .replace('"', "")
            .replace("'", "")
            .replace("\n", " ")
            .replace("\r", "")
            .strip()
    )[:max_len]


# ── Local Storage Helpers ────────────────────────────────────────────────────

def _load_reminders() -> List[Dict[str, Any]]:
    f = _storage_file()
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "reminders" in data and isinstance(data["reminders"], list):
            return data["reminders"]
        return []
    except Exception:
        return []


def _save_reminders(reminders: List[Dict[str, Any]]) -> None:
    f = _storage_file()
    payload = {"reminders": reminders}
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


# ── Time & Recurrence Parsing ────────────────────────────────────────────────

def parse_reminder_spec(
    time_str: str = "",
    date_str: str = "",
    message: str = "",
    recurrence: str = "",
    now: Optional[datetime] = None,
) -> Tuple[datetime, Optional[str]]:
    """
    Parses datetime and recurrence from natural language or structured inputs.
    Returns: (target_datetime, recurrence_rule)
    """
    if now is None:
        now = datetime.now()

    time_raw = (time_str or "").strip()
    date_raw = (date_str or "").strip()
    msg_raw = (message or "").strip()
    rec_raw = (recurrence or "").strip()

    combined = f"{date_raw} {time_raw} {msg_raw} {rec_raw}".strip()

    # 1. Detect recurrence rule
    rec_rule = None
    if rec_raw:
        r_lower = rec_raw.lower()
        if r_lower in ("daily", "every day", "everyday"):
            rec_rule = "daily"
        elif r_lower.startswith("every "):
            day = r_lower.split()[1].capitalize()
            rec_rule = f"weekly:{day}"
        elif r_lower.startswith("weekly"):
            rec_rule = rec_raw
    else:
        m_daily = re.search(r"\b(every\s*day|daily)\b", combined, re.I)
        if m_daily:
            rec_rule = "daily"
        else:
            m_weekly = re.search(
                r"\bevery\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
                combined, re.I
            )
            if m_weekly:
                day_name = m_weekly.group(1).capitalize()
                rec_rule = f"weekly:{day_name}"

    # 2. Check for relative offsets ("in 30 minutes", "set a timer for 20 minutes", "in 2 hours", etc.)
    offset_candidate = f"{date_raw} {time_raw}".strip() or msg_raw
    rel_m = re.search(r"(?:in|for)?\s*(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|m)\b", offset_candidate, re.I)
    rel_h = re.search(r"(?:in|for)?\s*(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", offset_candidate, re.I)
    rel_s = re.search(r"(?:in|for)?\s*(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b", offset_candidate, re.I)

    has_calendar_keyword = bool(re.search(r"\b(at|tomorrow|yesterday|today|\d{4}-\d{2}-\d{2})\b", offset_candidate, re.I))
    is_pure_rel = bool(rel_m or rel_h or rel_s) and not has_calendar_keyword

    if is_pure_rel:
        mins = float(rel_m.group(1)) if rel_m else 0.0
        hrs = float(rel_h.group(1)) if rel_h else 0.0
        secs = float(rel_s.group(1)) if rel_s else 0.0
        target = now + timedelta(hours=hrs, minutes=mins, seconds=secs)
        return target.replace(microsecond=0), rec_rule

    # 3. Recurrence handling (Weekly / Daily)
    if rec_rule and rec_rule.startswith("weekly"):
        if ":" in rec_rule:
            target_day_name = rec_rule.split(":", 1)[1].lower()
        else:
            target_day_name = "monday"
        target_weekday = DAYS.get(target_day_name, 0)

        time_part = time_raw or "09:00"
        t_match = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", time_part, re.I)
        if t_match:
            time_dt = dateutil.parser.parse(t_match.group(1), default=datetime(now.year, now.month, now.day, 9, 0, 0))
        else:
            time_dt = datetime(now.year, now.month, now.day, 9, 0, 0)

        days_ahead = target_weekday - now.weekday()
        if days_ahead < 0 or (days_ahead == 0 and (now.hour, now.minute) >= (time_dt.hour, time_dt.minute)):
            days_ahead += 7
        target_date = now.date() + timedelta(days=days_ahead)
        target = datetime(target_date.year, target_date.month, target_date.day, time_dt.hour, time_dt.minute, 0)
        return target, rec_rule

    if rec_rule == "daily":
        time_part = time_raw or "09:00"
        t_match = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", time_part, re.I)
        if t_match:
            time_dt = dateutil.parser.parse(t_match.group(1), default=datetime(now.year, now.month, now.day, 9, 0, 0))
        else:
            time_dt = datetime(now.year, now.month, now.day, 9, 0, 0)
        target = datetime(now.year, now.month, now.day, time_dt.hour, time_dt.minute, 0)
        if target <= now:
            target += timedelta(days=1)
        return target, rec_rule

    # 4. Standard / Day + Time parsing
    combined_dt_str = f"{date_raw} {time_raw}".strip()
    base_day = now.date()
    if re.search(r"\btomorrow\b", combined_dt_str, re.I):
        base_day = now.date() + timedelta(days=1)
    elif re.search(r"\btoday\b", combined_dt_str, re.I):
        base_day = now.date()
    elif date_raw:
        try:
            parsed_d = dateutil.parser.parse(date_raw, default=now).date()
            base_day = parsed_d
        except Exception:
            pass

    clean_time = re.sub(r"\b(tomorrow|today|at)\b", "", combined_dt_str, flags=re.I).strip()
    if not clean_time:
        clean_time = "09:00"

    default_dt = datetime(base_day.year, base_day.month, base_day.day, 0, 0, 0)
    parsed_time = dateutil.parser.parse(clean_time, default=default_dt)
    target = datetime(base_day.year, base_day.month, base_day.day, parsed_time.hour, parsed_time.minute, 0)

    if not date_raw and not re.search(r"\btomorrow\b", combined, re.I) and target <= now:
        target += timedelta(days=1)

    return target, rec_rule


# ── Notification Script & OS Schedulers ──────────────────────────────────────

def _write_notify_script(task_name: str, message: str, os_name: str, is_recurring: bool = False) -> Path:
    script_path = _scripts_dir() / f"{task_name}.py"
    msg_literal = json.dumps(message)

    if os_name == "windows":
        notify_block = f"""
message = {msg_literal}
notified = False

try:
    from plyer import notification
    notification.notify(title="AGENT Reminder", message=message, timeout=15)
    notified = True
except Exception:
    pass

if not notified:
    try:
        from win10toast import ToastNotifier
        ToastNotifier().show_toast("AGENT Reminder", message, duration=15, threaded=False)
        notified = True
    except Exception:
        pass

if not notified:
    try:
        import subprocess
        subprocess.run(["msg", "*", "/TIME:30", message], check=False)
    except Exception:
        pass

try:
    import winsound
    for freq in [800, 1000, 1200]:
        winsound.Beep(freq, 180)
        import time; time.sleep(0.08)
except Exception:
    pass
"""

    elif os_name == "mac":
        notify_block = f"""
message = {msg_literal}
notified = False

try:
    from plyer import notification
    notification.notify(title="AGENT Reminder", message=message, timeout=15)
    notified = True
except Exception:
    pass

if not notified:
    try:
        import subprocess
        script = 'display notification "{{}}" with title "AGENT Reminder"'.format(
            message.replace('"', '')
        )
        subprocess.run(["osascript", "-e", script], check=False)
    except Exception:
        pass
"""

    else:  # linux
        notify_block = f"""
message = {msg_literal}
notified = False

try:
    from plyer import notification
    notification.notify(title="AGENT Reminder", message=message, timeout=15)
    notified = True
except Exception:
    pass

if not notified:
    try:
        import subprocess
        subprocess.run(
            ["notify-send", "--urgency=normal", "--expire-time=15000",
             "AGENT Reminder", message],
            check=False
        )
    except Exception:
        pass
"""

    self_delete_code = ""
    if not is_recurring:
        self_delete_code = """
# Self-delete after firing (non-recurring only)
try:
    pathlib.Path(__file__).unlink(missing_ok=True)
except Exception:
    pass
"""

    script_body = f"""# Auto-generated by AGENT reminder — do not edit
import sys, os, pathlib
{notify_block}
{self_delete_code}
"""
    script_path.write_text(script_body, encoding="utf-8")
    script_path.chmod(0o600)   # owner read/write only
    return script_path


def _schedule_windows(
    target_dt: datetime,
    task_name: str,
    script_path: Path,
    message: str,
    recurrence: Optional[str] = None,
) -> str:
    python_exe = Path(sys.executable)
    pythonw = python_exe.parent / "pythonw.exe"
    if pythonw.exists():
        python_exe = pythonw

    xml_path = _scripts_dir() / f"{task_name}.xml"

    # Build Trigger XML (One-shot, Daily recurrence, or Weekly recurrence)
    if recurrence == "daily":
        trigger_xml = (
            "  <Triggers><CalendarTrigger>\n"
            f'    <StartBoundary>{target_dt.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>\n'
            "    <Enabled>true</Enabled>\n"
            "    <ScheduleByDay>\n"
            "      <DaysInterval>1</DaysInterval>\n"
            "    </ScheduleByDay>\n"
            "  </CalendarTrigger></Triggers>\n"
        )
    elif recurrence and recurrence.lower().startswith("weekly"):
        if ":" in recurrence:
            day_name = recurrence.split(":", 1)[1].capitalize()
        else:
            day_name = target_dt.strftime("%A")
        trigger_xml = (
            "  <Triggers><CalendarTrigger>\n"
            f'    <StartBoundary>{target_dt.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>\n'
            "    <Enabled>true</Enabled>\n"
            "    <ScheduleByWeek>\n"
            "      <DaysOfWeek>\n"
            f"        <{day_name} />\n"
            "      </DaysOfWeek>\n"
            "      <WeeksInterval>1</WeeksInterval>\n"
            "    </ScheduleByWeek>\n"
            "  </CalendarTrigger></Triggers>\n"
        )
    else:
        trigger_xml = (
            "  <Triggers><TimeTrigger>\n"
            f'    <StartBoundary>{target_dt.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>\n'
            "    <Enabled>true</Enabled>\n"
            "  </TimeTrigger></Triggers>\n"
        )

    xml_content = (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        '  <RegistrationInfo><Description>AGENT Reminder</Description></RegistrationInfo>\n'
        f"{trigger_xml}"
        '  <Actions><Exec>\n'
        f'    <Command>{python_exe}</Command>\n'
        f'    <Arguments>"{script_path}"</Arguments>\n'
        '  </Exec></Actions>\n'
        '  <Settings>\n'
        '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n'
        '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n'
        '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n'
        '    <StartWhenAvailable>true</StartWhenAvailable>\n'
        '    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>\n'
        '    <Enabled>true</Enabled>\n'
        '  </Settings>\n'
        '  <Principals><Principal>\n'
        '    <LogonType>InteractiveToken</LogonType>\n'
        '    <RunLevel>LeastPrivilege</RunLevel>\n'
        '  </Principal></Principals>\n'
        '</Task>'
    )

    xml_path.write_text(xml_content, encoding="utf-16")

    result = subprocess.run(
        ["schtasks", "/Create", "/TN", task_name, "/XML", str(xml_path), "/F"],
        capture_output=True, text=True, **_CNW,
    )

    try:
        xml_path.unlink(missing_ok=True)
    except Exception:
        pass

    if result.returncode != 0:
        script_path.unlink(missing_ok=True)
        err = (result.stderr or result.stdout).strip()
        print(f"[Reminder] ❌ schtasks: {err}")
        return ""

    return task_name


def _schedule_mac(target_dt: datetime, task_name: str, script_path: Path) -> str:
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    label     = f"com.jarvis.reminder.{task_name}"
    plist_path = agents_dir / f"{label}.plist"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>             <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable}</string>
    <string>{script_path}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Year</key>   <integer>{target_dt.year}</integer>
    <key>Month</key>  <integer>{target_dt.month}</integer>
    <key>Day</key>    <integer>{target_dt.day}</integer>
    <key>Hour</key>   <integer>{target_dt.hour}</integer>
    <key>Minute</key> <integer>{target_dt.minute}</integer>
  </dict>
  <key>RunAtLoad</key>         <false/>
  <key>StandardOutPath</key>   <string>/dev/null</string>
  <key>StandardErrorPath</key> <string>/dev/null</string>
</dict>
</plist>
"""
    plist_path.write_text(plist_content, encoding="utf-8")
    plist_path.chmod(0o644)

    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        plist_path.unlink(missing_ok=True)
        script_path.unlink(missing_ok=True)
        print(f"[Reminder] ❌ launchctl: {result.stderr.strip()}")
        return ""

    return label


def _schedule_linux(target_dt: datetime, task_name: str, script_path: Path) -> str:
    if shutil.which("systemd-run"):
        on_calendar = target_dt.strftime("%Y-%m-%d %H:%M:00")
        result = subprocess.run(
            [
                "systemd-run",
                "--user",
                f"--on-calendar={on_calendar}",
                f"--unit={task_name}",
                "--",
                sys.executable, str(script_path),
            ],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return task_name
        print(f"[Reminder] ⚠️ systemd-run failed: {result.stderr.strip()}, trying 'at'")

    if shutil.which("at"):
        at_time = target_dt.strftime("%H:%M %Y-%m-%d")
        cmd_str = f"{sys.executable} {script_path}\n"
        result  = subprocess.run(
            ["at", at_time],
            input=cmd_str, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return task_name
        print(f"[Reminder] ❌ at: {result.stderr.strip()}")
        return ""

    print("[Reminder] ❌ Neither systemd-run nor at found on this Linux system.")
    return ""


def _cancel_scheduled_task(task_name: str, os_name: Optional[str] = None) -> bool:
    if not task_name:
        return False
    if os_name is None:
        os_name = _get_os()

    cancelled = False
    if os_name == "windows":
        res = subprocess.run(
            ["schtasks", "/Delete", "/TN", task_name, "/F"],
            capture_output=True, text=True, **_CNW
        )
        cancelled = (res.returncode == 0)
    elif os_name == "mac":
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"com.jarvis.reminder.{task_name}.plist"
        res = subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True, text=True)
        plist_path.unlink(missing_ok=True)
        cancelled = (res.returncode == 0)
    else:  # linux
        res = subprocess.run(["systemctl", "--user", "stop", task_name], capture_output=True, text=True)
        cancelled = (res.returncode == 0)

    # Clean up Python notify script
    script_path = _scripts_dir() / f"{task_name}.py"
    try:
        script_path.unlink(missing_ok=True)
    except Exception:
        pass

    return cancelled


# ── CRUD Operations ──────────────────────────────────────────────────────────

def _create_reminder(parameters: Dict[str, Any], os_name: str, player=None) -> Dict[str, Any]:
    time_str = parameters.get("time", "").strip()
    date_str = parameters.get("date", "").strip()
    message  = parameters.get("message") or parameters.get("original_text") or parameters.get("text") or "Reminder"
    message  = str(message).strip()
    recurrence = parameters.get("recurrence", "").strip()

    if not time_str and not date_str and not message:
        return {
            "success": False,
            "action": "create",
            "value": None,
            "message": "I need a time or message to set a reminder.",
        }

    try:
        target_dt, detected_rec = parse_reminder_spec(
            time_str=time_str,
            date_str=date_str,
            message=message,
            recurrence=recurrence,
        )
    except Exception as e:
        return {
            "success": False,
            "action": "create",
            "value": None,
            "message": f"I couldn't parse the reminder time: {e}",
        }

    final_rec = detected_rec or recurrence or None

    # Check for past non-recurring target time
    if not final_rec and target_dt <= datetime.now():
        return {
            "success": False,
            "action": "create",
            "value": None,
            "message": "That time has already passed — I can't set a reminder in the past.",
        }

    safe_msg = _sanitise(message)
    rem_id_suffix = uuid.uuid4().hex[:4]
    reminder_id = f"rem_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{rem_id_suffix}"
    task_name = f"AGENTReminder_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{rem_id_suffix}"

    try:
        script_path = _write_notify_script(
            task_name=task_name,
            message=safe_msg,
            os_name=os_name,
            is_recurring=bool(final_rec),
        )
    except Exception as e:
        return {
            "success": False,
            "action": "create",
            "value": None,
            "message": f"Could not prepare the reminder script: {e}",
        }

    try:
        if os_name == "windows":
            job_id = _schedule_windows(
                target_dt=target_dt,
                task_name=task_name,
                script_path=script_path,
                message=safe_msg,
                recurrence=final_rec,
            )
        elif os_name == "mac":
            job_id = _schedule_mac(target_dt, task_name, script_path)
        else:
            job_id = _schedule_linux(target_dt, task_name, script_path)
    except Exception as e:
        script_path.unlink(missing_ok=True)
        return {
            "success": False,
            "action": "create",
            "value": None,
            "message": f"Scheduling error: {e}",
        }

    if not job_id:
        return {
            "success": False,
            "action": "create",
            "value": None,
            "message": "I couldn't register the reminder with the system scheduler.",
        }

    friendly_time = target_dt.strftime("%B %d at %I:%M %p")
    rec_desc = f" (recurring: {final_rec})" if final_rec else ""

    record = {
        "id": reminder_id,
        "message": safe_msg,
        "original_text": message,
        "target_time": target_dt.isoformat(),
        "target_time_friendly": friendly_time,
        "recurrence": final_rec,
        "task_name": task_name,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    }

    # Save to local JSON
    reminders = _load_reminders()
    reminders.append(record)
    _save_reminders(reminders)

    if player:
        player.write_log(f"[Reminder] ✅ {reminder_id} ({friendly_time}{rec_desc}) — {safe_msg[:40]}")

    return {
        "success": True,
        "action": "create",
        "value": record,
        "message": f"Reminder set for {friendly_time}{rec_desc}.",
    }


def _list_reminders(parameters: Dict[str, Any]) -> Dict[str, Any]:
    reminders = _load_reminders()
    status_filter = str(parameters.get("status") or "all").strip().lower()
    rec_filter = parameters.get("recurrence")

    filtered = []
    for r in reminders:
        if status_filter != "all" and str(r.get("status", "")).lower() != status_filter:
            continue
        if rec_filter and r.get("recurrence") != rec_filter:
            continue
        filtered.append(r)

    return {
        "success": True,
        "action": "list",
        "value": {
            "total": len(filtered),
            "reminders": filtered,
        },
        "message": f"Found {len(filtered)} reminder(s).",
    }


def _update_reminder(parameters: Dict[str, Any], os_name: str) -> Dict[str, Any]:
    target_id = str(parameters.get("id") or "").strip()
    if not target_id:
        return {
            "success": False,
            "action": "update",
            "value": None,
            "message": "Reminder ID is required to update a reminder.",
        }

    reminders = _load_reminders()
    found_idx = -1
    for i, r in enumerate(reminders):
        if r.get("id") == target_id or r.get("task_name") == target_id:
            found_idx = i
            break

    if found_idx == -1:
        return {
            "success": False,
            "action": "update",
            "value": None,
            "message": f"Reminder with ID '{target_id}' not found.",
        }

    record = reminders[found_idx]

    # Un-schedule existing task from OS scheduler
    old_task_name = record.get("task_name")
    if old_task_name:
        _cancel_scheduled_task(old_task_name, os_name)

    # Compute updated attributes
    new_msg = parameters.get("message") or record.get("message") or "Reminder"
    new_time_str = parameters.get("time") or ""
    new_date_str = parameters.get("date") or ""
    new_rec = parameters.get("recurrence")

    if not new_time_str and not new_date_str:
        # Keep existing target time if no new time provided
        target_dt = datetime.fromisoformat(record["target_time"])
        final_rec = new_rec if new_rec is not None else record.get("recurrence")
    else:
        target_dt, detected_rec = parse_reminder_spec(
            time_str=new_time_str,
            date_str=new_date_str,
            message=new_msg,
            recurrence=new_rec if new_rec is not None else (record.get("recurrence") or ""),
        )
        final_rec = detected_rec if detected_rec is not None else new_rec

    safe_msg = _sanitise(new_msg)
    rem_id_suffix = uuid.uuid4().hex[:4]
    new_task_name = f"AGENTReminder_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{rem_id_suffix}"

    try:
        script_path = _write_notify_script(
            task_name=new_task_name,
            message=safe_msg,
            os_name=os_name,
            is_recurring=bool(final_rec),
        )
        if os_name == "windows":
            _schedule_windows(
                target_dt=target_dt,
                task_name=new_task_name,
                script_path=script_path,
                message=safe_msg,
                recurrence=final_rec,
            )
        elif os_name == "mac":
            _schedule_mac(target_dt, new_task_name, script_path)
        else:
            _schedule_linux(target_dt, new_task_name, script_path)
    except Exception as e:
        return {
            "success": False,
            "action": "update",
            "value": None,
            "message": f"Failed to re-schedule updated reminder: {e}",
        }

    friendly_time = target_dt.strftime("%B %d at %I:%M %p")
    record.update({
        "message": safe_msg,
        "target_time": target_dt.isoformat(),
        "target_time_friendly": friendly_time,
        "recurrence": final_rec,
        "task_name": new_task_name,
        "status": "pending",
        "updated_at": datetime.now().isoformat(),
    })

    reminders[found_idx] = record
    _save_reminders(reminders)

    return {
        "success": True,
        "action": "update",
        "value": record,
        "message": f"Reminder '{target_id}' updated for {friendly_time}.",
    }


def _delete_reminder(parameters: Dict[str, Any], os_name: str) -> Dict[str, Any]:
    target_id = str(parameters.get("id") or "").strip()
    if not target_id:
        return {
            "success": False,
            "action": "delete",
            "value": None,
            "message": "Reminder ID is required to delete a reminder.",
        }

    reminders = _load_reminders()
    target_record = None
    remaining = []
    for r in reminders:
        if r.get("id") == target_id or r.get("task_name") == target_id:
            target_record = r
        else:
            remaining.append(r)

    if not target_record:
        return {
            "success": False,
            "action": "delete",
            "value": None,
            "message": f"Reminder with ID '{target_id}' not found.",
        }

    # Cancel in OS Task Scheduler
    task_name = target_record.get("task_name")
    unscheduled = False
    if task_name:
        unscheduled = _cancel_scheduled_task(task_name, os_name)

    _save_reminders(remaining)

    return {
        "success": True,
        "action": "delete",
        "value": {
            "id": target_id,
            "task_name": task_name,
            "unscheduled": unscheduled,
        },
        "message": f"Reminder '{target_id}' successfully deleted and un-scheduled.",
    }


# ── Main Handler ─────────────────────────────────────────────────────────────

def reminder(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> dict:
    os_name = _get_os()
    raw_action = str(parameters.get("action") or "").strip().lower()

    if not raw_action:
        # Infer action from parameters
        if "id" in parameters and not any(k in parameters for k in ("time", "date", "message")):
            raw_action = "delete" if parameters.get("delete") else "list"
        elif "id" in parameters and any(k in parameters for k in ("time", "date", "message", "recurrence")):
            raw_action = "update"
        elif not parameters or (len(parameters) == 1 and "status" in parameters):
            raw_action = "list"
        else:
            raw_action = "create"

    if raw_action in ("create", "add", "set", "new"):
        return _create_reminder(parameters, os_name=os_name, player=player)
    elif raw_action in ("list", "show", "get", "all", "query"):
        return _list_reminders(parameters)
    elif raw_action in ("update", "edit", "modify", "change"):
        return _update_reminder(parameters, os_name=os_name)
    elif raw_action in ("delete", "remove", "cancel", "del"):
        return _delete_reminder(parameters, os_name=os_name)
    else:
        return {
            "success": False,
            "action": raw_action,
            "value": None,
            "message": f"Unknown reminder action '{raw_action}'. Supported: create, list, update, delete.",
        }


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
class ReminderTool(AgentTool):
    @property
    def name(self) -> str:
        return "reminder"

    @property
    def description(self) -> str:
        return (
            "Manages reminders with local JSON storage and OS Task Scheduler. "
            "Supports relative time (e.g. 'in 30 minutes', 'tomorrow at 9 AM'), "
            "recurrence (daily, weekly), and full CRUD operations: "
            "create, list, update, and delete."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": (
                        "CRUD action to perform: "
                        "create (set a new reminder) | "
                        "list (view pending/existing reminders) | "
                        "update (change reminder time/message by ID) | "
                        "delete (remove reminder and un-schedule task by ID)"
                    ),
                },
                "id": {
                    "type": "STRING",
                    "description": "Unique reminder ID (e.g. 'rem_...') for update or delete actions.",
                },
                "message": {
                    "type": "STRING",
                    "description": "Reminder text or notification message.",
                },
                "time": {
                    "type": "STRING",
                    "description": (
                        "Target time or relative offset. Examples: "
                        "'in 20 minutes', 'in 2 hours', '09:00', '9 AM', '17:30', '5:30 PM'."
                    ),
                },
                "date": {
                    "type": "STRING",
                    "description": "Date for reminder. Examples: 'tomorrow', 'today', '2026-09-26'.",
                },
                "recurrence": {
                    "type": "STRING",
                    "description": "Recurrence pattern: 'daily' or 'weekly:DayName' (e.g. 'weekly:Monday').",
                },
                "status": {
                    "type": "STRING",
                    "description": "Filter for list action: 'all', 'pending', or 'cancelled'.",
                },
            },
            "required": [],
        }

    def execute(self, parameters: dict = None, **context):
        return reminder(parameters=parameters, **context)


ACTION = ReminderTool()
TOOL = ACTION.to_tool_dict()
