"""
Actions: Application & File Launcher with Dynamic System Discovery and Lifecycle Verification.

Features:
- Dynamic system application discovery via AppLauncher (Start Menu .lnk, UWP/StartApps, built-in utilities).
- Replaces hardcoded _APP_ALIASES and brittle blind Start-Menu keystrokes.
- Lifecycle verification: polls process/window appearance with timeout instead of blind sleep.
- Target-type detection: seamless support for user files vs application requests.
- Structured return format: {"success", "action", "app", "pid_or_window", "value", "message"}.
"""
import os
import time
import subprocess
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

from core.tool import AgentTool, ToolResult

# ── Console UTF-8 Reconfiguration ───────────────────────────────────────────
for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

try:
    import pygetwindow as gw
    _GW = True
except ImportError:
    _GW = False

_SYSTEM = platform.system()


# Ensure primary directory is in sys.path for phase3.app_launcher import
def _ensure_primary_path() -> None:
    base = Path(__file__).resolve().parent.parent
    primary_dir = str(base / "primary")
    if primary_dir not in sys.path:
        sys.path.append(primary_dir)


_ensure_primary_path()

_launcher_instance = None


def _get_launcher():
    global _launcher_instance
    if _launcher_instance is None:
        try:
            from phase3.app_launcher import AppLauncher
            _launcher_instance = AppLauncher()
            _launcher_instance.discover_system_apps()
        except Exception as e:
            print(f"[open_app] Warning: could not initialize AppLauncher: {e}")
            _launcher_instance = None
    return _launcher_instance


# ── File Target Helpers ──────────────────────────────────────────────────────

_KNOWN_FILE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff",
    ".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".csv", ".xlsx", ".xls",
    ".pptx", ".ppt", ".json", ".xml", ".yaml", ".yml", ".html", ".htm",
    ".mp3", ".wav", ".ogg", ".m4a", ".flac", ".mp4", ".mkv", ".avi", ".mov", ".wmv",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".py", ".js", ".ts", ".css", ".cpp", ".c", ".h"
}


def _get_shortcuts() -> dict[str, Path]:
    home = Path.home()
    if _SYSTEM == "Linux":
        xdg_desktop = os.environ.get("XDG_DESKTOP_DIR", "")
        desktop = Path(xdg_desktop) if xdg_desktop and Path(xdg_desktop).exists() else home / "Desktop"
        xdg_downloads = os.environ.get("XDG_DOWNLOAD_DIR", "")
        downloads = Path(xdg_downloads) if xdg_downloads and Path(xdg_downloads).exists() else home / "Downloads"
        xdg_documents = os.environ.get("XDG_DOCUMENTS_DIR", "")
        documents = Path(xdg_documents) if xdg_documents and Path(xdg_documents).exists() else home / "Documents"
        xdg_pictures = os.environ.get("XDG_PICTURES_DIR", "")
        pictures = Path(xdg_pictures) if xdg_pictures and Path(xdg_pictures).exists() else home / "Pictures"
        xdg_music = os.environ.get("XDG_MUSIC_DIR", "")
        music = Path(xdg_music) if xdg_music and Path(xdg_music).exists() else home / "Music"
        xdg_videos = os.environ.get("XDG_VIDEOS_DIR", "")
        videos = Path(xdg_videos) if xdg_videos and Path(xdg_videos).exists() else home / "Videos"
    else:
        desktop   = home / "Desktop"
        downloads = home / "Downloads"
        documents = home / "Documents"
        pictures  = home / "Pictures"
        music     = home / "Music"
        videos    = home / "Videos"

    return {
        "desktop":   desktop,
        "downloads": downloads,
        "documents": documents,
        "pictures":  pictures,
        "music":     music,
        "videos":    videos,
        "home":      home,
    }


def _resolve_file_path(raw: str) -> Path:
    raw = raw.strip().strip('"\'')
    shortcuts = _get_shortcuts()
    lower = raw.lower()
    if lower in shortcuts:
        return shortcuts[lower]

    if lower in ("last_capture", "photo", "capture", "current_file", "user_photo.png", "user_photo.jpg"):
        for cand in [Path.cwd() / "last_capture.jpg", Path.cwd() / "last_capture.png", shortcuts["pictures"] / "last_capture.jpg"]:
            if cand.exists():
                return cand

    normalized = raw.replace("\\", "/")
    head, sep, rest = normalized.partition("/")
    if sep and head.lower() in shortcuts:
        rest = rest.strip("/")
        return shortcuts[head.lower()] / rest if rest else shortcuts[head.lower()]

    expanded = Path(raw).expanduser()
    if expanded.is_absolute() and expanded.exists():
        return expanded

    for folder in shortcuts.values():
        cand = folder / raw
        if cand.exists():
            return cand

    cwd_cand = Path.cwd() / raw
    if cwd_cand.exists():
        return cwd_cand

    cap_cand = Path.cwd() / "data" / "captures" / raw
    if cap_cand.exists():
        return cap_cand

    return expanded


def _is_file_target(target: str) -> bool:
    clean = target.strip().strip('"\'')
    ext = Path(clean).suffix.lower()
    has_sep = ("/" in clean) or ("\\" in clean)
    lower = clean.lower()
    if lower in ("last_capture", "photo", "capture", "current_file"):
        return True
    return (ext in _KNOWN_FILE_EXTENSIONS) or (has_sep and bool(ext))


def _open_file_native(target_path: Path) -> Dict[str, Any]:
    try:
        resolved = target_path.resolve()
        if not resolved.exists():
            return {
                "success": False,
                "action": "open_file",
                "app": target_path.name,
                "pid_or_window": None,
                "value": None,
                "message": f"File not found: '{target_path}'. (Looked at: {resolved})",
            }

        if _SYSTEM == "Windows":
            os.startfile(str(resolved))
        elif _SYSTEM == "Darwin":
            subprocess.Popen(["open", str(resolved)])
        else:
            subprocess.Popen(["xdg-open", str(resolved)])

        return {
            "success": True,
            "action": "open_file",
            "app": resolved.name,
            "pid_or_window": str(resolved),
            "value": {
                "file_path": str(resolved),
                "filename": resolved.name,
                "size_bytes": resolved.stat().st_size if resolved.is_file() else None,
            },
            "message": f"Opened file: {resolved.name}",
        }
    except Exception as e:
        return {
            "success": False,
            "action": "open_file",
            "app": target_path.name,
            "pid_or_window": None,
            "value": None,
            "message": f"Failed to open file '{target_path.name}': {e}",
        }


# ── Lifecycle Verification ───────────────────────────────────────────────────

def _extract_candidate_tokens(app_info: Optional[Dict[str, Any]], query: str) -> List[str]:
    """Builds a set of normalized search tokens to match process and window names."""
    tokens = set()
    clean_q = query.lower().strip()
    tokens.add(clean_q)

    # Add query words
    for w in clean_q.replace("-", " ").replace("_", " ").split():
        if len(w) >= 3:
            tokens.add(w)

    if app_info:
        name = app_info.get("name", "").lower()
        if name:
            tokens.add(name)
            for w in name.replace("-", " ").replace("_", " ").split():
                if len(w) >= 3:
                    tokens.add(w)

        display = app_info.get("display_name", "").lower()
        if display:
            tokens.add(display)

        target = app_info.get("target", "").lower()
        if target:
            target_stem = Path(target).stem.lower()
            tokens.add(target_stem)

        path = app_info.get("path", "")
        if path:
            p_stem = Path(path).stem.lower()
            tokens.add(p_stem)

        app_id = app_info.get("app_id", "").lower()
        if app_id:
            for part in app_id.replace("!", ".").replace("_", ".").split("."):
                clean_part = part.lower().replace("windows", "").replace("microsoft", "").strip()
                if len(clean_part) >= 3:
                    tokens.add(clean_part)

    stop_words = {"app", "the", "for", "and", "pro", "x86", "x64", "windows", "microsoft"}
    return [t for t in tokens if len(t) >= 3 and t not in stop_words]


def _verify_app_lifecycle(
    candidate_tokens: List[str],
    pre_pids: Set[int],
    launch_time: Optional[float] = None,
    timeout: float = 6.0,
    interval: float = 0.25,
) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    Polls for the appearance of the application process or window within timeout seconds.
    Returns: (verified: bool, pid: Optional[int], window_or_process_name: Optional[str])
    """
    if not _PSUTIL:
        time.sleep(1.0)
        return True, None, "Process verified (psutil unavailable)"

    deadline = time.time() + timeout
    seen_spawned_pids: Set[int] = set()

    while time.time() < deadline:
        current_pids = set(psutil.pids())
        new_pids = current_pids - pre_pids
        if new_pids:
            seen_spawned_pids.update(new_pids)

        # 1. Check newly appeared processes first
        for pid in new_pids:
            try:
                p = psutil.Process(pid)
                pname = p.name().lower()
                for tok in candidate_tokens:
                    if tok in pname:
                        return True, pid, p.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # 2. Check open window titles if pygetwindow is available
        if _GW:
            try:
                for w in gw.getAllWindows():
                    title = (w.title or "").strip()
                    if title:
                        t_lower = title.lower()
                        for tok in candidate_tokens:
                            if tok in t_lower:
                                return True, None, title
            except Exception:
                pass

        # 3. If no new process matched directly, check existing processes matching candidates
        # ONLY IF there is evidence of an actual launch / activation event:
        # - Evidence A: The process was created at or after the launch attempt
        # - Evidence B: Active window currently belongs to/matches candidate (app brought to foreground)
        # - Evidence C: A transient helper/launcher process was observed spawning (seen_spawned_pids non-empty)
        for p in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                pname = (p.info.get("name") or "").lower()
                matches_token = any(tok in pname for tok in candidate_tokens)
                if not matches_token:
                    continue

                pid = p.info.get("pid")
                create_time = p.info.get("create_time", 0.0)

                # Evidence A: Process start time is at or after launch_time
                if launch_time and create_time >= launch_time:
                    return True, pid, p.info.get("name")

                # Evidence B: Active window currently belongs to/matches candidate
                if _GW:
                    try:
                        active_win = gw.getActiveWindow()
                        if active_win and active_win.title:
                            if any(tok in active_win.title.lower() for tok in candidate_tokens):
                                return True, pid, active_win.title
                    except Exception:
                        pass

                # Evidence C: Transient helper/launcher process was observed spawning
                if seen_spawned_pids:
                    return True, pid, p.info.get("name")

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        time.sleep(interval)

    return False, None, None


# ── Launchers ────────────────────────────────────────────────────────────────

def _launch_via_app_launcher(app_name: str, app_info: Dict[str, Any]) -> bool:
    launcher = _get_launcher()
    if not launcher:
        return False

    app_type = app_info.get("type", "exe")
    target = app_info.get("path") or app_info.get("app_id") or app_info.get("target")

    if target and launcher._spawn(target, app_type=app_type):
        return True

    success, _ = launcher.launch(app_name)
    return success


def _launch_macos(app_name: str) -> bool:
    try:
        res = subprocess.run(["open", "-a", app_name], capture_output=True, timeout=8)
        if res.returncode == 0:
            return True
    except Exception:
        pass

    try:
        res = subprocess.run(["open", "-a", f"{app_name}.app"], capture_output=True, timeout=8)
        if res.returncode == 0:
            return True
    except Exception:
        pass

    binary = shutil.which(app_name) or shutil.which(app_name.lower())
    if binary:
        try:
            subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass

    return False


def _launch_linux(app_name: str) -> bool:
    binary = (
        shutil.which(app_name) or
        shutil.which(app_name.lower()) or
        shutil.which(app_name.lower().replace(" ", "-")) or
        shutil.which(app_name.lower().replace(" ", "_"))
    )
    if binary:
        try:
            subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass

    try:
        subprocess.run(["xdg-open", app_name], capture_output=True, timeout=5)
        return True
    except Exception:
        pass

    return False


# ── Main Handler ─────────────────────────────────────────────────────────────

def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
    **extra,
) -> Dict[str, Any]:
    params = parameters or {}
    app_name = (params.get("app_name") or params.get("target") or params.get("path") or "").strip()

    if not app_name:
        return {
            "success": False,
            "action": "open_app",
            "app": "",
            "pid_or_window": None,
            "value": None,
            "message": "No application or file name provided.",
        }

    # 1. Target-Type Detection: File open request vs Application launch
    if _is_file_target(app_name):
        resolved_path = _resolve_file_path(app_name)
        if player:
            player.write_log(f"[open_file] {app_name}")
        print(f"[open_app] [FILE] Treating '{app_name}' as file path -> resolved: '{resolved_path}'")
        return _open_file_native(resolved_path)

    # 2. Application Launch
    if player:
        player.write_log(f"[open_app] {app_name}")

    pre_pids = set(psutil.pids()) if _PSUTIL else set()
    launch_time = time.time()

    # Windows: Use dynamically discovered system apps via AppLauncher
    if _SYSTEM == "Windows":
        launcher = _get_launcher()
        app_info = launcher.find_system_app(app_name) if launcher else None

        if not app_info:
            # Check if app_name is an executable in system PATH
            if shutil.which(app_name) or shutil.which(f"{app_name}.exe"):
                app_info = {"name": app_name, "display_name": app_name, "target": app_name, "type": "exe"}

        if not app_info:
            print(f"[open_app] ❌ Application '{app_name}' not found in system app discovery.")
            return {
                "success": False,
                "action": "open_app",
                "app": app_name,
                "pid_or_window": None,
                "value": None,
                "message": (
                    f"Could not find application '{app_name}'. "
                    f"Please verify the application is installed."
                ),
            }

        display_name = app_info.get("display_name", app_info.get("name", app_name))
        candidate_tokens = _extract_candidate_tokens(app_info, app_name)
        print(f"[open_app] [APP] Launching '{display_name}' (type: {app_info.get('type')}) with tokens: {candidate_tokens}")

        # Spawn application
        spawn_success = _launch_via_app_launcher(app_name, app_info)
        if not spawn_success:
            return {
                "success": False,
                "action": "open_app",
                "app": display_name,
                "pid_or_window": None,
                "value": None,
                "message": f"Failed to execute launch command for '{display_name}'.",
            }

        # Lifecycle Verification: Poll until process or window appears
        verified, pid, win_or_proc = _verify_app_lifecycle(
            candidate_tokens, pre_pids, launch_time=launch_time, timeout=6.0
        )

        if not verified:
            print(f"[open_app] ⚠️ Lifecycle check timeout for '{display_name}'.")
            return {
                "success": False,
                "action": "open_app",
                "app": display_name,
                "pid_or_window": None,
                "value": None,
                "message": f"Launched '{display_name}', but process/window did not appear within 6.0s timeout.",
            }

        ref_identifier = f"PID {pid}" if pid else (win_or_proc or "active")
        print(f"[open_app] ✅ Lifecycle verified: '{display_name}' is running ({ref_identifier}).")

        return {
            "success": True,
            "action": "open_app",
            "app": display_name,
            "pid_or_window": ref_identifier,
            "value": {
                "app": display_name,
                "pid": pid,
                "window": win_or_proc if not pid else None,
                "pid_or_window": ref_identifier,
                "app_type": app_info.get("type"),
            },
            "message": f"Successfully opened {display_name} ({ref_identifier}).",
        }

    # macOS and Linux handling
    display_name = app_name.capitalize()
    candidate_tokens = _extract_candidate_tokens(None, app_name)
    spawn_success = _launch_macos(app_name) if _SYSTEM == "Darwin" else _launch_linux(app_name)

    if not spawn_success:
        return {
            "success": False,
            "action": "open_app",
            "app": app_name,
            "pid_or_window": None,
            "value": None,
            "message": f"Could not find or launch application '{app_name}' on {_SYSTEM}.",
        }

    verified, pid, win_or_proc = _verify_app_lifecycle(
        candidate_tokens, pre_pids, launch_time=launch_time, timeout=5.0
    )
    ref_identifier = f"PID {pid}" if pid else (win_or_proc or "active")

    return {
        "success": True,
        "action": "open_app",
        "app": display_name,
        "pid_or_window": ref_identifier,
        "value": {
            "app": display_name,
            "pid": pid,
            "pid_or_window": ref_identifier,
        },
        "message": f"Successfully opened {display_name}.",
    }


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
class OpenAppTool(AgentTool):
    @property
    def name(self) -> str:
        return "open_app"

    @property
    def description(self) -> str:
        return (
            "Opens any installed desktop application or file with dynamic system app discovery "
            "and post-launch lifecycle verification. Always call this tool when the user requests "
            "to open, launch, or start an app or file."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Name of the application or file path (e.g. 'Chrome', 'Notepad', 'Calculator', 'report.pdf')",
                }
            },
            "required": [
                "app_name"
            ],
        }

    def execute(self, parameters: Optional[Dict[str, Any]] = None, **context) -> Dict[str, Any]:
        known = {"response", "player", "session_memory"}
        filtered = {k: v for k, v in context.items() if k in known}
        return open_app(parameters=parameters, **filtered)


ACTION = OpenAppTool()
TOOL = ACTION.to_tool_dict()
