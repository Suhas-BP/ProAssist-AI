#desktop.py
import os
import sys
import json
import shutil
import subprocess
import tempfile
import platform
from pathlib import Path
from datetime import datetime

try:
    import pyautogui
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_api_key() -> str:
    path = _get_base_dir() / "config" / "api_keys.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]
    
def _get_desktop() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DESKTOP_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Desktop"

import ast
import re

_BasePlatformPath = type(Path())


class SafePath(_BasePlatformPath):
    """Restricted Path subclass for desktop automation sandbox.
    Disallows file deletion, modification, and destructive operations."""

    def unlink(self, *args, **kwargs):
        raise PermissionError("Path.unlink() is blocked in sandbox for safety.")

    def rmdir(self, *args, **kwargs):
        raise PermissionError("Path.rmdir() is blocked in sandbox for safety.")

    def write_text(self, *args, **kwargs):
        raise PermissionError("Path.write_text() is blocked in sandbox for safety.")

    def write_bytes(self, *args, **kwargs):
        raise PermissionError("Path.write_bytes() is blocked in sandbox for safety.")

    def rename(self, *args, **kwargs):
        raise PermissionError("Path.rename() is blocked in sandbox for safety.")

    def replace(self, *args, **kwargs):
        raise PermissionError("Path.replace() is blocked in sandbox for safety.")

    def mkdir(self, *args, **kwargs):
        raise PermissionError("Path.mkdir() is blocked in sandbox for safety.")

    def touch(self, *args, **kwargs):
        raise PermissionError("Path.touch() is blocked in sandbox for safety.")

    def chmod(self, *args, **kwargs):
        raise PermissionError("Path.chmod() is blocked in sandbox for safety.")

    def lchmod(self, *args, **kwargs):
        raise PermissionError("Path.lchmod() is blocked in sandbox for safety.")

    def symlink_to(self, *args, **kwargs):
        raise PermissionError("Path.symlink_to() is blocked in sandbox for safety.")

    def hardlink_to(self, *args, **kwargs):
        raise PermissionError("Path.hardlink_to() is blocked in sandbox for safety.")


def _scan_code_safety(code: str) -> list[str]:
    """Scan code for destructive or dangerous operations before exec()."""
    threats = []

    # 1. AST check for calls / attribute access
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in (
                    "unlink", "rmdir", "rmtree", "remove", "system", "popen",
                    "spawn", "write_text", "write_bytes", "rename", "replace",
                    "chmod", "truncate", "kill", "terminate"
                ):
                    threats.append(f"method call: .{node.attr}")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                threats.append("import statement")
            elif isinstance(node, ast.Name):
                if node.id in ("eval", "exec", "__import__", "open", "compile", "globals", "locals"):
                    threats.append(f"dangerous builtin: {node.id}")
    except Exception:
        threats.append("unparseable syntax")

    # 2. Regex fallback scan
    patterns = [
        (r"\b(unlink|rmdir|rmtree|remove)\b", "file deletion pattern"),
        (r"\b(write_text|write_bytes|rename|replace)\b", "file modification pattern"),
        (r"\b(system|popen|subprocess|spawn|exec|eval)\b", "system execution pattern"),
        (r"\b(shutil\.(move|rmtree))\b", "shutil destructive pattern"),
    ]
    for pattern, desc in patterns:
        if re.search(pattern, code, re.IGNORECASE) and desc not in threats:
            threats.append(desc)

    return list(dict.fromkeys(threats))


def _build_sandbox() -> dict:
    import time

    safe_builtins = {
        "print": print,
        "len": len, "str": str, "int": int, "float": float,
        "bool": bool, "list": list, "dict": dict, "tuple": tuple,
        "range": range, "enumerate": enumerate, "sorted": sorted,
        "isinstance": isinstance, "hasattr": hasattr, "getattr": getattr,
        "max": max, "min": min, "sum": sum, "abs": abs,
        "zip": zip, "map": map, "filter": filter,
    }

    sandbox = {
        "__builtins__": safe_builtins,
        "Path": SafePath,
        "time": time,
        "shutil": type("shutil", (), {
            "copy2":      staticmethod(shutil.copy2),
            "copytree":   staticmethod(shutil.copytree),
            "disk_usage": staticmethod(shutil.disk_usage),
        })(),
        "os_path": os.path,  
    }

    if _PYAUTOGUI:
        sandbox["pyautogui"] = pyautogui

    if _OS == "Windows":
        try:
            import ctypes
            import winreg
            sandbox["ctypes"] = ctypes
            sandbox["winreg"] = type("winreg", (), {
                # Sadece okuma
                "OpenKey":      winreg.OpenKey,
                "QueryValueEx": winreg.QueryValueEx,
                "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
            })()
        except ImportError:
            pass

    return sandbox


def _run_sandbox(code: str, player=None) -> str:
    sandbox      = _build_sandbox()
    output_lines = []
    sandbox["__builtins__"]["print"] = lambda *a: output_lines.append(" ".join(str(x) for x in a))

    try:
        exec(compile(code, "<jarvis_desktop>", "exec"), sandbox)
        return "\n".join(output_lines) if output_lines else "Done."
    except Exception as e:
        print(f"[Desktop] Exec error: {e}\nCode:\n{code[:300]}")
        return f"Execution error: {e}"


def _execute_generated_code(code: str, player=None) -> str:
    if not code or code.strip() == "UNSAFE":
        return "This action cannot be performed safely."

    # Kod temizleme
    if code.startswith("```"):
        lines = code.split("\n")
        code  = "\n".join(lines[1:-1]).strip()

    # Pre-execution static safety check
    threats = _scan_code_safety(code)
    if threats:
        from core import confirm
        threat_summary = ", ".join(threats)
        if confirm.pending_title():
            return "There is already a confirmation waiting on screen. Ask the user to answer that one first."
        return confirm.request(
            key="desktop_code",
            title="Execute Potentially Destructive Script",
            detail=f"Detected: {threat_summary}\n\nCode:\n{code[:300]}",
            run=lambda: _run_sandbox(code, player=player),
        )

    return _run_sandbox(code, player=player)


def _ask_gemini_for_desktop_action(task: str) -> str:

    from google import genai as _genai

    desktop = str(_get_desktop())

    os_specific = ""
    if _OS == "Windows":
        os_specific = "- ctypes (Windows API calls, read-only)\n- winreg (registry READ only)"
    elif _OS == "Darwin":
        os_specific = "- subprocess is NOT available; use pyautogui or Path only"
    else:
        os_specific = "- subprocess is NOT available; use pyautogui or Path only"

    prompt = f"""You are a desktop automation assistant.
Current OS: {_OS}
Desktop path: {desktop}

Generate safe Python code to accomplish the task below.
Allowed modules ONLY:
- pyautogui (mouse, keyboard — if needed)
- pathlib.Path (file/folder inspection only, no deletion)
- shutil.copy2, shutil.copytree, shutil.disk_usage (NO move, NO rmtree)
- os_path (os.path equivalent, read-only)
- time.sleep
{os_specific}

Hard rules:
- NO file deletion (no unlink, no rmtree, no remove)
- NO subprocess calls
- NO exec() or eval() inside the code
- NO import statements (modules are pre-injected)
- NO file write operations except explicitly requested
- If task cannot be done safely with these tools, output exactly: UNSAFE

Output ONLY the Python code. No explanation, no markdown, no backticks.

Task: {task}"""

    try:
        from core import gemini
        response = gemini.call(prompt, tier=gemini.SMART, timeout_ms=30_000)
        if response is None:
            return "ERROR: every Gemini model on the ladder failed"
        code = (response.text or "").strip()
        if code.startswith("```"):
            lines = code.split("\n")
            code  = "\n".join(lines[1:-1]).strip()
        return code
    except Exception as e:
        return f"ERROR: {e}"

def set_wallpaper(image_path: str) -> str:
    path = Path(image_path).expanduser().resolve()
    if not path.exists():
        return f"Image not found: {image_path}"
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
        return f"Unsupported format: {path.suffix}. Use jpg, png, bmp or webp."

    try:
        if _OS == "Windows":
            import ctypes
            if path.suffix.lower() in {".webp", ".png"}:
                try:
                    from PIL import Image
                    bmp_path = Path(tempfile.mktemp(suffix=".bmp"))
                    Image.open(path).convert("RGB").save(bmp_path, "BMP")
                    path = bmp_path
                except ImportError:
                    pass 
            ctypes.windll.user32.SystemParametersInfoW(20, 0, str(path), 3)
            return f"Wallpaper set: {path.name}"

        elif _OS == "Darwin":
            script = (
                f'tell application "System Events" to tell every desktop to '
                f'set picture to POSIX file "{path}"'
            )
            subprocess.run(["osascript", "-e", script], capture_output=True)
            return f"Wallpaper set: {path.name}"

        else:
            desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
            uri = f"file://{path}"

            if "gnome" in desktop_env or "unity" in desktop_env:
                subprocess.run([
                    "gsettings", "set", "org.gnome.desktop.background",
                    "picture-uri", uri
                ], capture_output=True)
                subprocess.run([
                    "gsettings", "set", "org.gnome.desktop.background",
                    "picture-uri-dark", uri
                ], capture_output=True)

            elif "kde" in desktop_env:
                # KDE Plasma
                script = f"""
var allDesktops = desktops();
for (var i = 0; i < allDesktops.length; i++) {{
    d = allDesktops[i];
    d.wallpaperPlugin = "org.kde.image";
    d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    d.writeConfig("Image", "file://{path}");
}}
"""
                subprocess.run(
                    ["qdbus", "org.kde.plasmashell", "/PlasmaShell",
                     "org.kde.PlasmaShell.evaluateScript", script],
                    capture_output=True
                )

            elif "xfce" in desktop_env:
                subprocess.run([
                    "xfconf-query", "-c", "xfce4-desktop",
                    "-p", "/backdrop/screen0/monitor0/workspace0/last-image",
                    "-s", str(path)
                ], capture_output=True)

            else:
                result = subprocess.run(
                    ["feh", "--bg-scale", str(path)],
                    capture_output=True
                )
                if result.returncode != 0:
                    return (
                        f"Could not set wallpaper automatically on {desktop_env}. "
                        f"Try manually or install 'feh'."
                    )

            return f"Wallpaper set: {path.name}"

    except Exception as e:
        return f"Could not set wallpaper: {e}"


def set_wallpaper_from_url(url: str) -> str:
    try:
        from core import confirm
        if confirm.pending_title():
            return "There is already a confirmation waiting on screen. Ask the user to answer that one first."

        parsed_name = Path(url.split("?")[0]).name
        filename = parsed_name or "wallpaper.jpg"
        suffix = Path(parsed_name).suffix or ".jpg"
        tmp = Path(tempfile.mktemp(suffix=suffix))

        title = f"Download Wallpaper: {filename}"
        detail = (
            f"File: {filename}\n"
            f"Source URL: {url}\n"
            f"Destination: {tmp}\n\n"
            f"Do you want to download and set this wallpaper?"
        )

        def _execute():
            try:
                import urllib.request
                urllib.request.urlretrieve(url, str(tmp))
                if not tmp.exists() or tmp.stat().st_size == 0:
                    return f"Download failed: file {filename} is missing or empty."
                result = set_wallpaper(str(tmp))
                try:
                    tmp.unlink()
                except Exception:
                    pass
                return result
            except Exception as e:
                return f"Could not download wallpaper: {e}"

        return confirm.request(
            key="desktop_wallpaper_url",
            title=title,
            detail=detail,
            run=_execute,
        )
    except Exception as e:
        return f"Could not download wallpaper: {e}"


def get_current_wallpaper() -> str:
    try:
        if _OS == "Windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop"
            )
            val, _ = winreg.QueryValueEx(key, "Wallpaper")
            winreg.CloseKey(key)
            return f"Current wallpaper: {val}"

        elif _OS == "Darwin":
            script = (
                'tell application "System Events" to get picture of desktop 1'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True
            )
            return f"Current wallpaper: {result.stdout.strip()}"

        else:
            desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
            if "gnome" in desktop_env or "unity" in desktop_env:
                result = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.background", "picture-uri"],
                    capture_output=True, text=True
                )
                return f"Current wallpaper: {result.stdout.strip()}"
            return "Wallpaper path retrieval not supported for this desktop environment."

    except Exception as e:
        return f"Could not get wallpaper: {e}"

FILE_TYPE_MAP = {
    "Images":      {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
    "Documents":   {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx",
                    ".ppt", ".pptx", ".csv", ".odt", ".ods", ".odp"},
    "Videos":      {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
    "Music":       {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
    "Archives":    {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Code":        {".py", ".js", ".ts", ".html", ".css", ".json", ".xml",
                    ".cpp", ".java", ".cs", ".go", ".rs", ".sh", ".php"},
    "Executables": {".exe", ".msi", ".bat", ".cmd", ".sh", ".appimage", ".deb", ".rpm"},
}

_SKIP_EXTENSIONS = {
    "Windows": {".lnk", ".url"},
    "Darwin":  {".webloc"},
    "Linux":   {".desktop"},
}


def organize_desktop(mode: str = "by_type") -> str:
    desktop       = _get_desktop()
    if not desktop.exists():
        return f"Desktop directory not found: {desktop}"

    skip_exts     = _SKIP_EXTENSIONS.get(_OS, set())

    # 1. Pre-plan all moves without touching any files
    plan: list[tuple[Path, Path, str]] = []  # (src_item, dst_path, folder_name)
    skipped: list[str] = []

    for item in desktop.iterdir():
        if item.is_dir() or item.name.startswith("."):
            continue
        if item.suffix.lower() in skip_exts:
            continue

        if mode == "by_date":
            mtime       = datetime.fromtimestamp(item.stat().st_mtime)
            folder_name = mtime.strftime("%Y-%m")
        else:
            ext         = item.suffix.lower()
            folder_name = "Others"
            for folder, exts in FILE_TYPE_MAP.items():
                if ext in exts:
                    folder_name = folder
                    break

        target_dir = desktop / folder_name
        new_path = target_dir / item.name

        if new_path.exists():
            skipped.append(item.name)
            continue

        plan.append((item, new_path, folder_name))

    if not plan:
        msg = f"Desktop is already organized ({mode}). No files to move."
        if skipped:
            msg += f" ({len(skipped)} file(s) skipped due to name conflicts)."
        return msg

    from core import confirm

    if confirm.pending_title():
        return "There is already a confirmation waiting on screen. Ask the user to answer that one first."

    lines = [f"• {src.name} → {folder_name}/" for src, dst, folder_name in plan[:10]]
    if len(plan) > 10:
        lines.append(f"... and {len(plan) - 10} more file(s)")
    if skipped:
        lines.append(f"({len(skipped)} file(s) skipped due to name conflicts)")

    detail = (
        f"Mode: {mode}\n"
        f"Total files to move: {len(plan)}\n"
        f"Desktop path: {desktop}\n\n"
        f"Planned moves:\n" + "\n".join(lines)
    )

    def _execute() -> str:
        moved = []
        journal: list[tuple[Path, Path]] = []
        for src, dst, folder_name in plan:
            try:
                dst.parent.mkdir(exist_ok=True)
                shutil.move(str(src), str(dst))
                moved.append(f"{src.name} → {folder_name}/")
                journal.append((src, dst))
            except Exception as e:
                print(f"[Desktop] organize error moving {src.name}: {e}")

        if journal:
            def _undo_organize(entries=tuple(journal)):
                restored = 0
                for orig_src, moved_dst in entries:
                    try:
                        if moved_dst.exists():
                            orig_src.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(moved_dst), str(orig_src))
                            restored += 1
                    except Exception as err:
                        print(f"[Desktop] undo organize error: {err}")
                for folder in {m.parent for _s, m in entries}:
                    try:
                        if folder.exists() and folder.is_dir() and not any(folder.iterdir()):
                            folder.rmdir()
                    except Exception:
                        pass
                return f"Restored {restored} file(s) back to Desktop."

            try:
                from core.undo import push_undo
                push_undo(f"organize desktop ({mode})", _undo_organize)
            except ImportError:
                pass

        result = f"Desktop organized ({mode}): {len(moved)} files moved."
        if moved:
            result += "\n" + "\n".join(moved[:8])
            if len(moved) > 8:
                result += f"\n... and {len(moved) - 8} more."
        if skipped:
            result += f"\n{len(skipped)} file(s) skipped (name conflict)."
        return result

    return confirm.request(
        key="desktop_organize",
        title=f"Organize Desktop: Move {len(plan)} file(s) ({mode})",
        detail=detail,
        run=_execute,
    )


def list_desktop() -> str:
    desktop = _get_desktop()
    items   = []
    for item in sorted(desktop.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            try:
                count = len(list(item.iterdir()))
            except PermissionError:
                count = "?"
            items.append(f"📁 {item.name}/ ({count} items)")
        else:
            size     = item.stat().st_size
            size_str = (
                f"{size / 1024:.1f} KB" if size < 1024 * 1024
                else f"{size / 1024 / 1024:.1f} MB"
            )
            items.append(f"📄 {item.name} ({size_str})")

    if not items:
        return "Desktop is empty."
    return f"Desktop ({len(items)} items):\n" + "\n".join(items)


def clean_desktop() -> str:
    desktop     = _get_desktop()
    if not desktop.exists():
        return f"Desktop directory not found: {desktop}"

    skip_exts   = _SKIP_EXTENSIONS.get(_OS, set())
    today       = datetime.now().strftime("%Y-%m-%d")
    archive_dir = desktop / f"Desktop Archive {today}"

    # 1. Pre-plan all files to archive without touching anything
    plan: list[tuple[Path, Path]] = []
    skipped: list[str] = []

    for item in desktop.iterdir():
        if item.is_dir() or item.name.startswith("."):
            continue
        if item.suffix.lower() in skip_exts:
            continue
        new_path = archive_dir / item.name
        if new_path.exists():
            skipped.append(item.name)
            continue
        plan.append((item, new_path))

    if not plan:
        msg = f"Desktop is already clean. No files to archive."
        if skipped:
            msg += f" ({len(skipped)} file(s) skipped due to name conflicts)."
        return msg

    from core import confirm

    if confirm.pending_title():
        return "There is already a confirmation waiting on screen. Ask the user to answer that one first."

    lines = [f"• {src.name} → {archive_dir.name}/" for src, dst in plan[:10]]
    if len(plan) > 10:
        lines.append(f"... and {len(plan) - 10} more file(s)")
    if skipped:
        lines.append(f"({len(skipped)} file(s) skipped due to name conflicts)")

    detail = (
        f"Archive folder: {archive_dir.name}\n"
        f"Total files to archive: {len(plan)}\n"
        f"Desktop path: {desktop}\n\n"
        f"Planned moves:\n" + "\n".join(lines)
    )

    def _execute() -> str:
        archive_dir.mkdir(exist_ok=True)
        moved = 0
        journal: list[tuple[Path, Path]] = []
        for src, dst in plan:
            try:
                shutil.move(str(src), str(dst))
                moved += 1
                journal.append((src, dst))
            except Exception as e:
                print(f"[Desktop] clean error moving {src.name}: {e}")

        if journal:
            def _undo_clean(entries=tuple(journal)):
                restored = 0
                for orig_src, moved_dst in entries:
                    try:
                        if moved_dst.exists():
                            orig_src.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(moved_dst), str(orig_src))
                            restored += 1
                    except Exception as err:
                        print(f"[Desktop] undo clean error: {err}")
                try:
                    if archive_dir.exists() and archive_dir.is_dir() and not any(archive_dir.iterdir()):
                        archive_dir.rmdir()
                except Exception:
                    pass
                return f"Restored {restored} file(s) from '{archive_dir.name}' back to Desktop."

            try:
                from core.undo import push_undo
                push_undo(f"clean desktop ({archive_dir.name})", _undo_clean)
            except ImportError:
                pass

        result = f"Desktop cleaned: {moved} files archived to '{archive_dir.name}'."
        if skipped:
            result += f" ({len(skipped)} file(s) skipped due to name conflicts)."
        return result

    return confirm.request(
        key="desktop_clean",
        title=f"Clean Desktop: Archive {len(plan)} file(s) to '{archive_dir.name}'",
        detail=detail,
        run=_execute,
    )


def get_desktop_stats() -> str:
    desktop    = _get_desktop()
    files      = [i for i in desktop.iterdir() if i.is_file()]
    folders    = [i for i in desktop.iterdir() if i.is_dir()]
    total_size = sum(f.stat().st_size for f in files if f.exists())
    size_str   = (
        f"{total_size / 1024:.1f} KB" if total_size < 1024 * 1024
        else f"{total_size / 1024 / 1024:.1f} MB"
    )
    return (
        f"Desktop stats ({_OS}):\n"
        f"  Files   : {len(files)}\n"
        f"  Folders : {len(folders)}\n"
        f"  Size    : {size_str}\n"
        f"  Path    : {desktop}"
    )

def desktop_control(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    parameters:
        action : wallpaper | wallpaper_url | current_wallpaper |
                 organize  | clean | list | stats |
                 task (AI-powered)
        path   : image path for 'wallpaper'
        url    : image URL for 'wallpaper_url'
        mode   : 'by_type' or 'by_date' for 'organize'
        task   : natural language description for AI-powered actions
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()
    task   = params.get("task", "").strip()

    if player:
        player.write_log(f"[desktop] {action or task[:40]}")

    try:
        if action == "wallpaper":
            path = params.get("path", "")
            return set_wallpaper(path) if path else "No image path provided."

        elif action == "wallpaper_url":
            url = params.get("url", "")
            return set_wallpaper_from_url(url) if url else "No URL provided."

        elif action == "current_wallpaper":
            return get_current_wallpaper()

        elif action == "organize":
            return organize_desktop(params.get("mode", "by_type"))

        elif action == "clean":
            return clean_desktop()

        elif action == "list":
            return list_desktop()

        elif action == "stats":
            return get_desktop_stats()

        elif action == "task" or task:
            actual_task = task or params.get("description", "")
            if not actual_task:
                return "Please describe what you want to do on the desktop."

            print(f"[Desktop] Asking Gemini: {actual_task}")
            if player:
                player.write_log("[Desktop] Generating action...")

            code = _ask_gemini_for_desktop_action(actual_task)
            return _execute_generated_code(code, player=player)

        else:
            if action:
                code = _ask_gemini_for_desktop_action(action)
                return _execute_generated_code(code, player=player)
            return "No action or task specified."

    except Exception as e:
        print(f"[Desktop] Error: {e}")
        return f"Desktop control error: {e}"


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "desktop_control",
    "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"
            },
            "path": {
                "type": "STRING",
                "description": "Image path for wallpaper"
            },
            "url": {
                "type": "STRING",
                "description": "Image URL for wallpaper_url"
            },
            "mode": {
                "type": "STRING",
                "description": "by_type or by_date for organize"
            },
            "task": {
                "type": "STRING",
                "description": "Natural language desktop task"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": desktop_control,
}
