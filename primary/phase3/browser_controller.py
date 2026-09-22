"""
Browser Controller for ProAssist AI Phase 3
Provides controlled web browsing and website navigation
using standard web protocols without credential storage or arbitrary scripting.
"""

import re
import webbrowser
from urllib.parse import urlparse
from phase3 import config as p3_config
from phase3.app_launcher import AppLauncher


class BrowserController:
    """Controls browser navigation and allowlisted website launching."""

    def __init__(self, launcher: AppLauncher = None):
        self.launcher = launcher or AppLauncher()
        self.allowed_websites = p3_config.ALLOWED_WEBSITES

    def open_browser(self, browser_name: str = None, dry_run: bool = False) -> tuple[bool, str]:
        """
        Opens the requested browser or default browser.
        """
        if browser_name:
            target = browser_name.lower().strip()
            if target in ["chrome", "google chrome"]:
                return self.launcher.launch("chrome", dry_run=dry_run)
            elif target in ["edge", "microsoft edge"]:
                return self.launcher.launch("edge", dry_run=dry_run)
            elif target in ["firefox", "mozilla firefox"]:
                return self.launcher.launch("firefox", dry_run=dry_run)

        # Fallback to system default browser via webbrowser standard library
        if dry_run:
            print("[BrowserController DRY-RUN] Verified default browser launch.")
            return True, "Opening browser."

        try:
            webbrowser.open("https://www.google.com")
            return True, "Opening browser."
        except Exception as e:
            print(f"[BrowserController ERROR] Failed to launch default browser: {e}")
            return False, "I couldn't open the browser."

    def open_website(self, site_name: str, dry_run: bool = False) -> tuple[bool, str]:
        """
        Opens an allowlisted website (e.g. Google, YouTube, Gmail, GitHub).
        """
        key = site_name.lower().strip()
        url = self.allowed_websites.get(key)

        if not url:
            # Check for partial match (e.g. 'yt' for 'youtube')
            for site_key, site_url in self.allowed_websites.items():
                if site_key in key:
                    url = site_url
                    key = site_key
                    break

        if not url:
            print(f"[BrowserController SECURITY] Website '{site_name}' not in predefined allowlist.")
            return False, f"I don't have a configured shortcut for {site_name}."

        display_name = key.capitalize()
        if key == "youtube":
            display_name = "YouTube"
        elif key == "github":
            display_name = "GitHub"
        elif key == "gmail":
            display_name = "Gmail"

        if dry_run:
            print(f"[BrowserController DRY-RUN] Verified opening website: {display_name} ({url})")
            return True, f"Opening {display_name}."

        try:
            webbrowser.open(url)
            return True, f"Opening {display_name}."
        except Exception as e:
            print(f"[BrowserController ERROR] Failed to open website {display_name}: {e}")
            return False, f"I couldn't open {display_name}."

    def open_url_safely(self, url: str, dry_run: bool = False) -> tuple[bool, str]:
        """
        Safely opens a validated HTTP/HTTPS URL.
        Rejects non-HTTP schemes (e.g. file://, javascript:, data:).
        """
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"]:
            print(f"[BrowserController SECURITY] Rejected disallowed URL scheme: '{parsed.scheme}'")
            return False, "Invalid or unsafe web address."

        if dry_run:
            print(f"[BrowserController DRY-RUN] Verified opening safe URL: {url}")
            return True, "Opening web page."

        try:
            import os
            import sys
            import subprocess

            launched = False
            if sys.platform == "win32":
                browser_candidates = [
                    os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                    os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                    os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
                    os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
                ]
                for c in browser_candidates:
                    if os.path.isfile(c):
                        subprocess.Popen([c, url], shell=False)
                        launched = True
                        break

            if not launched:
                webbrowser.open(url)
            return True, "Opening web page."
        except Exception as e:
            print(f"[BrowserController ERROR] Failed to open URL {url}: {e}")
            return False, "I couldn't open the web page."
