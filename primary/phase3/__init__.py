"""
ProAssist AI - Phase 3: Desktop & Web Action Agent
Provides safe, allowlisted application execution, browser control,
web search, YouTube actions, safe math evaluation, and desktop automation.
"""

from phase3.config import (
    ALLOWED_APPLICATIONS,
    ALLOWED_WEBSITES,
    ALLOWED_FOLDERS,
    GOOGLE_SEARCH_URL,
    YOUTUBE_SEARCH_URL,
)
from phase3.app_launcher import AppLauncher
from phase3.browser_controller import BrowserController
from phase3.web_actions import WebActions
from phase3.desktop_controller import DesktopController, SafeMathEvaluator
from phase3.phase3_router import Phase3Router

__all__ = [
    "ALLOWED_APPLICATIONS",
    "ALLOWED_WEBSITES",
    "ALLOWED_FOLDERS",
    "GOOGLE_SEARCH_URL",
    "YOUTUBE_SEARCH_URL",
    "AppLauncher",
    "BrowserController",
    "WebActions",
    "DesktopController",
    "SafeMathEvaluator",
    "Phase3Router",
]
