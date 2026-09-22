"""
Phase 3 Configuration: Desktop and Web Action Agent
Defines strict allowlists for applications, websites, folders,
and safety policies for ProAssist AI.
"""

from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# =====================================================================
# APPLICATION ALLOWLIST (Safe, predefined executables)
# =====================================================================
ALLOWED_APPLICATIONS = {
    "chrome": {
        "name": "Google Chrome",
        "executables": ["chrome.exe", "google-chrome"],
        "display_name": "Chrome",
    },
    "edge": {
        "name": "Microsoft Edge",
        "executables": ["msedge.exe"],
        "display_name": "Microsoft Edge",
    },
    "firefox": {
        "name": "Mozilla Firefox",
        "executables": ["firefox.exe"],
        "display_name": "Firefox",
    },
    "calculator": {
        "name": "Calculator",
        "executables": ["calc.exe"],
        "display_name": "Calculator",
    },
    "notepad": {
        "name": "Notepad",
        "executables": ["notepad.exe"],
        "display_name": "Notepad",
    },
    "explorer": {
        "name": "File Explorer",
        "executables": ["explorer.exe"],
        "display_name": "File Explorer",
    },
}

# =====================================================================
# ALLOWED WEBSITES & URL TEMPLATES
# =====================================================================
ALLOWED_WEBSITES = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "github": "https://www.github.com",
}

GOOGLE_SEARCH_URL = "https://www.google.com/search?q={query}"
YOUTUBE_SEARCH_URL = "https://www.youtube.com/results?search_query={query}"

# =====================================================================
# ALLOWED FOLDERS FOR FILE EXPLORER
# =====================================================================
USER_HOME = Path.home()
DOCUMENTS_DIR = (USER_HOME / "OneDrive" / "Documents") if (USER_HOME / "OneDrive" / "Documents").exists() else (USER_HOME / "Documents")
DESKTOP_DIR = (USER_HOME / "OneDrive" / "Desktop") if (USER_HOME / "OneDrive" / "Desktop").exists() else (USER_HOME / "Desktop")
DOWNLOADS_DIR = USER_HOME / "Downloads"

ALLOWED_FOLDERS = {
    "downloads": DOWNLOADS_DIR,
    "documents": DOCUMENTS_DIR,
    "desktop": DESKTOP_DIR,
    "explorer": USER_HOME,
}

# =====================================================================
# SAFETY & SECURITY RESTRICTIONS
# =====================================================================
# Disallowed destructive tokens that trigger immediate security block
DANGEROUS_PATTERNS = [
    r"\b(powershell|cmd\.exe|os\.system|subprocess|eval|exec|shutil)\b",
    r"\b(rmdir|del\s+|delete\s+everything|format\s+[c-z]:|drop\s+database)\b",
    r"\b(regedit|shutdown|taskkill|curl|wget|chmod|chown)\b",
]
