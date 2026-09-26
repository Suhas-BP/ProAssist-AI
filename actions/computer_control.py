#computer_control.py
import sys
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import io
import json
import platform
import re
import string
import subprocess

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}
import time
import random
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE         = _base_dir()
_CONFIG_PATH  = _BASE / "config" / "api_keys.json"
_MEMORY_PATH  = _BASE / "memory" / "long_term.json"

def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _platform_os() -> str:
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(
        platform.system(), "linux"
    )

def _get_os() -> str:
    return _load_config().get("os_system", _platform_os()).lower()


def _get_api_key() -> str:
    return _load_config().get("gemini_api_key", "")

_SAFE_SCREENSHOT_ROOTS = (
    Path.home(),
    Path.cwd(),
)

def _safe_screenshot_path(requested: str | None) -> Path:
    fallback = Path.home() / "Pictures" / "screenshot.png"
    if not fallback.parent.exists():
        fallback = Path.home() / "Desktop" / "screenshot.png"
    if not requested:
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return fallback
    try:
        p = Path(requested).expanduser().resolve()
        for root in _SAFE_SCREENSHOT_ROOTS:
            if p.resolve() == root.resolve() or p.resolve().is_relative_to(root.resolve()):
                p.parent.mkdir(parents=True, exist_ok=True)
                return p
    except Exception:
        pass
    fallback.parent.mkdir(parents=True, exist_ok=True)
    return fallback

def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")

_FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Drew", "Quinn",
    "Avery", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Harper",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]


def _random_data(data_type: str) -> str:
    dt = data_type.lower().strip()

    if dt == "first_name":
        return random.choice(_FIRST_NAMES)

    if dt == "last_name":
        return random.choice(_LAST_NAMES)

    if dt == "name":
        return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"

    if dt == "email":
        first = random.choice(_FIRST_NAMES).lower()
        last  = random.choice(_LAST_NAMES).lower()
        num   = random.randint(10, 999)
        return f"{first}.{last}{num}@{random.choice(_DOMAINS)}"

    if dt == "username":
        return f"{random.choice(_FIRST_NAMES).lower()}{random.randint(100, 9999)}"

    if dt == "password":
        chars = string.ascii_letters + string.digits + "!@#$%"
        raw   = (
            random.choice(string.ascii_uppercase)
            + random.choice(string.digits)
            + random.choice("!@#$%")
            + "".join(random.choices(chars, k=9))
        )
        return "".join(random.sample(raw, len(raw)))

    if dt == "phone":
        return f"+1{random.randint(200,999)}{random.randint(1_000_000, 9_999_999)}"

    if dt == "birthday":
        y = random.randint(1980, 2000)
        m = random.randint(1, 12)
        d = random.randint(1, 28)
        return f"{m:02d}/{d:02d}/{y}"

    if dt == "address":
        num    = random.randint(100, 9999)
        street = random.choice(["Main St", "Oak Ave", "Park Blvd", "Elm St", "Cedar Ln"])
        return f"{num} {street}"

    if dt == "zip_code":
        return str(random.randint(10000, 99999))

    if dt == "city":
        return random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"])

    return f"random_{data_type}_{random.randint(1000, 9999)}"

def _user_profile() -> dict:
    """Read identity fields from long-term memory."""
    try:
        if _MEMORY_PATH.exists():
            data     = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
            identity = data.get("identity", {})
            return {k: v.get("value", "") for k, v in identity.items()}
    except Exception:
        pass
    return {}

def _type(text: str, interval: float = 0.03) -> str:
    _require_pyautogui()
    time.sleep(0.3)
    pyautogui.typewrite(text, interval=interval)
    return f"Typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _smart_type(text: str, clear_first: bool = True) -> str:
    _require_pyautogui()
    if clear_first:
        _clear_field()
        time.sleep(0.1)

    if len(text) > 20 and _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        paste_key = "command" if _get_os() == "mac" else "ctrl"
        pyautogui.hotkey(paste_key, "v")
        return f"Smart-typed (clipboard): {text[:60]}{'…' if len(text) > 60 else ''}"

    pyautogui.typewrite(text, interval=0.04)
    return f"Smart-typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _click(x=None, y=None, button: str = "left", clicks: int = 1, interaction: str = "single") -> str:
    _require_pyautogui()
    if interaction == "double" or clicks == 2:
        clicks = 2
    else:
        clicks = 1
    if x is not None and y is not None:
        pyautogui.click(x, y, button=button, clicks=clicks)
        return f"{'Double-c' if clicks == 2 else 'C'}licked ({x}, {y}) [{button}]"
    pyautogui.click(button=button, clicks=clicks)
    return f"{'Double-c' if clicks == 2 else 'C'}licked at current position [{button}]"


def _hotkey(*keys) -> str:
    _require_pyautogui()
    pyautogui.hotkey(*keys)
    return f"Hotkey: {'+'.join(keys)}"


def _press(key: str) -> str:
    _require_pyautogui()
    pyautogui.press(key)
    return f"Pressed: {key}"


def _scroll(direction: str = "down", amount: int = 3) -> str:
    _require_pyautogui()
    vertical   = direction in ("up", "down")
    clicks     = amount if direction in ("up", "right") else -amount
    pyautogui.scroll(clicks) if vertical else pyautogui.hscroll(clicks)
    return f"Scrolled {direction} ×{amount}"


def _move(x: int, y: int, duration: float = 0.3) -> str:
    _require_pyautogui()
    pyautogui.moveTo(x, y, duration=duration)
    return f"Mouse → ({x}, {y})"


def _drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> str:
    _require_pyautogui()
    pyautogui.moveTo(x1, y1, duration=0.2)
    pyautogui.dragTo(x2, y2, duration=duration, button="left")
    return f"Dragged ({x1},{y1}) → ({x2},{y2})"


def _clipboard_get() -> str:
    if _PYPERCLIP:
        return pyperclip.paste()
    _hotkey("ctrl", "c")
    time.sleep(0.2)
    return "(copied — pyperclip unavailable for read)"


def _clipboard_paste(text: str) -> str:
    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        _require_pyautogui()
        paste_key = "command" if _get_os() == "mac" else "ctrl"
        pyautogui.hotkey(paste_key, "v")
        return f"Pasted: {text[:60]}{'…' if len(text) > 60 else ''}"
    return "pyperclip not available"


def _screenshot(save_path: str | None = None) -> str:
    _require_pyautogui()
    path = _safe_screenshot_path(save_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img  = pyautogui.screenshot()
    img.save(str(path))
    return f"Screenshot saved: {path}"


def _clear_field() -> str:
    _require_pyautogui()
    select_key = "command" if _get_os() == "mac" else "ctrl"
    pyautogui.hotkey(select_key, "a")
    time.sleep(0.1)
    pyautogui.press("delete")
    return "Field cleared"

def _focus_window(title: str) -> str:
    os_name = _get_os()

    if os_name == "windows":
        try:
            script = f'(New-Object -ComObject WScript.Shell).AppActivate("{title}")'
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, timeout=5, **_WIN_HIDE,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (Windows) failed: {e}"

    if os_name == "mac":
        script = (
            f'tell application "System Events" to '
            f'set frontmost of (first process whose name contains "{title}") to true'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (macOS) failed: {e}"

    if os_name == "linux":
        try:
            result = subprocess.run(
                ["wmctrl", "-a", title],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                time.sleep(0.3)
                return f"Focused window: {title}"
        except FileNotFoundError:
            pass
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", title, "windowactivate"],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except FileNotFoundError:
            return "focus_window (Linux) requires wmctrl or xdotool"
        except Exception as e:
            return f"focus_window (Linux) failed: {e}"

    return f"focus_window: unknown OS '{os_name}'"

def _screen_find(description: str) -> tuple[int, int, str] | None:
    api_key = _get_api_key()
    if not api_key:
        print("[ComputerControl] ⚠️ No API key for screen_find")
        return None

    try:
        from google import genai
        from google.genai import types as gtypes

        _require_pyautogui()
        screen_w, screen_h = pyautogui.size()
        img = pyautogui.screenshot()
        img_w, img_h = img.size
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        prompt = (
            f"This is a screenshot of the user's screen ({img_w}×{img_h} physical pixels).\n"
            f"Locate the UI element described as: '{description}'.\n"
            f"Also determine the appropriate mouse interaction type based on visual context:\n"
            f"- If the target is a list item, table row, playlist entry, song/track, file icon, or folder icon meant to be opened/activated: interaction is 'double'\n"
            f"- If the target is a button, menu item, tab, toggle, checkbox, hyperlink, or single control: interaction is 'single'\n"
            f"- If ambiguous, default to 'single'\n\n"
            f"Reply in EXACTLY this format:\n"
            f"COORDINATES: x,y\n"
            f"INTERACTION: single|double\n"
            f"Where x,y are normalized coordinates from 0 to 1000 (0,0 is top-left, 1000,1000 is bottom-right).\n"
            f"If the element is not visible, reply: NOT_FOUND"
        )

        from core import gemini
        response = gemini.call(
            [gtypes.Part.from_bytes(data=image_bytes, mime_type="image/png"), prompt],
            tier=gemini.FAST, timeout_ms=20_000,
        )
        if response is None:
            return None

        text = (response.text or "").strip()
        if "NOT_FOUND" in text.upper():
            return None

        coord_match = re.search(r"COORDINATES:\s*(\d+)\s*,\s*(\d+)", text, re.IGNORECASE)
        if not coord_match:
            coord_match = re.search(r"(\d+)\s*,\s*(\d+)", text)

        if not coord_match:
            return None

        raw_x, raw_y = int(coord_match.group(1)), int(coord_match.group(2))

        interaction = "single"
        inter_match = re.search(r"INTERACTION:\s*(single|double)", text, re.IGNORECASE)
        if inter_match:
            interaction = inter_match.group(1).lower()

        # Coordinate conversion with DPI scaling awareness:
        # If coordinates are normalized in 0..1000 range:
        if raw_x <= 1000 and raw_y <= 1000 and (img_w > 1000 or img_h > 1000):
            target_x = int(raw_x / 1000.0 * screen_w)
            target_y = int(raw_y / 1000.0 * screen_h)
        else:
            # Fallback if coordinates were returned in physical image pixel space:
            target_x = int(raw_x * (screen_w / img_w))
            target_y = int(raw_y * (screen_h / img_h))

        return target_x, target_y, interaction

    except Exception as e:
        print(f"[ComputerControl] ⚠️ screen_find failed: {e}")

    return None


# ── Closed-Loop Action Retry & Error Recovery (Item 3 / Section 22) ───────────

class ActionExecutionError(Exception):
    def __init__(self, failure_type: str, message: str, attempts: int = 1):
        super().__init__(message)
        self.failure_type = failure_type
        self.message = message
        self.attempts = attempts


def _verify_coordinates(x: int | None, y: int | None) -> None:
    """Pre-verification: Ensure target coordinates fall strictly within physical screen bounds."""
    if x is None and y is None:
        return
    _require_pyautogui()
    screen_w, screen_h = pyautogui.size()
    if (x is not None and (x < 0 or x > screen_w)) or (y is not None and (y < 0 or y > screen_h)):
        raise ActionExecutionError(
            "COORDINATES_OUT_OF_BOUNDS",
            f"[FAILURE:COORDINATES_OUT_OF_BOUNDS] Coordinates ({x}, {y}) exceed display bounds ({screen_w}x{screen_h}). Action aborted without blind execution."
        )


def _retry_action(
    action_name: str,
    action_fn,
    pre_verify_fn=None,
    re_verify_fn=None,
    max_retries: int = 2,
    initial_backoff: float = 0.3,
    backoff_multiplier: float = 2.0,
) -> str:
    """
    Closed-loop retry wrapper for computer control actions:
    1. Pre-verifies state before execution.
    2. Catches transient errors/failures, re-verifies state, and retries up to max_retries with backoff.
    3. Produces explicit diagnostic classification upon failure exhaustion.
    """
    backoff = initial_backoff
    last_error: str = ""
    attempts = 0

    for attempt in range(1 + max_retries):
        attempts += 1
        try:
            if attempt == 0:
                if pre_verify_fn:
                    pre_verify_fn()
            else:
                if re_verify_fn:
                    re_verify_fn()

            result = action_fn()
            if isinstance(result, str):
                if result.startswith("Element not found on screen"):
                    raise ActionExecutionError("ELEMENT_NOT_FOUND", result, attempts=attempts)
                if "focus_window" in result and "failed" in result.lower():
                    raise ActionExecutionError("WINDOW_FOCUS", result, attempts=attempts)
            return result

        except ActionExecutionError as e:
            if e.failure_type == "COORDINATES_OUT_OF_BOUNDS":
                print(f"[ComputerControl] 🚫 Bounds check failed: {e.message}")
                return e.message
            last_error = e.message
        except Exception as e:
            err_str = str(e)
            if "FailSafe" in type(e).__name__ or "failsafe" in err_str.lower():
                last_error = f"[FAILURE:INPUT_DRIVER] PyAutoGUI action '{action_name}' failed: FailSafeException (cursor in corner)."
            else:
                last_error = f"[FAILURE:INPUT_DRIVER] Action '{action_name}' execution error: {e}"

        if attempt < max_retries:
            print(f"[ComputerControl] ⚠️ Attempt {attempts} failed for '{action_name}'; retrying in {backoff:.2f}s... ({last_error})")
            time.sleep(backoff)
            backoff *= backoff_multiplier

    # Max retries exhausted: Explicit failure classification
    _screen_w, _screen_h = ("unknown", "unknown")
    try:
        if _PYAUTOGUI:
            _screen_w, _screen_h = pyautogui.size()
    except Exception:
        pass

    if "ELEMENT_NOT_FOUND" in last_error or "not found" in last_error.lower():
        report = (
            f"[FAILURE:ELEMENT_NOT_FOUND] Could not locate target on screen after {max_retries} retries "
            f"(total {attempts} attempts, backoffs 0.30s, 0.60s). "
            f"Display resolution: {_screen_w}x{_screen_h}. "
            f"Suggestions: Verify the target window is in the foreground and the element is not scrolled out of view."
        )
    elif "WINDOW_FOCUS" in last_error or "focus" in last_error.lower():
        report = (
            f"[FAILURE:WINDOW_FOCUS] Window focus failed after {max_retries} retries "
            f"(total {attempts} attempts). Target window could not be activated."
        )
    elif "INPUT_DRIVER" in last_error:
        report = last_error
    else:
        report = f"[FAILURE:ACTION_FAILED] Action '{action_name}' failed after {max_retries} retries (total {attempts} attempts): {last_error}"

    print(f"[ComputerControl] ❌ Exhausted retries: {report}")
    return report


def computer_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Dispatch table for all computer control actions.

    parameters keys (all optional unless noted):
      action        : (required) one of the actions listed below
      text          : text to type or paste
      x, y          : screen coordinates
      button        : 'left' | 'right' (default: left)
      keys          : hotkey string, e.g. 'ctrl+c'
      key           : single key name, e.g. 'enter'
      direction     : 'up' | 'down' | 'left' | 'right'
      amount        : scroll amount (default: 3)
      seconds       : wait duration
      title         : window title fragment for focus_window
      description   : natural-language element description for screen_find/click
      type          : data type for random_data
      field         : memory field name for user_data
      clear_first   : bool, clear field before typing (default: true)
      path          : save path for screenshot (must be inside home dir)

    Actions:
      type          — type text at cursor
      smart_type    — clear field + type (clipboard-backed)
      click         — left click
      double_click  — double left click
      right_click   — right click
      move          — move mouse
      drag          — click-drag between two points
      hotkey        — key combination
      press         — single key
      scroll        — scroll the wheel
      copy          — read clipboard
      paste         — write + paste clipboard
      screenshot    — capture screen (safe path only)
      wait          — sleep N seconds
      clear_field   — select-all + delete
      focus_window  — bring window to foreground
      screen_find   — AI element finder (returns x,y)
      screen_click  — AI element finder + click
      random_data   — generate fake form data
      user_data     — pull real data from memory
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()

    if not action:
        return "No action specified for computer_control."

    if player:
        player.write_log(f"[Computer] {action}")

    print(f"[ComputerControl] ▶ {action}  {params}")

    try:

        if action == "type":
            title = params.get("title")
            return _retry_action(
                "type",
                lambda: _type(params.get("text", "")),
                re_verify_fn=lambda: _focus_window(title) if title else None,
            )

        if action == "smart_type":
            title = params.get("title")
            return _retry_action(
                "smart_type",
                lambda: _smart_type(
                    params.get("text", ""),
                    clear_first=params.get("clear_first", True),
                ),
                re_verify_fn=lambda: _focus_window(title) if title else None,
            )

        if action in ("click", "left_click"):
            interaction = params.get("interaction", "single")
            clicks = 2 if interaction == "double" or params.get("clicks") == 2 else 1
            x = params.get("x")
            y = params.get("y")
            title = params.get("title")
            return _retry_action(
                "click",
                lambda: _click(x, y, "left", clicks=clicks, interaction=interaction),
                pre_verify_fn=lambda: _verify_coordinates(x, y),
                re_verify_fn=lambda: _focus_window(title) if title else None,
            )

        if action == "double_click":
            x = params.get("x")
            y = params.get("y")
            title = params.get("title")
            return _retry_action(
                "double_click",
                lambda: _click(x, y, "left", clicks=2, interaction="double"),
                pre_verify_fn=lambda: _verify_coordinates(x, y),
                re_verify_fn=lambda: _focus_window(title) if title else None,
            )

        if action == "right_click":
            x = params.get("x")
            y = params.get("y")
            title = params.get("title")
            return _retry_action(
                "right_click",
                lambda: _click(x, y, "right", 1),
                pre_verify_fn=lambda: _verify_coordinates(x, y),
                re_verify_fn=lambda: _focus_window(title) if title else None,
            )

        if action == "move":
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
            return _retry_action(
                "move",
                lambda: _move(x, y),
                pre_verify_fn=lambda: _verify_coordinates(x, y),
            )

        if action == "drag":
            x1 = int(params.get("x1", 0))
            y1 = int(params.get("y1", 0))
            x2 = int(params.get("x2", 0))
            y2 = int(params.get("y2", 0))
            def _verify_drag_bounds():
                _verify_coordinates(x1, y1)
                _verify_coordinates(x2, y2)
            return _retry_action(
                "drag",
                lambda: _drag(x1, y1, x2, y2),
                pre_verify_fn=_verify_drag_bounds,
            )

        if action == "hotkey":
            raw  = params.get("keys", "")
            keys = [k.strip() for k in raw.split("+")] if isinstance(raw, str) else raw
            return _retry_action(
                "hotkey",
                lambda: _hotkey(*keys),
            )

        if action == "press":
            return _retry_action(
                "press",
                lambda: _press(params.get("key", "enter")),
            )

        if action == "scroll":
            return _scroll(
                direction=params.get("direction", "down"),
                amount=int(params.get("amount", 3)),
            )

        if action == "copy":
            return _clipboard_get()

        if action == "paste":
            return _clipboard_paste(params.get("text", ""))

        if action == "screenshot":
            return _screenshot(params.get("path"))

        if action == "screen_find":
            result = _screen_find(params.get("description", ""))
            if result:
                x, y, interaction = result
                return f"{x},{y},{interaction}"
            return "NOT_FOUND"

        if action == "screen_click":
            desc = params.get("description", "")
            title = params.get("title")

            def _do_screen_click():
                result = _screen_find(desc)
                if not result:
                    raise ActionExecutionError(
                        "ELEMENT_NOT_FOUND",
                        f"Element not found on screen: '{desc}'"
                    )
                x, y, interaction = result
                # User/caller override if explicitly specified in params
                interaction = params.get("interaction") or interaction
                time.sleep(0.2)
                click_msg = _click(x=x, y=y, interaction=interaction)
                return f"{click_msg} on '{desc}' (interaction: {interaction})"

            def _re_verify_screen():
                if title:
                    _focus_window(title)
                    time.sleep(0.2)

            return _retry_action(
                "screen_click",
                _do_screen_click,
                re_verify_fn=_re_verify_screen,
                max_retries=2,
                initial_backoff=0.3,
            )

        if action == "wait":
            secs = float(params.get("seconds", 1.0))
            secs = min(secs, 30.0)
            time.sleep(secs)
            return f"Waited {secs}s"

        if action == "clear_field":
            return _retry_action(
                "clear_field",
                _clear_field,
            )

        if action == "focus_window":
            title = params.get("title", "")
            return _retry_action(
                "focus_window",
                lambda: _focus_window(title),
            )

        if action == "random_data":
            dt     = params.get("type", "name")
            result = _random_data(dt)
            print(f"[ComputerControl] 🎲 random {dt} → {result}")
            return result

        if action == "user_data":
            field   = params.get("field", "name")
            profile = _user_profile()
            value   = profile.get(field, "")
            if not value:
                value = _random_data(field)
                print(f"[ComputerControl] ⚠️ No '{field}' in memory, using random: {value}")
            return value

        return f"Unknown action: '{action}'"

    except Exception as e:
        print(f"[ComputerControl] ❌ {action}: {e}")
        return f"computer_control '{action}' failed: {e}"


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "computer_control",
    "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"
            },
            "text": {
                "type": "STRING",
                "description": "Text to type or paste"
            },
            "x": {
                "type": "INTEGER",
                "description": "X coordinate"
            },
            "y": {
                "type": "INTEGER",
                "description": "Y coordinate"
            },
            "keys": {
                "type": "STRING",
                "description": "Key combination e.g. 'ctrl+c'"
            },
            "key": {
                "type": "STRING",
                "description": "Single key e.g. 'enter'"
            },
            "direction": {
                "type": "STRING",
                "description": "up | down | left | right"
            },
            "amount": {
                "type": "INTEGER",
                "description": "Scroll amount (default: 3)"
            },
            "seconds": {
                "type": "NUMBER",
                "description": "Seconds to wait"
            },
            "title": {
                "type": "STRING",
                "description": "Window title for focus_window"
            },
            "description": {
                "type": "STRING",
                "description": "Element description for screen_find/screen_click"
            },
            "type": {
                "type": "STRING",
                "description": "Data type for random_data"
            },
            "field": {
                "type": "STRING",
                "description": "Field for user_data: name|email|city"
            },
            "clear_first": {
                "type": "BOOLEAN",
                "description": "Clear field before typing (default: true)"
            },
            "path": {
                "type": "STRING",
                "description": "Save path for screenshot"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": computer_control,
}
