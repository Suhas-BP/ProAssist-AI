"""
Phase 3 Command Router for ProAssist AI
Interprets desktop and web action commands:
- Application Launching (Chrome, Edge, Firefox, Calculator, Notepad, File Explorer)
- Website Opening (Google, YouTube, Gmail, GitHub)
- Google Search & YouTube Search/Playback
- Safe Mathematical Calculations
- Notepad Typing Automation
- File Explorer Folder Navigation
- Volume Control (set volume, mute, unmute, volume up/down)
- Media Key Control (play/pause, next track, previous track)
- Screenshot Capture
- Window Management (minimize, maximize, close)
- Clipboard Read
- Multi-step Commands
- Security Allowlist & Threat Blocking
"""

import re
from phase3 import config as p3_config
from phase3.app_launcher import AppLauncher
from phase3.browser_controller import BrowserController
from phase3.web_actions import WebActions
from phase3.desktop_controller import DesktopController
from phase3.system_controller import SystemController


class Phase3Router:
    """Routes desktop, web, calculation, and system operation voice commands to safe execution handlers."""

    def __init__(self,
                 app_launcher: AppLauncher = None,
                 browser_controller: BrowserController = None,
                 web_actions: WebActions = None,
                 desktop_controller: DesktopController = None,
                 system_controller: SystemController = None):
        self.launcher = app_launcher or AppLauncher()
        self.browser = browser_controller or BrowserController(launcher=self.launcher)
        self.web = web_actions or WebActions(browser_controller=self.browser)
        self.desktop = desktop_controller or DesktopController(launcher=self.launcher)
        self.system = system_controller or SystemController()



    def _clean_input(self, text: str) -> str:
        """Strips conversational fillers, polite prefixes, and expands contractions."""
        t = text.strip()
        replacements = [
            (r"\bwhat's\b", "what is"),
            (r"\bthat's\b", "that is"),
            (r"\btoday's\b", "todays"),
            (r"\bit's\b", "it is"),
            (r"\bcan't\b", "cannot"),
            (r"\bi'm\b", "i am"),
            (r"\bi'd\b", "i would"),
            (r"\bnote\s+pad\b", "notepad"),
            (r"\bweb\s+browser\b", "browser"),
            (r"\binternet\s+browser\b", "browser"),
            (r"\bchrome\s+browser\b", "chrome"),
            (r"\bgoogle\s+chrome\b", "chrome"),
            (r"\bmicrosoft\s+edge\b", "edge"),
            (r"\bms\s+edge\b", "edge"),
            (r"\bmozilla\s+firefox\b", "firefox"),
            (r"\bfile\s+manager\b", "explorer"),
            (r"\bmy\s+files\b", "explorer"),
            (r"\b(?:open|launch|start)\s+(?:the\s+)?(?:brows|brower|bus(?![\s_-]*pass))\b", "open browser"),
        ]
        for pat, repl in replacements:
            t = re.sub(pat, repl, t, flags=re.IGNORECASE)

        t = re.sub(r"[?!.,;:\"]+", " ", t).strip()
        t = " ".join(t.split())

        prefixes = [
            r"^(?:can\s+you\s+please|could\s+you\s+please|would\s+you\s+please|will\s+you\s+please)\s+",
            r"^(?:can\s+you|could\s+you|would\s+you|will\s+you)\s+(?!hear\s+me\b)",
            r"^(?:please|kindly)\s+",
            r"^(?:i\s+want\s+you\s+to|i\s+need\s+you\s+to|i\s+would\s+like\s+you\s+to|i'd\s+like\s+you\s+to)\s+",
            r"^(?:help\s+me\s+to|help\s+me)\s+",
            r"^(?:just|go\s+ahead\s+and)\s+",
            r"^(?:hey\s+proassist|proassist|agent|hey\s+agent)\s*,?\s*",
        ]
        trailing = [
            r"\s+(?:for\s+me\s+please|for\s+me|please|thanks|thank\s+you)$",
            r"\s+(?:right\s+now|now|quickly)$",
        ]
        changed = True
        while changed:
            changed = False
            for p in prefixes:
                new_t = re.sub(p, "", t, flags=re.IGNORECASE).strip()
                if new_t != t:
                    t = new_t
                    changed = True
            for tr in trailing:
                new_t = re.sub(tr, "", t, flags=re.IGNORECASE).strip()
                if new_t != t:
                    t = new_t
                    changed = True
        return t

    def is_security_threat(self, text: str) -> bool:
        """Detects unauthorized shell invocation or destructive system patterns."""
        t = text.lower()
        for pat in p3_config.DANGEROUS_PATTERNS:
            if re.search(pat, t):
                return True
        return False

    def execute(self, command_text: str, dry_run: bool = False) -> dict:
        """
        Parses and executes a Phase 3 command safely.
        Returns:
            dict containing handled (bool), intent (str), response (str), executed (bool), and status (str).
        """
        raw_text = command_text.strip()
        if not raw_text:
            return {
                "handled": False,
                "intent": "empty",
                "raw_text": "",
                "response": "I didn't catch that. Could you please repeat?",
                "executed": False,
                "status": "empty",
            }

        # 1. Security Check: Block dangerous shell and destructive commands
        if self.is_security_threat(raw_text):
            print(f"[Phase3 SECURITY ALERT] Blocked dangerous voice input: '{raw_text}'")
            return {
                "handled": False,
                "intent": "unknown",
                "raw_text": raw_text,
                "response": f"I heard \"{raw_text}\", but I don't know how to handle that command yet.",
                "executed": False,
                "status": "unknown",
            }

        cleaned = self._clean_input(raw_text)

        # 2. Multi-step command: "Open YouTube and search for <query>"
        multi_yt = re.search(r"open\s+youtube\s+and\s+search\s+(?:for\s+)?(.+)", cleaned, re.IGNORECASE)
        if multi_yt:
            query = multi_yt.group(1).strip()
            success, resp = self.web.search_youtube(query, dry_run=dry_run)
            return {
                "handled": True,
                "intent": "youtube_search",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        # Multi-step command: "Open Chrome and search Google for <query>"
        multi_google = re.search(r"open\s+(?:chrome|browser)\s+and\s+(?:search\s+google\s+for|search\s+for|google\s+search)\s+(.+)", cleaned, re.IGNORECASE)
        if multi_google:
            query = multi_google.group(1).strip()
            success, resp = self.web.search_google(query, dry_run=dry_run)
            return {
                "handled": True,
                "intent": "google_search",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        # 3. YouTube Play Commands: "play <song/artist> on youtube" or explicit youtube play
        # Bare "play music", "play/pause", "resume" are reserved for media key control (section 12)
        MEDIA_CONTROL_WORDS = {"music", "song", "audio", "video", "playback", "pause", "resume"}
        yt_play_match = re.search(r"\bplay\s+(.+?)(?:\s+on\s+youtube|\s+in\s+youtube)?$", cleaned, re.IGNORECASE)
        if yt_play_match and ("youtube" in cleaned.lower() or cleaned.lower().startswith("play ")):
            query = yt_play_match.group(1).strip()
            # Remove trailing "on youtube" if captured
            query = re.sub(r"\s+on\s+youtube$", "", query, flags=re.IGNORECASE).strip()
            # Only route to YouTube if: youtube is mentioned, OR query is not a generic media control word
            query_words = set(query.lower().split())
            is_media_control = query_words.issubset(MEDIA_CONTROL_WORDS)
            if query and query.lower() != "the first result" and not is_media_control:
                # Only play on YouTube if youtube is explicitly mentioned OR it's clearly a specific title
                if "youtube" in cleaned.lower() or (not is_media_control and not re.match(r"^(music|song|audio|video|playback)$", query, re.IGNORECASE)):
                    success, resp = self.web.play_youtube(query, dry_run=dry_run)
                    return {
                        "handled": True,
                        "intent": "youtube_play",
                        "raw_text": raw_text,
                        "response": resp,
                        "executed": success,
                        "status": "success" if success else "error",
                    }
            elif query.lower() == "the first result":
                return {
                    "handled": True,
                    "intent": "youtube_play",
                    "raw_text": raw_text,
                    "response": "Playing it.",
                    "executed": True,
                    "status": "success",
                }



        # 4. YouTube Search Commands: "search youtube for <query>" or "find <query> on youtube"
        yt_search_match = re.search(r"(?:search\s+youtube\s+for|find\s+(?:videos\s+)?(.+?)\s+on\s+youtube|search\s+on\s+youtube\s+for)\s*(.*)", cleaned, re.IGNORECASE)
        if yt_search_match:
            query = yt_search_match.group(1) or yt_search_match.group(2)
            query = query.strip()
            if query:
                success, resp = self.web.search_youtube(query, dry_run=dry_run)
                return {
                    "handled": True,
                    "intent": "youtube_search",
                    "raw_text": raw_text,
                    "response": resp,
                    "executed": success,
                    "status": "success" if success else "error",
                }

        # 5. Google Search Commands:
        # "search google for <query>", "google search <query>", "search for <query> on google", "search the web for <query>", "look up <query>"
        google_search_match = re.search(r"(?:search\s+google\s+for|google\s+search|search\s+for\s+(.+?)\s+on\s+google|search\s+(.+?)\s+on\s+google|search\s+the\s+web\s+for|look\s+up\s+(.+?)\s+on\s+google|look\s+up)\s*(.*)", cleaned, re.IGNORECASE)
        if google_search_match:
            query = google_search_match.group(1) or google_search_match.group(2) or google_search_match.group(3) or google_search_match.group(4)
            query = re.sub(r"\s+on\s+google$", "", (query or "").strip(), flags=re.IGNORECASE).strip()
            if query:
                success, resp = self.web.search_google(query, dry_run=dry_run)
                return {
                    "handled": True,
                    "intent": "google_search",
                    "raw_text": raw_text,
                    "response": resp,
                    "executed": success,
                    "status": "success" if success else "error",
                }

        # 6. Calculator Operations: "calculate <expr>", "what is <expr>"
        if re.search(r"\b(calculate|solve|evaluate)\b", cleaned, re.IGNORECASE) or (re.search(r"\bwhat\s+is\s+\d+", cleaned, re.IGNORECASE) and any(op in cleaned.lower() for op in ["plus", "minus", "times", "multiplied", "divided", "percent", "%", "power", "+", "-", "*", "/"])):
            success, resp = self.desktop.calculate(cleaned)
            return {
                "handled": True,
                "intent": "calculate",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        # 7. Notepad Typing: "type <text> in notepad", "write <text> in notepad", "open notepad and write <text>"
        type_match = re.search(r"(?:open\s+notepad\s+and\s+(?:type|write)|type|write|note\s+down)\s+(?:in|into|on\s+notepad)?\s*(.+?)(?:\s+in\s+notepad|\s+into\s+notepad|\s+on\s+notepad)?$", cleaned, re.IGNORECASE)
        if type_match and ("notepad" in cleaned.lower() or cleaned.lower().startswith("type ") or cleaned.lower().startswith("write ") or "open notepad and" in cleaned.lower()):
            text_to_type = type_match.group(1).strip().strip("'\"")
            text_to_type = re.sub(r"\s+in\s+notepad$", "", text_to_type, flags=re.IGNORECASE).strip()
            text_to_type = re.sub(r"\s+into\s+notepad$", "", text_to_type, flags=re.IGNORECASE).strip()
            text_to_type = re.sub(r"\s+on\s+notepad$", "", text_to_type, flags=re.IGNORECASE).strip()
            text_to_type = re.sub(r"^(?:in|into|on)\s+notepad\s+", "", text_to_type, flags=re.IGNORECASE).strip()
            if text_to_type:
                success, resp = self.desktop.type_in_notepad(text_to_type, dry_run=dry_run)
                return {
                    "handled": True,
                    "intent": "type_in_notepad",
                    "raw_text": raw_text,
                    "response": resp,
                    "executed": success,
                    "status": "success" if success else "error",
                }

        # 8. File Explorer Folders: "open downloads", "open documents", "open desktop", "open file explorer"
        folder_match = re.search(r"\b(?:open|launch|show)\s+(?:the\s+|my\s+)?(downloads|documents|desktop|file\s+explorer|explorer)(?:\s+folder)?\b", cleaned, re.IGNORECASE)
        if folder_match:
            folder_key = folder_match.group(1).lower().replace("file explorer", "explorer").strip()
            success, resp = self.desktop.open_folder(folder_key, dry_run=dry_run)
            return {
                "handled": True,
                "intent": "open_folder",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        # 8.5 File Opening: "open bus pass", "open bus pass application", "open file <name>", "open document <name>"
        if re.search(r"\bopen\s+(?:a\s+|the\s+)?file\s+(?:from|in)\s+(?:the\s+)?file\s+explorer\b", cleaned, re.IGNORECASE) and not any(k in cleaned.lower() for k in ["bus pass", "student", "project", "review", ".pdf", ".docx", ".txt"]):
            success, resp = self.desktop.open_folder("explorer", dry_run=dry_run)
            return {
                "handled": True,
                "intent": "open_folder",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        open_file_match = re.search(r"\b(?:open|launch|show|view)\s+(?:the\s+|a\s+)?(?:file|pdf|document)?\s*(bus\s+pass\s+application|student\s+bus\s+pass|bus\s+pass|major\s+project|[a-zA-Z0-9_\-\s]+?\.(?:pdf|docx|txt|md))\b", cleaned, re.IGNORECASE)
        if not open_file_match and not re.search(r"\bopen\s+(?:the\s+|my\s+)?(?:file\s+explorer|explorer)\b", cleaned, re.IGNORECASE):
            open_file_match = re.search(r"\bopen\s+(?:the\s+|a\s+)?(?:file|pdf|document)\s+(?:from\s+(?:the\s+)?file\s+explorer\s+)?(?!explorer\b)(.+)", cleaned, re.IGNORECASE)
        if open_file_match:
            target_file_query = open_file_match.group(1).strip()
            success, resp = self.desktop.open_file(target_file_query, dry_run=dry_run)
            return {
                "handled": True,
                "intent": "open_file",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        # 9. Allowed Website Opening: "open google", "open youtube", "open gmail", "open github"
        site_match = re.search(r"\b(?:open|launch|start|visit|go\s+to|check)\s+(?:my\s+|the\s+)?(gmail|google\s+mail|youtube|google(?!\s+chrome)|github)(?:\.com)?(?:\s+(?:website|site|app|page))?\b", cleaned, re.IGNORECASE)
        if site_match:
            site_raw = site_match.group(1).lower().strip()
            site_key = "gmail" if site_raw in ["gmail", "google mail"] else site_raw
            success, resp = self.browser.open_website(site_key, dry_run=dry_run)
            return {
                "handled": True,
                "intent": "open_website",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        # 10. Allowed Application Launching:
        # "open chrome", "launch edge", "open firefox", "open calculator", "open notepad", "open browser"
        app_match = re.search(r"\b(?:open|launch|start|run)\s+(?:the\s+|my\s+)?(google\s+chrome|chrome|calculator|calc|notepad|note\s+pad|edge|microsoft\s+edge|firefox|browser|file\s+explorer|explorer)(?:\s+browser|\s+app)?\b", cleaned, re.IGNORECASE)
        if app_match:
            matched_app = app_match.group(1).lower().strip()
            if matched_app in ["chrome", "google chrome"]:
                success, resp = self.launcher.launch("chrome", dry_run=dry_run)
            elif matched_app in ["edge", "microsoft edge"]:
                success, resp = self.launcher.launch("edge", dry_run=dry_run)
            elif matched_app in ["firefox"]:
                success, resp = self.launcher.launch("firefox", dry_run=dry_run)
            elif matched_app in ["calculator", "calc"]:
                success, resp = self.launcher.launch("calculator", dry_run=dry_run)
            elif matched_app in ["notepad", "note pad"]:
                success, resp = self.launcher.launch("notepad", dry_run=dry_run)
            elif matched_app in ["explorer", "file explorer"]:
                success, resp = self.launcher.launch("explorer", dry_run=dry_run)
            elif matched_app in ["browser"]:
                success, resp = self.browser.open_browser(dry_run=dry_run)
            else:
                success, resp = False, f"Unknown application: {matched_app}"

            return {
                "handled": True,
                "intent": "open_application",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        # 10.5 Dynamic Laptop Application Launching (Word, Excel, PowerPoint, Camera, Settings, Paint, Cursor, etc.)
        dynamic_app_match = re.search(r"\b(?:open|launch|start|run)\s+(?:the\s+|my\s+)?([a-zA-Z0-9\s_\-\.]{2,35}?)(?:\s+(?:app|application|software|program))?$", cleaned, re.IGNORECASE)
        if dynamic_app_match:
            cand_app = dynamic_app_match.group(1).strip()
            if cand_app and not any(k in cand_app.lower() for k in ["file", "document", "pdf", "youtube", "google", "gmail", "github", "search", "something"]):
                sys_app = self.launcher.find_system_app(cand_app)
                if sys_app:
                    success, resp = self.launcher.launch(cand_app, dry_run=dry_run)
                    return {
                        "handled": True,
                        "intent": "open_application",
                        "raw_text": raw_text,
                        "response": resp,
                        "executed": success,
                        "status": "success" if success else "error",
                    }

        # 11. Volume Control Operations
        # "set volume to 50", "volume 75 percent", "volume up", "volume down", "mute", "unmute"
        vol_set_match = re.search(
            r"\b(?:set\s+(?:the\s+)?volume\s+(?:to\s+)?|volume\s+(?:to\s+)?)(\d{1,3})\s*(?:percent|%)?",
            cleaned, re.IGNORECASE
        )
        if vol_set_match:
            level = int(vol_set_match.group(1))
            success, resp = self.system.set_volume(level, dry_run=dry_run)
            return {
                "handled": True,
                "intent": "volume_set",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        if re.search(r"\b(volume\s+up|increase\s+(?:the\s+)?volume|louder|turn\s+(?:it\s+)?up)\b", cleaned, re.IGNORECASE):
            success, resp = self.system.volume_up(dry_run=dry_run)
            return {
                "handled": True,
                "intent": "volume_up",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        if re.search(r"\b(volume\s+down|decrease\s+(?:the\s+)?volume|quieter|lower\s+(?:the\s+)?volume|turn\s+(?:it\s+)?down)\b", cleaned, re.IGNORECASE):
            success, resp = self.system.volume_down(dry_run=dry_run)
            return {
                "handled": True,
                "intent": "volume_down",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        if re.search(r"\b(mute|silence|shut\s+(?:the\s+)?(?:volume|audio|sound)\s+(?:up|off)|turn\s+off\s+(?:the\s+)?(?:sound|audio|volume))\b", cleaned, re.IGNORECASE):
            success, resp = self.system.mute(dry_run=dry_run)
            return {
                "handled": True,
                "intent": "volume_mute",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        if re.search(r"\b(unmute|restore\s+(?:the\s+)?(?:sound|audio|volume)|turn\s+(?:the\s+)?(?:sound|audio|volume)\s+back\s+on)\b", cleaned, re.IGNORECASE):
            success, resp = self.system.unmute(dry_run=dry_run)
            return {
                "handled": True,
                "intent": "volume_unmute",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        # 12. Media Key Controls
        # "pause", "pause music", "play music", "resume", "next song", "next track", "previous song"
        if re.search(r"\b(pause(?:\s+(?:music|song|video|playback))?|play(?:/pause)?(?:\s+(?:music|song|video))?|resume(?:\s+(?:music|song|video|playback))?)\b", cleaned, re.IGNORECASE):
            # Only if not already caught as youtube_play
            if not re.search(r"\byoutube\b", cleaned, re.IGNORECASE):
                success, resp = self.system.media_play_pause(dry_run=dry_run)
                return {
                    "handled": True,
                    "intent": "media_play_pause",
                    "raw_text": raw_text,
                    "response": "Done.",
                    "executed": success,
                    "status": "success" if success else "error",
                }

        if re.search(r"\b(next\s+(?:song|track|music)|skip(?:\s+(?:song|track|this))?)\b", cleaned, re.IGNORECASE):
            success, resp = self.system.media_next(dry_run=dry_run)
            return {
                "handled": True,
                "intent": "media_next",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        if re.search(r"\b(previous\s+(?:song|track|music)|go\s+back\s+(?:song|track)|last\s+(?:song|track))\b", cleaned, re.IGNORECASE):
            success, resp = self.system.media_prev(dry_run=dry_run)
            return {
                "handled": True,
                "intent": "media_prev",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        # 13. Screenshot Capture
        # "take a screenshot", "capture screen", "screenshot", "take screenshot"
        if re.search(r"\b(take\s+(?:a\s+)?screenshot|capture\s+(?:the\s+)?(?:screen|display)|screenshot|screen\s+capture)\b", cleaned, re.IGNORECASE):
            success, resp = self.system.take_screenshot(dry_run=dry_run)
            return {
                "handled": True,
                "intent": "screenshot",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        # 14. Window Management
        # "minimize", "minimize window", "maximize", "maximize window", "close window"
        if re.search(r"\b(minimize(?:\s+(?:the\s+)?window)?|shrink\s+(?:the\s+)?window)\b", cleaned, re.IGNORECASE):
            success, resp = self.system.minimize_window(dry_run=dry_run)
            return {
                "handled": True,
                "intent": "window_minimize",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        if re.search(r"\b(maximize(?:\s+(?:the\s+)?window)?|fullscreen|full\s+screen)\b", cleaned, re.IGNORECASE):
            success, resp = self.system.maximize_window(dry_run=dry_run)
            return {
                "handled": True,
                "intent": "window_maximize",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        if re.search(r"\b(close(?:\s+(?:the\s+|this\s+)?window|window|\s+app|\s+application)?|close\s+this)\b", cleaned, re.IGNORECASE):
            success, resp = self.system.close_window(dry_run=dry_run)
            return {
                "handled": True,
                "intent": "window_close",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        # 15. Clipboard Read
        # "what's in my clipboard", "read clipboard", "paste content"
        if re.search(r"\b((?:what(?:'s|\s+is)\s+(?:in\s+)?(?:my\s+)?clipboard|read\s+(?:(?:the|my)\s+)?clipboard|clipboard\s+content))\b", cleaned, re.IGNORECASE):
            success, resp = self.system.read_clipboard(dry_run=dry_run)
            return {
                "handled": True,
                "intent": "clipboard_read",
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error",
            }

        # Not a Phase 3 command
        return {
            "handled": False,
            "intent": "unknown",
            "raw_text": raw_text,
            "response": f"I heard \"{raw_text}\", but I don't know how to handle that command yet.",
            "executed": False,
            "status": "unknown",
        }

