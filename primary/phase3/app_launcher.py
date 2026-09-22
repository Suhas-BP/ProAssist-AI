"""
Safe Application Launcher for ProAssist AI Phase 3
Launches allowlisted desktop applications without executing arbitrary shell commands.
"""

import json
import os
import re
import sys
import subprocess
import shutil
from phase3 import config as p3_config


class AppLauncher:
    """Safe application launcher supporting core applications and dynamic laptop application discovery."""

    def __init__(self, allowlist: dict = None):
        self.allowlist = allowlist or p3_config.ALLOWED_APPLICATIONS.copy()
        self._system_apps = {}
        self._apps_discovered = False

    def discover_system_apps(self) -> dict:
        """
        Discovers all installed applications on the Windows laptop:
        - Start Menu shortcuts (.lnk files)
        - Windows Store / UWP apps (Get-StartApps)
        - Built-in utilities (paint, settings, camera, clock, task manager, etc.)
        """
        if self._apps_discovered:
            return self._system_apps

        apps = {}

        if sys.platform == "win32":
            # 1. Start Menu Shortcuts (.lnk files)
            shortcut_paths = [
                os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
                os.path.expandvars(r"%AppData%\Microsoft\Windows\Start Menu\Programs"),
            ]
            for base in shortcut_paths:
                if os.path.exists(base):
                    for root, _, files in os.walk(base):
                        for f in files:
                            if f.lower().endswith(".lnk"):
                                name = f[:-4].strip()
                                full_path = os.path.join(root, f)
                                apps[name.lower()] = {
                                    "name": name,
                                    "display_name": name,
                                    "path": full_path,
                                    "type": "lnk",
                                }

            # 2. Windows StartApps / UWP apps via PowerShell
            try:
                cmd = ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json"]
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=4,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                )
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    for item in data:
                        n = item.get("Name", "").strip()
                        app_id = item.get("AppID", "").strip()
                        if n and app_id:
                            key = n.lower()
                            if key not in apps:
                                apps[key] = {
                                    "name": n,
                                    "display_name": n,
                                    "app_id": app_id,
                                    "type": "uwp",
                                }
            except Exception:
                pass

            # 3. Standard built-in Windows accessories and utilities
            common_utilities = {
                "paint": {"name": "Paint", "target": "mspaint.exe", "type": "exe"},
                "mspaint": {"name": "Paint", "target": "mspaint.exe", "type": "exe"},
                "task manager": {"name": "Task Manager", "target": "taskmgr.exe", "type": "exe"},
                "taskmgr": {"name": "Task Manager", "target": "taskmgr.exe", "type": "exe"},
                "snipping tool": {"name": "Snipping Tool", "target": "snippingtool.exe", "type": "exe"},
                "snip": {"name": "Snipping Tool", "target": "snippingtool.exe", "type": "exe"},
                "settings": {"name": "Settings", "target": "ms-settings:", "type": "protocol"},
                "camera": {"name": "Camera", "target": "microsoft.windows.camera:", "type": "protocol"},
                "clock": {"name": "Clock", "target": "ms-clock:", "type": "protocol"},
                "wordpad": {"name": "WordPad", "target": "write.exe", "type": "exe"},
                "control panel": {"name": "Control Panel", "target": "control.exe", "type": "exe"},
                "cmd": {"name": "Command Prompt", "target": "cmd.exe", "type": "exe"},
                "command prompt": {"name": "Command Prompt", "target": "cmd.exe", "type": "exe"},
            }
            for k, v in common_utilities.items():
                if k not in apps:
                    apps[k] = {
                        "name": v["name"],
                        "display_name": v["name"],
                        "target": v["target"],
                        "type": v["type"],
                    }

        self._system_apps = apps
        self._apps_discovered = True
        return self._system_apps

    def find_system_app(self, query: str) -> dict | None:
        """
        Locates an installed application matching query using fuzzy & exact scoring.
        """
        clean_q = query.lower().strip()
        # Security threat check
        for pat in p3_config.DANGEROUS_PATTERNS:
            if re.search(pat, clean_q):
                return None

        # Clean noise words
        clean_q = re.sub(r"\b(the|my|app|application|software|program|tool)\b", " ", clean_q)
        clean_q = " ".join(clean_q.split())
        if not clean_q:
            return None

        # Ensure discovery has run
        self.discover_system_apps()

        # Direct dictionary match
        if clean_q in self._system_apps:
            return self._system_apps[clean_q]

        # Common aliases
        aliases = {
            "vscode": "visual studio code",
            "vs code": "visual studio code",
            "code": "visual studio code",
            "chrome": "google chrome",
            "edge": "microsoft edge",
            "word": "word",
            "excel": "excel",
            "ppt": "powerpoint",
            "powerpoint": "powerpoint",
            "photos": "photos",
            "spotify": "spotify",
            "calculator": "calculator",
            "calc": "calculator",
            "notepad": "notepad",
            "note pad": "notepad",
            "terminal": "terminal",
            "browser": "google chrome",
        }
        if clean_q in aliases:
            target_alias = aliases[clean_q]
            if target_alias in self._system_apps:
                return self._system_apps[target_alias]

        # Exact match or word boundaries
        candidates = []
        for key, info in self._system_apps.items():
            if key == clean_q:
                return info
            if key.startswith(clean_q + " ") or key.startswith(clean_q):
                candidates.append((50, info))
            elif clean_q in key.split():
                candidates.append((40, info))
            elif clean_q in key:
                candidates.append((20, info))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

        return None

    def is_allowed(self, app_key: str) -> bool:
        """Checks if app_key exists in predefined allowlist or is an installed system application."""
        key = app_key.lower().strip()
        if key in self.allowlist:
            return True
        return self.find_system_app(key) is not None

    def get_app_info(self, app_key: str) -> dict:
        """Returns metadata for the given app key or None."""
        key = app_key.lower().strip()
        if key in self.allowlist:
            return self.allowlist.get(key)
        return self.find_system_app(key)

    def launch_application(self, app_key: str, dry_run: bool = False) -> tuple[bool, str]:
        """Alias for launch() to support explicit launch_application API calls."""
        return self.launch(app_key, dry_run=dry_run)

    @staticmethod
    def _spawn(target: str, app_type: str = "exe") -> bool:
        """Safely and reliably spawns an application on Windows/Linux."""
        if app_type == "uwp":
            try:
                uwp_id = target if target.startswith("shell:AppsFolder\\") else f"shell:AppsFolder\\{target}"
                subprocess.Popen(["explorer.exe", uwp_id], shell=False)
                return True
            except Exception:
                return False

        if sys.platform == "win32":
            # Method 1: PowerShell Start-Process (handles .lnk, Click-To-Run, protocols, and standard exes)
            try:
                cmd = ["powershell", "-WindowStyle", "Hidden", "-Command", f"Start-Process '{target}'"]
                subprocess.Popen(cmd, shell=False)
                return True
            except Exception:
                pass

            # Method 2: cmd.exe start
            try:
                subprocess.Popen(["cmd.exe", "/c", "start", "", target], shell=False)
                return True
            except Exception:
                pass

        # Method 3: direct subprocess.Popen
        try:
            subprocess.Popen([target], shell=False)
            return True
        except Exception:
            pass

        return False

    def launch(self, app_key: str, dry_run: bool = False) -> tuple[bool, str]:
        """
        Safely launches an allowlisted application.
        Args:
            app_key: Identifier from ALLOWED_APPLICATIONS (e.g. 'chrome', 'calculator').
            dry_run: When True, simulates launch without spawning subprocesses.
        Returns:
            tuple: (success: bool, response_message: str)
        """
        key = app_key.lower().strip()
        if not self.is_allowed(key):
            print(f"[AppLauncher SECURITY] Blocked unauthorized application launch request: '{key}'")
            return False, f"I cannot open {app_key} because it is not on the allowed applications list."

        # 1. Predefined allowlist apps (Chrome, Edge, Firefox, Calculator, Notepad, Explorer)
        if key in self.allowlist:
            app_info = self.allowlist[key]
            display_name = app_info.get("display_name", key.capitalize())

            if dry_run:
                print(f"[AppLauncher DRY-RUN] Verified launch for: {display_name}")
                return True, f"Opening {display_name}."

            executables = app_info.get("executables", [])
            launched = False
            error_reason = ""

            # Direct reliable spawn on Windows
            if sys.platform == "win32":
                well_known = {
                    "calculator": "calc",
                    "notepad": "notepad",
                    "explorer": "explorer",
                    "chrome": "chrome",
                    "edge": "msedge",
                }
                if key in well_known:
                    try:
                        if self._spawn(well_known[key]):
                            print(f"[AppLauncher] Successfully launched: {display_name}")
                            return True, f"Opening {display_name}."
                    except Exception as e:
                        error_reason = str(e)

            for exe in executables:
                try:
                    resolved_exe = shutil.which(exe)
                    if not resolved_exe and sys.platform == "win32":
                        candidates = [
                            os.path.expandvars(rf"%ProgramFiles%\Google\Chrome\Application\{exe}"),
                            os.path.expandvars(rf"%ProgramFiles(x86)%\Google\Chrome\Application\{exe}"),
                            os.path.expandvars(rf"%LOCALAPPDATA%\Google\Chrome\Application\{exe}"),
                            os.path.expandvars(rf"%ProgramFiles(x86)%\Microsoft\Edge\Application\{exe}"),
                            os.path.expandvars(rf"%ProgramFiles%\Microsoft\Edge\Application\{exe}"),
                            os.path.expandvars(rf"%ProgramFiles%\Mozilla Firefox\{exe}"),
                            os.path.expandvars(rf"%ProgramFiles(x86)%\Mozilla Firefox\{exe}"),
                        ]
                        for c in candidates:
                            if os.path.isfile(c):
                                resolved_exe = c
                                break

                    if resolved_exe:
                        subprocess.Popen([resolved_exe], shell=False)
                        launched = True
                        break
                    elif sys.platform == "win32":
                        if self._spawn(exe):
                            launched = True
                            break
                except Exception as e:
                    error_reason = str(e)
                    continue

            if launched:
                print(f"[AppLauncher] Successfully launched: {display_name}")
                return True, f"Opening {display_name}."

            print(f"[AppLauncher ERROR] Failed to launch {display_name}: {error_reason}")
            return False, f"I couldn't open {display_name}."

        # 2. Dynamically discovered system applications (Word, Excel, PowerPoint, Camera, Settings, etc.)
        sys_app = self.find_system_app(key)
        if sys_app:
            display_name = sys_app.get("display_name", sys_app.get("name", key.capitalize()))
            if dry_run:
                print(f"[AppLauncher DRY-RUN] Verified launch for system app: {display_name}")
                return True, f"Opening {display_name}."

            try:
                app_type = sys_app.get("type", "exe")
                target = sys_app.get("path") or sys_app.get("app_id") or sys_app.get("target")
                if target and self._spawn(target, app_type=app_type):
                    print(f"[AppLauncher] Successfully launched system app: {display_name}")
                    return True, f"Opening {display_name}."
            except Exception as e:
                print(f"[AppLauncher ERROR] Failed to launch system app {display_name}: {e}")
                return False, f"I couldn't open {display_name}."

            return False, f"I couldn't open {display_name}."

        print(f"[AppLauncher SECURITY] Application not found or blocked: '{key}'")
        return False, f"I couldn't find an application named '{app_key}' on your laptop."


def launch_application(app_key: str, dry_run: bool = False) -> tuple[bool, str]:
    """Module-level helper to launch an allowlisted application."""
    launcher = AppLauncher()
    return launcher.launch(app_key, dry_run=dry_run)

