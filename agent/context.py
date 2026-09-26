"""
agent/context.py
Section 20: Live Agent Context Snapshot

Provides a thread-safe, lightweight, in-memory snapshot of the agent's current
operating environment without continuous polling or background screenshot capture.

Core Attributes:
- current_active_application: foreground app process name (lazy query, graceful fallback)
- current_window: foreground window title (lazy query, graceful fallback)
- current_screen_screenshot: on-demand capture only (never background polled)
- open_applications: top-level window titles (lazy query, short TTL cache)
- current_directory: active workspace directory and active file
- recent_action: most recent tool execution parameters (pushed via _execute_tool)
- previous_action_result: most recent tool return value/error (pushed via _execute_tool)
- agent_state: live state from UI (WORKING, LISTENING, THINKING, SPEAKING)
"""

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

import os
import time
import platform
import ctypes
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False

from core.logger import scrub_text, scrub_secrets


# ── Native Windows OS Inspection Helpers ─────────────────────────────────────

# Thread-local storage to cache desktop attachment and prevent redundant Win32 swaps
_thread_desktop_state = threading.local()


def _ensure_input_desktop() -> None:
    """
    Ensure the calling thread is attached to the active input desktop if currently isolated.
    Guarantees strict Win32 handle lifecycle:
    - Thread-local caching ensures attach-and-swap executes at most once per thread lifetime.
    - If switching desktops, captures old desktop handle via GetThreadDesktop() before SetThreadDesktop().
    - Closes the old desktop handle via CloseDesktop() after SetThreadDesktop() succeeds.
    - Closes newly opened handle if SetThreadDesktop() fails.
    - Never closes the active desktop handle while in use.
    """
    if platform.system() != "Windows":
        return

    # Thread-local cache check: avoid redundant Win32 calls on the same thread
    if getattr(_thread_desktop_state, "attached_to_input_desktop", False):
        return

    try:
        user32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if hwnd:
            # Already on an interactive desktop with a valid foreground window
            _thread_desktop_state.attached_to_input_desktop = True
            return

        # Attempt to open active input desktop or default desktop
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF) or user32.OpenDesktopW("default", 0, False, 0x01FF)
        if not hdesk:
            return

        # Capture thread's CURRENT desktop handle before switching
        old_desk = user32.GetThreadDesktop(k32.GetCurrentThreadId())

        if user32.SetThreadDesktop(hdesk):
            _thread_desktop_state.attached_to_input_desktop = True
            # Close the OLD desktop handle now that thread has switched to the new desktop
            if old_desk and old_desk != hdesk:
                try:
                    user32.CloseDesktop(old_desk)
                except Exception:
                    pass
        else:
            # If switching failed, close newly opened handle immediately to avoid leak
            try:
                user32.CloseDesktop(hdesk)
            except Exception:
                pass
    except Exception:
        pass


def _get_active_window_title() -> str:
    """Retrieve the title of the current foreground window. Returns '' on failure."""
    if platform.system() != "Windows":
        return ""
    try:
        _ensure_input_desktop()
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value.strip()
    except Exception:
        return ""


def _get_active_app_name() -> str | None:
    """Retrieve the process name of the current foreground application. Returns None on failure."""
    if platform.system() != "Windows" or not _PSUTIL_AVAILABLE:
        return None
    try:
        _ensure_input_desktop()
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        proc = psutil.Process(pid.value)
        return proc.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
        return None


def _get_open_window_titles() -> list[str]:
    """Enumerate titles of top-level visible windows. Returns [] on failure."""
    if platform.system() != "Windows":
        return []
    titles: list[str] = []
    try:
        _ensure_input_desktop()
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def enum_windows_callback(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()
                    if title and title not in ("Program Manager", "Default IME", "MSCTFIME UI"):
                        titles.append(title)
            return True

        user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)
    except Exception:
        return []
    return titles


# ── AgentContext Singleton Implementation ────────────────────────────────────

class AgentContext:
    """
    Live queryable snapshot of agent state and environmental context.
    Thread-safe and strictly on-demand (no background polling threads).
    """

    _instance: Optional["AgentContext"] = None
    _singleton_lock = threading.Lock()

    def __init__(self):
        self._lock = threading.Lock()
        self._ui = None
        self._active_file: Optional[str] = None
        self._recent_action: Optional[Dict[str, Any]] = None
        self._previous_action_result: Optional[Dict[str, Any]] = None

        # Screenshot on-demand cache
        self._cached_screenshot_bytes: Optional[bytes] = None
        self._cached_screenshot_time: float = 0.0

        # Open applications TTL cache
        self._open_apps_cache: Optional[List[str]] = None
        self._open_apps_cache_time: float = 0.0
        self._OPEN_APPS_TTL: float = 3.0  # seconds

    @classmethod
    def get_instance(cls) -> "AgentContext":
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for clean test isolation)."""
        with cls._singleton_lock:
            cls._instance = None

    def set_ui(self, ui: Any) -> None:
        """Register the AgentUI instance to observe state transitions and active files."""
        with self._lock:
            self._ui = ui

    def set_active_file(self, file_path: str | None) -> None:
        """Update the active working file path."""
        with self._lock:
            self._active_file = str(file_path) if file_path else None

    # ── Tool Execution State (Push Integration from _execute_tool) ────────────

    def update_tool_state(
        self,
        tool: str,
        action: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        result: Any = None,
        error: Optional[str] = None,
        verified: Optional[bool] = None,
        verification_source: Optional[str] = None,
    ) -> None:
        """
        Record the most recent tool execution and its outcome.
        Called atomically from main.py::_execute_tool alongside ActionLogger.log_event.
        """
        now = time.time()
        with self._lock:
            self._recent_action = {
                "tool": tool,
                "action": action,
                "parameters": dict(parameters) if parameters else {},
                "timestamp": now,
            }
            self._previous_action_result = {
                "tool": tool,
                "action": action,
                "result": result,
                "error": error,
                "verified": verified,
                "verification_source": verification_source,
                "timestamp": now,
            }

    # ── Lazy On-Demand Environmental Properties ───────────────────────────────

    @property
    def current_active_application(self) -> Optional[str]:
        """Lazy query: Returns the process name of the current foreground application."""
        return _get_active_app_name()

    @property
    def current_window(self) -> str:
        """Lazy query: Returns the title of the current foreground window."""
        return _get_active_window_title()

    @property
    def open_applications(self) -> List[str]:
        """Lazy query: Returns visible top-level window titles (cached for 3.0s)."""
        now = time.monotonic()
        with self._lock:
            if (
                self._open_apps_cache is not None
                and (now - self._open_apps_cache_time) < self._OPEN_APPS_TTL
            ):
                return list(self._open_apps_cache)

        # Query OS outside lock
        apps = _get_open_window_titles()

        with self._lock:
            self._open_apps_cache = apps
            self._open_apps_cache_time = now
            return list(apps)

    @property
    def current_directory(self) -> Path:
        """Current working directory."""
        return Path.cwd()

    @property
    def active_file(self) -> Optional[str]:
        """Active file path from UI or context."""
        with self._lock:
            if self._active_file:
                return self._active_file
            if self._ui and hasattr(self._ui, "current_file"):
                return getattr(self._ui, "current_file") or None
        return None

    @property
    def agent_state(self) -> str:
        """Current high-level state of the agent (e.g. WORKING, LISTENING)."""
        with self._lock:
            if self._ui and hasattr(self._ui, "state"):
                return str(getattr(self._ui, "state") or "READY")
        return "READY"

    @property
    def recent_action(self) -> Optional[Dict[str, Any]]:
        """Most recent action dispatched."""
        with self._lock:
            return dict(self._recent_action) if self._recent_action else None

    @property
    def previous_action_result(self) -> Optional[Dict[str, Any]]:
        """Result from the most recent action."""
        with self._lock:
            return dict(self._previous_action_result) if self._previous_action_result else None

    # ── On-Demand Screenshot Capture ──────────────────────────────────────────

    def get_screenshot(self, max_age_seconds: float = 0.0) -> Optional[bytes]:
        """
        Capture or retrieve a screenshot strictly on demand.
        NEVER runs in a background thread or polling loop.
        If max_age_seconds > 0 and a capture exists within that window, reuses it.
        """
        now = time.monotonic()
        with self._lock:
            if (
                max_age_seconds > 0.0
                and self._cached_screenshot_bytes is not None
                and (now - self._cached_screenshot_time) <= max_age_seconds
            ):
                return self._cached_screenshot_bytes

        # Capture freshly on demand
        try:
            import io
            import pyautogui
            img = pyautogui.screenshot()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            img_bytes = buf.getvalue()
            with self._lock:
                self._cached_screenshot_bytes = img_bytes
                self._cached_screenshot_time = now
            return img_bytes
        except Exception as e:
            print(f"[AgentContext] ⚠️ Screenshot capture failed: {e}")
            return None

    # ── Snapshot & Redaction Formatting ───────────────────────────────────────

    def get_snapshot(self, scrub: bool = True) -> Dict[str, Any]:
        """
        Return an atomic dictionary snapshot of current context.
        When scrub=True, passes all string fields through scrub_secrets/scrub_text
        so credentials cannot leak into LLM system prompts.
        """
        with self._lock:
            recent_act = dict(self._recent_action) if self._recent_action else None
            prev_res = dict(self._previous_action_result) if self._previous_action_result else None

        raw = {
            "active_application": self.current_active_application,
            "active_window": self.current_window,
            "current_directory": str(self.current_directory),
            "active_file": self.active_file,
            "agent_state": self.agent_state,
            "recent_action": recent_act,
            "previous_action_result": prev_res,
        }

        if not scrub:
            return raw

        return scrub_secrets(raw)

    def get_snapshot_text(self, scrub: bool = True) -> str:
        """
        Format the live context as a concise string for LLM system prompts or diagnostics.
        Guarantees sensitive tokens (API keys, passwords, bearer tokens) are scrubbed.
        """
        snap = self.get_snapshot(scrub=scrub)
        parts = []

        if snap.get("active_application"):
            parts.append(f"App: {snap['active_application']}")
        if snap.get("active_window"):
            parts.append(f"Window: '{snap['active_window']}'")
        if snap.get("active_file"):
            parts.append(f"File: {snap['active_file']}")
        if snap.get("agent_state"):
            parts.append(f"State: {snap['agent_state']}")
        if snap.get("recent_action"):
            act = snap["recent_action"]
            parts.append(f"Last Action: {act.get('tool')}.{act.get('action') or 'default'}")
        if snap.get("previous_action_result"):
            res = snap["previous_action_result"]
            res_str = str(res.get("result", "") or res.get("error", "") or "")
            if res_str:
                parts.append(f"Result: {res_str[:60]}")

        text = " | ".join(parts) if parts else "Context: Ready"
        return scrub_text(text) if scrub else text
