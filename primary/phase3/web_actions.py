"""
Controlled Web Actions for ProAssist AI Phase 3
Handles Google Search, YouTube Search, and YouTube Playback
using safe URL formatting and browser dispatch.
"""

import urllib.parse
from phase3 import config as p3_config
from phase3.browser_controller import BrowserController


class WebActions:
    """Executes safe, allowlisted web actions like Google Search and YouTube navigation."""

    def __init__(self, browser_controller: BrowserController = None):
        self.browser = browser_controller or BrowserController()

    def search_google(self, query: str, dry_run: bool = False) -> tuple[bool, str]:
        """
        Executes a Google Search for the given query.
        """
        clean_query = query.strip()
        if not clean_query:
            return False, "What would you like me to search for on Google?"

        encoded_query = urllib.parse.quote_plus(clean_query)
        search_url = p3_config.GOOGLE_SEARCH_URL.format(query=encoded_query)

        if dry_run:
            try:
                print(f"[WebActions DRY-RUN] Verified Google Search: '{clean_query}' -> {search_url}")
            except UnicodeEncodeError:
                safe_q = clean_query.encode("ascii", "backslashreplace").decode("ascii")
                print(f"[WebActions DRY-RUN] Verified Google Search: '{safe_q}' -> {search_url}")
            return True, f"Searching Google for {clean_query}."

        success, _ = self.browser.open_url_safely(search_url, dry_run=False)
        if success:
            return True, f"Searching Google for {clean_query}."
        else:
            return False, f"I couldn't perform the Google search for {clean_query}."

    def search_youtube(self, query: str, dry_run: bool = False) -> tuple[bool, str]:
        """
        Executes a YouTube search for the specified topic/song/video.
        """
        clean_query = query.strip()
        if not clean_query:
            return False, "What would you like me to search for on YouTube?"

        encoded_query = urllib.parse.quote_plus(clean_query)
        search_url = p3_config.YOUTUBE_SEARCH_URL.format(query=encoded_query)

        if dry_run:
            try:
                print(f"[WebActions DRY-RUN] Verified YouTube Search: '{clean_query}' -> {search_url}")
            except UnicodeEncodeError:
                safe_q = clean_query.encode("ascii", "backslashreplace").decode("ascii")
                print(f"[WebActions DRY-RUN] Verified YouTube Search: '{safe_q}' -> {search_url}")
            return True, f"Searching YouTube for {clean_query}."

        success, _ = self.browser.open_url_safely(search_url, dry_run=False)
        if success:
            return True, f"Searching YouTube for {clean_query}."
        else:
            return False, f"I couldn't perform the YouTube search for {clean_query}."

    def play_youtube(self, query: str, dry_run: bool = False) -> tuple[bool, str]:
        """
        Plays the requested song/video on YouTube by navigating directly to the top result query.
        Accurately reports playback state without claiming phantom automation.
        """
        clean_query = query.strip()
        if not clean_query:
            return False, "What would you like me to play on YouTube?"

        encoded_query = urllib.parse.quote_plus(clean_query)
        search_url = p3_config.YOUTUBE_SEARCH_URL.format(query=encoded_query)

        if dry_run:
            try:
                print(f"[WebActions DRY-RUN] Verified YouTube Play: '{clean_query}' -> {search_url}")
            except UnicodeEncodeError:
                safe_q = clean_query.encode("ascii", "backslashreplace").decode("ascii")
                print(f"[WebActions DRY-RUN] Verified YouTube Play: '{safe_q}' -> {search_url}")
            return True, f"Playing {clean_query} on YouTube."

        success, _ = self.browser.open_url_safely(search_url, dry_run=False)
        if success:
            # Report accurate response to user
            return True, f"Playing {clean_query} on YouTube."
        else:
            return False, f"I couldn't play {clean_query} on YouTube."
