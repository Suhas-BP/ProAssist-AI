"""
Command Router Module for ProAssist AI Phase 2
Interprets transcribed speech commands and executes safe, predefined local actions:
- "what time is it"
- "what is today's date"
- "open calculator"
- "open notepad"
- "can you hear me" / system queries
- "stop" / "go to sleep" / "that's all" / "exit"
Safely rejects unknown commands without executing unauthorized system operations.
"""

import re
import socket
import subprocess
from datetime import datetime
from phase2.email.contact_manager import ContactManager
from phase2.email.email_parser import EmailParser


def is_internet_available(timeout: float = 1.5) -> bool:
    """Checks if an active internet connection is available via fast DNS socket test."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(("8.8.8.8", 53))
        sock.close()
        return True
    except OSError:
        return False


class CommandRouter:
    """Routes voice commands to safe local handlers."""

    def __init__(self, contact_manager: ContactManager = None):
        self.email_parser = EmailParser()
        self.contact_manager = contact_manager or ContactManager()
        self._rag_pipeline = None
        self._intent_engine = None
        self._response_manager = None
        try:
            from phase3.phase3_router import Phase3Router
            self.phase3_router = Phase3Router()
        except Exception:
            self.phase3_router = None

        try:
            from llm.online_llm import OnlineLLMQA
            self.online_llm = OnlineLLMQA()
        except Exception as e:
            print(f"[CommandRouter] Online LLM initialization note: {e}")
            self.online_llm = None


        # Intent matching patterns
        self.rag_patterns = [
            r"\b(check|read|inspect|review|look\s+at|view|test)\s+(?:the\s+)?(?:file|files|document|documents|report|paper|knowledge\s+base)\b",
            r"\b(check|read|inspect|open\s+and\s+read|review|look\s+at|test)\s+(?:the\s+)?([a-zA-Z0-9_\-\s]+?)\s*(?:file|document|pdf|report|application)?\b",
            r"\b(what\s+does\s+the\s+(?:file|document|report)|what\s+is\s+in\s+the\s+(?:file|document|report)|what\s+is\s+written\s+in\s+the\s+(?:file|document|report))\b",
            r"\b(summarize|summary\s+of|explain|describe)\s+(?:the\s+)?(?:pdf|pdfs|file|files|document|documents|report|paper|knowledge\s+base)\b",
            r"\b(summarize|summary\s+of|test)\s+(?:the\s+)?(.+?)\s*(?:pdf|document|file|report|application)?\b",
            r"\b(according\s+to|from|in)\s+(the\s+)?(file|files|document|documents|project|guide|notes|paper|manual|report)\b",
            r"\bsearch\s+(the\s+)?(file|files|document|documents|report|knowledge\s+base)\b",
            r"\b(who\s+submitted|who\s+are\s+the\s+students|who\s+is\s+the\s+guide|who\s+guided|project\s+title|project\s+report|what\s+is\s+the\s+abstract|major\s+project|project\s+phase|project\s+objective)\b",
            r"\b(tell me about|explain|summarize|what is|what are)\b.*\b(the file|the document|the project|proassist|rag|biometric security|speaker embedding|voiceprint|knowledge base|architecture|abstract)\b",
        ]

        self.time_patterns = [
            r"\b(what\s+time\s+is\s+it|what\s+is\s+the\s+time|tell\s+me\s+the\s+time|current\s+time|what\s+time|the\s+time)\b"
        ]
        self.date_patterns = [
            r"\b(what\s+is\s+todays?\s+date|what\s+is\s+the\s+date|tell\s+me\s+the\s+date|todays?\s+date|what\s+day\s+is\s+it|what\s+is\s+today|current\s+date)\b"
        ]
        self.calc_patterns = [
            r"\b(open\s+calculator|launch\s+calculator|start\s+calculator|run\s+calculator|calculator|calc)\b"
        ]
        self.notepad_patterns = [
            r"\b(open\s+notepad|launch\s+notepad|start\s+notepad|run\s+notepad|notepad)\b"
        ]
        self.hear_patterns = [
            r"\b(can\s+you\s+hear\s+me|do\s+you\s+hear\s+me|are\s+you\s+listening|can\s+you\s+hear|agent|hey\s+agent)\b"
        ]
        self.greeting_patterns = [
            r"\b(hello|hi|hey|good\s+morning|good\s+afternoon|good\s+evening)\b"
        ]
        self.identity_patterns = [
            r"\b(who\s+are\s+you|what\s+are\s+you|what\s+is\s+your\s+name)\b"
        ]
        self.exit_patterns = [
            r"\b(stop|go\s+to\s+sleep|that\s+(is\s+)?all|thats?\s+all|exit|bye|goodbye|quit|cancel|no\s+thanks|no\s+thank\s+you|nothing|nevermind|never\s+mind)\b"
        ]
        self.thank_you_patterns = [
            r"\b(thank\s+you|thanks|thank\s+u|thx)\b"
        ]

    @property
    def intent_engine(self):
        """Lazy-loaded multilingual intent engine."""
        if self._intent_engine is None:
            try:
                from multilingual.intent_engine import MultilingualIntentEngine
                self._intent_engine = MultilingualIntentEngine()
            except Exception as e:
                print(f"[CommandRouter] Multilingual intent engine unavailable: {e}")
                self._intent_engine = None
        return self._intent_engine

    @property
    def response_manager(self):
        """Lazy-loaded multilingual response manager."""
        if self._response_manager is None:
            try:
                from multilingual.response_manager import MultilingualResponseManager
                self._response_manager = MultilingualResponseManager(enable_tts=False)
            except Exception as e:
                print(f"[CommandRouter] Multilingual response manager unavailable: {e}")
                self._response_manager = None
        return self._response_manager

    @property
    def rag_pipeline(self):
        """Lazy-loaded RAG pipeline instance."""
        if self._rag_pipeline is None:
            try:
                from rag.pipeline import RAGPipeline
                self._rag_pipeline = RAGPipeline()
            except Exception as e:
                print(f"[CommandRouter] Local RAG pipeline unavailable: {e}")
                self._rag_pipeline = None
        return self._rag_pipeline


    def _normalize(self, text: str) -> str:
        """Lowercases, expands common contractions, strips polite conversational prefixes and trailing phrases, and cleans punctuation."""
        t = text.lower().strip()
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
            (r"\bopen\s+up\b", "open"),
            (r"\byou\s+tube\b", "youtube"),
            (r"\byoutube\.com\b", "youtube"),
            (r"\bgoogle\.com\b", "google"),
            (r"\bgmail\.com\b", "gmail"),
            (r"\b(?:can\s+you\s+)?(?:open|launch)\s+(?:not\s+bad|note\s+better|one\s+note\s+better|the\s+bag|a\s+bag)\b", "open notepad"),
            (r"\b(?:not\s+bad|note\s+better|one\s+note\s+better|the\s+bag)\b", "notepad"),
            (r"\b(?:pondow|pando|pandoo)\s+youtube\b", "open youtube"),
            (r"\b(?:pondow|pando|pandoo)\b", "open"),
        ]
        for pat, repl in replacements:
            t = re.sub(pat, repl, t)

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
                new_t = re.sub(p, "", t).strip()
                if new_t != t:
                    t = new_t
                    changed = True
            for tr in trailing:
                new_t = re.sub(tr, "", t).strip()
                if new_t != t:
                    t = new_t
                    changed = True

        clean = re.sub(r"[^\w\s\u0900-\u097F\u0C80-\u0CFF]", " ", t)
        return " ".join(clean.split())

    @staticmethod
    def _clean_search_query(q: str) -> str:
        """Strips conversational noise and target site qualifiers from search query."""
        if not q:
            return ""
        clean = q.strip()
        patterns_to_strip = [
            r"\s+(?:on|in|using|via|through)\s+(?:youtube|google|chrome|edge|firefox|browser|the\s+browser|the\s+web|the\s+internet)$",
            r"\s+(?:in|on)\s+(?:google\s+chrome|ms\s+edge|the\s+web)$",
            r"\s+(?:on\s+the\s+browser|in\s+the\s+browser|on\s+browser|in\s+browser)$",
            r"\s+(?:for\s+me|please|for\s+me\s+please)$",
            r"^(?:for|about|of)\s+",
        ]
        changed = True
        while changed:
            changed = False
            for pat in patterns_to_strip:
                new_c = re.sub(pat, "", clean, flags=re.IGNORECASE).strip()
                if new_c != clean and new_c:
                    clean = new_c
                    changed = True
        return clean.strip("\"' ")

    def parse_structured_intent(self, normalized_text: str, raw_text: str):
        """
        Parses structured intent and extracts entity from normalized text.
        Returns:
            (internal_intent, display_intent, entity, target)
        """
        t_lower = normalized_text.lower()
        r_lower = raw_text.lower()

        # 1. Exit Commands
        for pat in self.exit_patterns:
            if re.search(pat, t_lower) or re.search(pat, r_lower):
                return "exit", "EXIT", None, None

        # 2. Conversational / System Checks
        for pat in self.hear_patterns:
            if re.search(pat, r_lower) or re.search(pat, t_lower):
                return "can_you_hear_me", "CAN_YOU_HEAR_ME", None, None

        for pat in self.identity_patterns:
            if re.search(pat, t_lower):
                return "who_are_you", "WHO_ARE_YOU", None, None

        for pat in self.thank_you_patterns:
            if re.search(pat, t_lower):
                return "thank_you", "THANK_YOU", None, None

        # 3. Time and Date
        for pat in self.time_patterns:
            if re.search(pat, t_lower):
                return "get_time", "GET_TIME", None, None

        for pat in self.date_patterns:
            if re.search(pat, t_lower):
                return "get_date", "GET_DATE", None, None

        # 4. YouTube Play
        m_yt_play_explicit = re.search(r"\b(?:open\s+youtube\s+(?:and\s+)?(?:play|to\s+play)|open\s+and\s+play\s+(.+?)\s+on\s+youtube)\s*(.*)", t_lower)
        if m_yt_play_explicit:
            q = (m_yt_play_explicit.group(1) or m_yt_play_explicit.group(2)).strip()
            q = self._clean_search_query(q)
            if q:
                return "youtube_play", "YOUTUBE_PLAY", q, q

        m_yt_play = re.search(r"\bplay\s+(.+?)(?:\s+(?:on|in)\s+youtube)?$", t_lower)
        if m_yt_play and ("youtube" in t_lower or t_lower.startswith("play ")):
            q = m_yt_play.group(1).strip()
            q = self._clean_search_query(q)
            if q and q != "the first result":
                return "youtube_play", "YOUTUBE_PLAY", q, q
            elif q == "the first result":
                return "youtube_play", "YOUTUBE_PLAY", "the first result", "the first result"

        # 5. YouTube Search (Comprehensive sentence analysis)
        if "youtube" in t_lower:
            mA = re.search(r"\b(?:open|go\s+to|visit|launch)\s+youtube\s+(?:and\s+)?(?:search|to\s+search|find|look\s+up)(?:\s+for)?\s+(.+)", t_lower)
            mB = re.search(r"\b(?:search|find|look\s+up)\s+(?:for\s+)?(.+?)\s+(?:on|in|using|via|through)\s+youtube\b", t_lower)
            mC = re.search(r"\b(?:search|find|look\s+up)\s+(?:on|in)\s+youtube\s+(?:for\s+)?(.+)", t_lower)
            mD = re.search(r"\b(?:search|find)\s+youtube\s+(?:for\s+)?(.+)", t_lower)
            mE = re.search(r"\byoutube\s+search\s+(?:for\s+)?(.+)", t_lower)
            mF = re.search(r"\bopen\s+youtube\s+search\s+(?:for\s+)?(.+)", t_lower)

            candidate_yt = mA or mB or mC or mD or mE or mF
            if candidate_yt:
                raw_q = candidate_yt.group(1).strip()
                clean_q = self._clean_search_query(raw_q)
                if clean_q:
                    return "youtube_search", "YOUTUBE_SEARCH", clean_q, clean_q

        # 6. Google / Web Search (Comprehensive sentence analysis)
        if any(k in t_lower for k in ["google", "search", "web", "internet", "look up", "find"]):
            mGA = re.search(r"\bopen\s+(?:chrome|browser|google)\s+and\s+(?:search\s+google\s+for|search\s+for|google\s+search|search)\s+(.+)", t_lower)
            mGB = re.search(r"\b(?:go\s+to|visit)\s+google\s+and\s+search(?:\s+for)?\s+(.+)", t_lower)
            mGC = re.search(r"\b(?:search|find|look\s+up)\s+(?:for\s+)?(.+?)\s+(?:on|in|using|via)\s+google\b", t_lower)
            mGD = re.search(r"\b(?:search|find|look\s+up)\s+(?:on|in)\s+google\s+(?:for\s+)?(.+)", t_lower)
            mGE = re.search(r"\bsearch\s+google\s+(?:for\s+)?(.+)", t_lower)
            mGF = re.search(r"\bgoogle\s+search\s+(?:for\s+)?(.+)", t_lower)
            mGG = re.search(r"\bsearch\s+(?:the\s+)?(?:web|internet)\s+(?:for\s+)?(.+)", t_lower)
            mGH = re.search(r"\blook\s+up\s+(.+?)(?:\s+(?:on|in)\s+google|\s+on\s+the\s+web|\s+online)?$", t_lower)
            mGI = None
            if re.search(r"\bsearch\s+for\s+(.+)", t_lower) and not any(k in t_lower for k in ["file", "document", "notepad", "calculator"]):
                mGI = re.search(r"\bsearch\s+for\s+(.+)", t_lower)

            candidate_g = mGA or mGB or mGC or mGD or mGE or mGF or mGG or mGH or mGI
            if candidate_g:
                raw_gq = candidate_g.group(1).strip()
                clean_gq = self._clean_search_query(raw_gq)
                if clean_gq and clean_gq != "google":
                    return "google_search", "GOOGLE_SEARCH", clean_gq, clean_gq

        # 8. Math / Calculator Operations
        if re.search(r"\b(calculate|solve|evaluate)\b", t_lower) or (re.search(r"\bwhat\s+is\s+\d+", t_lower) and any(op in t_lower for op in ["plus", "minus", "times", "multiplied", "divided", "percent", "%", "power", "+", "-", "*", "/"])):
            expr = re.sub(r"^(?:calculate|solve|evaluate|what\s+is)\s+", "", t_lower).strip()
            return "calculate", "CALCULATOR", expr, expr

        # Multi-step: "open notepad and write/type <text>"
        m_open_write = re.search(r"\bopen\s+notepad\s+and\s+(?:write|type)\s+(?:down\s+)?(.+)$", t_lower)
        if m_open_write:
            text_to_type = m_open_write.group(1).strip().strip('"\'')
            return "type_in_notepad", "TYPE_IN_NOTEPAD", text_to_type, text_to_type

        # "write in notepad <text>" or "type in notepad <text>"
        m_write_in = re.search(r"\b(?:write|type|note\s+down)\s+(?:in|into|on)\s+notepad\s+(.+)$", t_lower)
        if m_write_in:
            text_to_type = m_write_in.group(1).strip().strip('"\'')
            return "type_in_notepad", "TYPE_IN_NOTEPAD", text_to_type, text_to_type

        # 9. Notepad Typing: "write <text> in notepad" or "type <text> in notepad"
        m_type = re.search(r"(?:type|write|note\s+down)\s+(?:\"([^\"]+)\"|'([^']+)'|(.+?))(?:\s+in\s+notepad|\s+into\s+notepad|\s+on\s+notepad)$", t_lower)
        if m_type:
            text_to_type = (m_type.group(1) or m_type.group(2) or m_type.group(3)).strip().strip('"\'')
            return "type_in_notepad", "TYPE_IN_NOTEPAD", text_to_type, text_to_type

        # 9.5 Specific File Opening (PDFs, Documents, bus pass, etc.)
        if re.search(r"\bopen\s+(?:a\s+|the\s+)?file\s+(?:from|in)\s+(?:the\s+)?file\s+explorer\b", t_lower) and not any(k in t_lower for k in ["bus pass", "student", "project", "review", ".pdf", ".docx", ".txt"]):
            return "open_folder", "OPEN_FOLDER", "File Explorer", "explorer"

        m_open_file = re.search(r"\b(?:open|launch|show|view)\s+(?:the\s+|a\s+)?(?:file|pdf|document)?\s*(bus\s+pass\s+application|student\s+bus\s+pass|bus\s+pass|major\s+project\s+document|literature\s+review|[a-zA-Z0-9_\-\s]+?\.(?:pdf|docx|txt|md))\b", t_lower)
        if not m_open_file and not re.search(r"\bopen\s+(?:the\s+|my\s+)?(?:file\s+explorer|explorer)\b", t_lower):
            m_open_file = re.search(r"\bopen\s+(?:the\s+|a\s+)?(?:file|pdf|document)\s+(?:from\s+(?:the\s+)?file\s+explorer\s+)?(?!explorer\b)(.+)", t_lower)
        if m_open_file:
            f_target = m_open_file.group(1).strip()
            return "open_file", "OPEN_FILE", f_target, f_target

        # 10. Allowed Application Launching (Chrome, Calculator, Notepad, Edge, Firefox, Explorer, Browser)
        m_app = re.search(r"\b(?:open|launch|start|run)\s+(?:the\s+|my\s+)?(google\s+chrome|chrome|calculator|calc|notepad|note\s+pad|edge|microsoft\s+edge|firefox|browser|file\s+explorer|explorer)(?:\s+browser|\s+app)?\b", t_lower)
        if m_app:
            a_raw = m_app.group(1).strip()
            if a_raw in ["chrome", "google chrome"]:
                return "open_application", "OPEN_APPLICATION", "chrome", "chrome"
            elif a_raw in ["calculator", "calc"]:
                return "open_calculator", "OPEN_APPLICATION", "calculator", "calculator"
            elif a_raw in ["notepad", "note pad"]:
                return "open_notepad", "OPEN_APPLICATION", "notepad", "notepad"
            elif a_raw in ["edge", "microsoft edge"]:
                return "open_application", "OPEN_APPLICATION", "edge", "edge"
            elif a_raw in ["firefox"]:
                return "open_application", "OPEN_APPLICATION", "firefox", "firefox"
            elif a_raw in ["explorer", "file explorer"]:
                return "open_application", "OPEN_APPLICATION", "explorer", "explorer"
            elif a_raw in ["browser"]:
                return "open_application", "OPEN_APPLICATION", "browser", "browser"

        for pat in self.calc_patterns:
            if re.search(pat, t_lower):
                return "open_calculator", "OPEN_APPLICATION", "calculator", "calculator"

        for pat in self.notepad_patterns:
            if re.search(pat, t_lower):
                return "open_notepad", "OPEN_APPLICATION", "notepad", "notepad"

        # 11. Folder Navigation
        m_folder = re.search(r"\b(?:open|launch|show)\s+(?:the\s+|my\s+)?(downloads|documents|desktop|file\s+explorer|explorer)(?:\s+folder)?\b", t_lower)
        if m_folder:
            f_raw = m_folder.group(1).strip()
            name_map = {
                "downloads": "Downloads",
                "documents": "Documents",
                "desktop": "Desktop",
                "file explorer": "File Explorer",
                "explorer": "File Explorer",
            }
            return "open_folder", "OPEN_FOLDER", name_map.get(f_raw, f_raw.capitalize()), f_raw.replace("file explorer", "explorer")

        # 12. Allowed Website Opening (Gmail, YouTube, Google, GitHub)
        if not any(k in t_lower for k in ["search", "play", "find", "look up"]):
            m_site = re.search(r"\b(?:open|launch|start|visit|go\s+to|check)?\s*(?:up\s+)?(?:my\s+|the\s+)?(gmail|google\s+mail|youtube|google(?!\s+chrome)|github)(?:\s+(?:website|site|app|application|page))?(?:\.com)?\b", t_lower)
            if m_site:
                s_raw = m_site.group(1).strip()
                if s_raw in ["gmail", "google mail"]:
                    return "open_website", "OPEN_WEBSITE", "Gmail", "gmail"
                elif s_raw == "youtube":
                    return "open_website", "OPEN_WEBSITE", "YouTube", "youtube"
                elif s_raw == "google":
                    return "open_website", "OPEN_WEBSITE", "Google", "google"
                elif s_raw == "github":
                    return "open_website", "OPEN_WEBSITE", "GitHub", "github"

        # 12.5 Dynamic Laptop Application Launching (Word, Excel, PowerPoint, Camera, Settings, Paint, Cursor, etc.)
        m_dynamic_app = re.search(r"\b(?:open|launch|start|run)\s+(?:the\s+|my\s+)?([a-zA-Z0-9\s_\-\.]{2,35}?)(?:\s+(?:app|application|software|program))?$", t_lower)
        if m_dynamic_app:
            cand_name = m_dynamic_app.group(1).strip()
            if cand_name and not any(k in cand_name for k in ["file", "document", "pdf", "youtube", "google", "gmail", "github", "search", "something"]):
                if getattr(self, "phase3_router", None) is not None:
                    sys_app = self.phase3_router.launcher.find_system_app(cand_name)
                    if sys_app:
                        disp_name = sys_app.get("display_name", sys_app.get("name", cand_name.capitalize()))
                        return "open_application", "OPEN_APPLICATION", disp_name, cand_name

        # 13. Greetings
        for pat in self.greeting_patterns:
            if re.search(pat, t_lower):
                return "greeting", "GREETING", None, None

        # 14. Email Commands
        email_res = self.email_parser.parse_command(normalized_text)
        if email_res["is_email"]:
            recip = email_res.get("recipient_name")
            return "email_compose", "EMAIL_COMPOSE", recip, None

        # 14. Document / PDF Summarization (File Explorer, Desktop, data/knowledge)
        m_sum_file = re.search(
            r"\b(?:summarize|summary\s+of|give\s+(?:me\s+)?(?:a\s+)?summary\s+of|brief\s+me\s+on)\s+(?:the\s+)?(?:pdf|pdfs|file|files|document|documents|report|application)?(?:\s+(?:that\s+)?exists\s+in\s+(?:the\s+)?file\s+explorer|\s+in\s+(?:the\s+)?(?:file\s+explorer|desktop|downloads))?\s*(.*)",
            t_lower
        )
        if not m_sum_file:
            m_sum_file = re.search(
                r"\b(?:check|read|inspect|what\s+is\s+in)\s+(?:the\s+)?(?:pdf|pdfs|file|files|document|documents|report|application)(?:\s+(?:that\s+)?exists\s+in\s+(?:the\s+)?file\s+explorer|\s+in\s+(?:the\s+)?(?:file\s+explorer|desktop|downloads))?\s*(.*)",
                t_lower
            )
        if m_sum_file:
            target_doc = m_sum_file.group(1).strip() if m_sum_file.group(1) else None
            # Clean filler trailing/leading words if any
            if target_doc:
                target_doc = re.sub(r"^(?:that\s+exists\s+in\s+(?:the\s+)?file\s+explorer|in\s+(?:the\s+)?file\s+explorer)\s*", "", target_doc).strip()
            target_doc = target_doc if target_doc else None
            return "summarize_document", "SUMMARIZE_DOCUMENT", target_doc, target_doc

        # 15. RAG / Knowledge Base / Document Queries
        m_check_file = re.search(r"\b(?:check|read|inspect|open\s+and\s+read|review|look\s+at|test)\s+(?:the\s+)?(?:file|files|document|documents|report|paper|application)(?:\s+(.+))?", t_lower)
        if m_check_file:
            fname = (m_check_file.group(1) or "document summary").strip()
            return "rag_query", "RAG_QUERY", fname, fname

        for pat in self.rag_patterns:
            if re.search(pat, t_lower):
                return "rag_query", "RAG_QUERY", normalized_text, normalized_text

        if re.search(r"\b(file|files|document|documents|report|paper|architecture|phase\s+\d|proassist|project|guide|manual|biometric|embedding|voiceprint|knowledge\s+base|abstract|methodology|objective)\b", t_lower) and \
           re.search(r"\b(what|tell\s+me|explain|summarize|how|who|where|why|check|read|inspect)\b", t_lower):
            topic = re.sub(r"^(?:what\s+is|what\s+are|tell\s+me\s+about|explain|summarize|check|read)\s+", "", t_lower).strip()
            return "rag_query", "RAG_QUERY", topic, topic

        # 15. Check Phase 3 Router
        if getattr(self, "phase3_router", None) is not None:
            p3_res = self.phase3_router.execute(normalized_text, dry_run=True)
            if p3_res.get("handled"):
                p3_intent = p3_res.get("intent", "phase3_action")
                return p3_intent, p3_intent.upper(), None, None

        # 16. General Knowledge & Online LLM Questions (Math, Current Events, Facts)
        # e.g. "what is the sum of 2+2", "who is the prime minister of uk", "what is the capital of france"
        if re.search(r"\b(sum\s+of\s+-?\d+|what\s+is\s+-?\d+\s*[\+\-\*\/])", t_lower) or \
           (re.match(r"^(who|what|where|when|why|how|tell me|explain)\b", t_lower) and not any(k in t_lower for k in ["time", "date", "file", "folder", "notepad", "calculator", "chrome", "edge", "firefox", "browser", "youtube", "clipboard", "screenshot", "volume", "sound", "window"])):
            return "general_question", "GENERAL_QUESTION", normalized_text, raw_text

        return "unknown", "UNKNOWN", None, None


    def match_intent(self, normalized_text: str) -> str:
        """Determines internal intent from normalized text."""
        internal_intent, _, _, _ = self.parse_structured_intent(normalized_text, normalized_text)
        return internal_intent

    def launch_application(self, app_key: str, dry_run: bool = False) -> tuple[bool, str]:
        """Safely launches an allowlisted application via AppLauncher."""
        if getattr(self, "phase3_router", None) is not None:
            return self.phase3_router.launcher.launch(app_key, dry_run=dry_run)
        try:
            from phase3.app_launcher import launch_application as p3_launch
            return p3_launch(app_key, dry_run=dry_run)
        except Exception as e:
            print(f"[CommandRouter ERROR] Failed to launch {app_key}: {e}")
            return False, f"I couldn't open {app_key}."

    def execute(self, command_text: str, dry_run: bool = False, _from_multilingual: bool = False) -> dict:
        """
        Interprets and executes the command.
        dry_run: When True, simulates action without launching GUI applications.
        Returns:
            dict containing intent, response message, executed status, and success state.
        """
        raw_text = command_text.strip()
        if not raw_text:
            return {
                "intent": "empty",
                "raw_text": "",
                "response": "I didn't catch that. Could you please repeat?",
                "executed": False,
                "status": "empty"
            }

        # Multilingual Intent Understanding (Phase 5: English, Hindi, Kannada)
        if not _from_multilingual and self.intent_engine is not None:
            parsed = self.intent_engine.parse_intent(raw_text)
            lang = parsed.get("language", "en")
            if lang in ["hi", "kn"]:
                lang_name = "Hindi" if lang == "hi" else "Kannada"
                print(f"[Language] Detected: {lang_name}")
                print(f"[Intent] Type: {parsed.get('intent')}{' | Target: ' + parsed.get('target') if parsed.get('target') else ''}")
                canonical = parsed.get("canonical_command", raw_text)
                try:
                    print(f"[Router] Canonical Command: \"{canonical}\"")
                except UnicodeEncodeError:
                    safe_c = canonical.encode("ascii", "backslashreplace").decode("ascii")
                    print(f"[Router] Canonical Command: \"{safe_c}\"")

                # If RAG query in Hindi / Kannada
                if parsed.get("intent") == "rag_query":
                    if dry_run:
                        return {
                            "intent": "rag_query",
                            "raw_text": raw_text,
                            "response": f"[Knowledge Base - {lang_name}] Verified retrieval response for '{raw_text}'.",
                            "executed": True,
                            "status": "success",
                            "sources": ["proassist_major_project.md, page 1"],
                            "language": lang,
                            "original_intent": "rag_query"
                        }

                    if self.rag_pipeline is not None:
                        try:
                            rag_res = self.rag_pipeline.ask(raw_text)
                            return {
                                "intent": "rag_query",
                                "raw_text": raw_text,
                                "response": rag_res.get("answer", ""),
                                "executed": True,
                                "status": "success",
                                "sources": rag_res.get("sources", []),
                                "rag_data": rag_res,
                                "language": lang,
                                "original_intent": "rag_query"
                            }
                        except Exception as e:
                            print(f"[CommandRouter] Multilingual RAG error: {e}")
                            return {
                                "intent": "rag_query",
                                "raw_text": raw_text,
                                "response": "I encountered an error querying the local knowledge base.",
                                "executed": False,
                                "status": "error",
                                "language": lang,
                                "original_intent": "rag_query"
                            }
                    else:
                        return {
                            "intent": "rag_query",
                            "raw_text": raw_text,
                            "response": "The local knowledge base module is currently unavailable.",
                            "executed": False,
                            "status": "unavailable",
                            "language": lang,
                            "original_intent": "rag_query"
                        }

                # Execute canonical command using existing centralized execution engine
                res = self.execute(canonical, dry_run=dry_run, _from_multilingual=True)

                # Localize response if available
                if self.response_manager is not None:
                    loc_resp = self.response_manager.localize(
                        parsed.get("intent", res.get("intent", "unknown")),
                        lang,
                        context=parsed,
                        default_en=res.get("response", "")
                    )
                    res["response"] = loc_resp

                res["language"] = lang
                res["original_intent"] = parsed.get("intent")
                return res

        norm_text = self._normalize(raw_text)
        intent, display_intent, entity, target = self.parse_structured_intent(norm_text, raw_text)

        # Determine selected action description for debug logging
        if intent == "open_application":
            selected_action = f'launch_application("{target or entity or "chrome"}")'
        elif intent == "open_calculator":
            selected_action = f'launch_application("{target or "calculator"}")'
        elif intent == "open_notepad":
            selected_action = f'launch_application("{target or "notepad"}")'
        elif intent == "open_website":
            selected_action = f'open_website("{target or entity}")'
        elif intent == "google_search":
            selected_action = f'search_google("{entity}")'
        elif intent == "youtube_search":
            selected_action = f'search_youtube("{entity}")'
        elif intent == "youtube_play":
            selected_action = f'play_youtube("{entity}")'
        elif intent == "calculate":
            selected_action = f'calculate("{entity}")'
        elif intent == "type_in_notepad":
            selected_action = f'type_in_notepad("{entity}")'
        elif intent == "open_folder":
            selected_action = f'open_folder("{target or entity}")'
        elif intent == "open_file":
            selected_action = f'open_file("{target or entity}")'
        elif intent == "email_compose":
            selected_action = f'email_compose("{entity}")'
        elif intent == "rag_query":
            selected_action = f'rag_query("{entity}")'
        elif intent == "general_question":
            selected_action = f'online_llm("{raw_text}")'
        elif intent in ["get_time", "get_date", "exit", "can_you_hear_me", "who_are_you", "greeting"]:
            selected_action = f'{intent}()'
        else:
            selected_action = "none"


        try:
            print(f'[CommandRouter] Raw transcript: "{raw_text}"')
            print(f'[CommandRouter] Normalized transcript: "{norm_text}"')
            print(f"[CommandRouter] Intent: {display_intent}")
            if entity:
                print(f"[CommandRouter] Entity: {entity}")
            if selected_action != "none":
                print(f"[CommandRouter] Selected action: {selected_action}")
                print("[CommandRouter] Executing action...")
        except UnicodeEncodeError:
            safe_text = raw_text.encode("ascii", "backslashreplace").decode("ascii")
            safe_norm = norm_text.encode("ascii", "backslashreplace").decode("ascii")
            print(f'[CommandRouter] Raw transcript: "{safe_text}"')
            print(f'[CommandRouter] Normalized transcript: "{safe_norm}"')
            print(f"[CommandRouter] Intent: {display_intent}")
            if entity:
                safe_entity = str(entity).encode("ascii", "backslashreplace").decode("ascii")
                print(f"[CommandRouter] Entity: {safe_entity}")
            if selected_action != "none":
                safe_action = str(selected_action).encode("ascii", "backslashreplace").decode("ascii")
                print(f"[CommandRouter] Selected action: {safe_action}")
                print("[CommandRouter] Executing action...")

        if intent not in ["unknown", "empty", "open_calculator", "open_notepad", "open_application"]:
            print(f"[CommandRouter] Executing: {intent}")

        if intent == "exit":
            response = "Going back to wake-word listening."
            res = {
                "intent": intent,
                "raw_text": raw_text,
                "response": response,
                "executed": True,
                "status": "exit"
            }

        elif intent == "language_switch":
            lang_code = entity or "en"
            if self.intent_engine and hasattr(self.intent_engine, "detector"):
                self.intent_engine.detector.current_language = lang_code
            if self.response_manager is not None:
                resp = self.response_manager.localize("language_switch", lang_code)
            else:
                resp = f"Switched language to {lang_code}."
            res = {
                "intent": intent,
                "raw_text": raw_text,
                "response": resp,
                "executed": True,
                "status": "success",
                "language": lang_code,
            }

        elif intent == "can_you_hear_me":
            response = "Yes, I can hear you clearly."
            res = {
                "intent": intent,
                "raw_text": raw_text,
                "response": response,
                "executed": True,
                "status": "success"
            }

        elif intent == "thank_you":
            response = "You're welcome! Let me know if you need anything else."
            res = {
                "intent": intent,
                "raw_text": raw_text,
                "response": response,
                "executed": True,
                "status": "success"
            }

        elif intent == "who_are_you":
            response = "I am ProAssist, your universal intelligent voice assistant."
            res = {
                "intent": intent,
                "raw_text": raw_text,
                "response": response,
                "executed": True,
                "status": "success"
            }

        elif intent == "greeting":
            response = "Hello! How can I help you?"
            res = {
                "intent": intent,
                "raw_text": raw_text,
                "response": response,
                "executed": True,
                "status": "success"
            }

        elif intent == "get_time":
            now_str = datetime.now().strftime("%I:%M %p")
            response = f"The current time is {now_str}."
            res = {
                "intent": intent,
                "raw_text": raw_text,
                "response": response,
                "executed": True,
                "status": "success"
            }

        elif intent == "get_date":
            today_str = datetime.now().strftime("%A, %B %d, %Y")
            response = f"Today is {today_str}."
            res = {
                "intent": intent,
                "raw_text": raw_text,
                "response": response,
                "executed": True,
                "status": "success"
            }

        elif intent == "open_calculator":
            target = target or "calculator"
            entity = entity or "calculator"
            exec_desc = f'launch_application("{target}")'
            print(f"[CommandRouter] Executing: {exec_desc}")
            success, msg = self.launch_application(target, dry_run=dry_run)
            res = {
                "intent": intent,
                "raw_text": raw_text,
                "response": msg,
                "executed": success,
                "status": "success" if success else "error"
            }

        elif intent == "open_notepad":
            target = target or "notepad"
            entity = entity or "notepad"
            exec_desc = f'launch_application("{target}")'
            print(f"[CommandRouter] Executing: {exec_desc}")
            success, msg = self.launch_application(target, dry_run=dry_run)
            res = {
                "intent": intent,
                "raw_text": raw_text,
                "response": msg,
                "executed": success,
                "status": "success" if success else "error"
            }

        elif intent == "open_application":
            app_target = target or entity or "chrome"
            exec_desc = f'launch_application("{app_target}")'
            print(f"[CommandRouter] Executing: {exec_desc}")
            if app_target == "browser":
                if getattr(self, "phase3_router", None) is not None:
                    success, resp = self.phase3_router.browser.open_browser(dry_run=dry_run)
                else:
                    success, resp = self.launch_application("chrome", dry_run=dry_run)
            else:
                success, resp = self.launch_application(app_target, dry_run=dry_run)
            res = {
                "intent": intent,
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error"
            }

        elif intent == "open_website":
            if getattr(self, "phase3_router", None) is not None:
                success, resp = self.phase3_router.browser.open_website(target or "google", dry_run=dry_run)
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": resp,
                    "executed": success,
                    "status": "success" if success else "error"
                }
            else:
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": f"Opening {entity}.",
                    "executed": True,
                    "status": "success"
                }

        elif intent == "google_search":
            search_query = entity or raw_text
            found_offline = False
            if not dry_run and self.rag_pipeline is not None:
                try:
                    rag_res = self.rag_pipeline.ask(search_query)
                    chunks = rag_res.get("chunks", [])
                    ans = rag_res.get("answer", "")
                    if chunks and len(chunks) > 0 and chunks[0].get("score", 0.0) >= 0.65 and ans and "could not find information" not in ans.lower():
                        found_offline = True
                        res = {
                            "intent": "rag_query",
                            "raw_text": raw_text,
                            "response": f"Found in offline documents: {ans}",
                            "executed": True,
                            "status": "success",
                            "sources": rag_res.get("sources", []),
                            "rag_data": rag_res
                        }
                except Exception as e:
                    print(f"[Offline Search Check] {e}")

            if not found_offline:
                if not dry_run and not is_internet_available():
                    res = {
                        "intent": intent,
                        "raw_text": raw_text,
                        "response": f"'{search_query}' was not found in your offline files, and internet is not available.",
                        "executed": False,
                        "status": "offline_no_internet"
                    }
                elif getattr(self, "phase3_router", None) is not None:
                    success, resp = self.phase3_router.web.search_google(search_query, dry_run=dry_run)
                    res = {
                        "intent": intent,
                        "raw_text": raw_text,
                        "response": resp,
                        "executed": success,
                        "status": "success" if success else "error"
                    }
                else:
                    res = {
                        "intent": intent,
                        "raw_text": raw_text,
                        "response": f"Searching Google for {search_query}.",
                        "executed": True,
                        "status": "success"
                    }

        elif intent == "youtube_search":
            search_query = entity or raw_text
            if not dry_run and not is_internet_available():
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": "Internet is not available to access YouTube.",
                    "executed": False,
                    "status": "offline_no_internet"
                }
            elif getattr(self, "phase3_router", None) is not None:
                success, resp = self.phase3_router.web.search_youtube(search_query, dry_run=dry_run)
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": resp,
                    "executed": success,
                    "status": "success" if success else "error"
                }
            else:
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": f"Searching YouTube for {search_query}.",
                    "executed": True,
                    "status": "success"
                }

        elif intent == "youtube_play":
            if not dry_run and not is_internet_available():
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": "Internet is not available to access YouTube.",
                    "executed": False,
                    "status": "offline_no_internet"
                }
            elif getattr(self, "phase3_router", None) is not None:
                if entity == "the first result":
                    res = {
                        "intent": intent,
                        "raw_text": raw_text,
                        "response": "Playing it.",
                        "executed": True,
                        "status": "success"
                    }
                else:
                    success, resp = self.phase3_router.web.play_youtube(entity or "", dry_run=dry_run)
                    res = {
                        "intent": intent,
                        "raw_text": raw_text,
                        "response": resp,
                        "executed": success,
                        "status": "success" if success else "error"
                    }
            else:
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": f"Playing {entity} on YouTube.",
                    "executed": True,
                    "status": "success"
                }

        elif intent == "calculate":
            if getattr(self, "phase3_router", None) is not None:
                success, resp = self.phase3_router.desktop.calculate(entity or raw_text)
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": resp,
                    "executed": success,
                    "status": "success" if success else "error"
                }
            else:
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": "Calculation module unavailable.",
                    "executed": False,
                    "status": "error"
                }

        elif intent == "type_in_notepad":
            if getattr(self, "phase3_router", None) is not None:
                success, resp = self.phase3_router.desktop.type_in_notepad(entity or "", dry_run=dry_run)
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": resp,
                    "executed": success,
                    "status": "success" if success else "error"
                }
            else:
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": "Notepad typing automation unavailable.",
                    "executed": False,
                    "status": "error"
                }

        elif intent == "open_folder":
            if getattr(self, "phase3_router", None) is not None:
                success, resp = self.phase3_router.desktop.open_folder(target or "explorer", dry_run=dry_run)
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": resp,
                    "executed": success,
                    "status": "success" if success else "error"
                }
            else:
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": f"Opening {entity}.",
                    "executed": True,
                    "status": "success"
                }

        elif intent == "open_file":
            f_target = target or entity or raw_text
            if getattr(self, "phase3_router", None) is not None:
                success, resp = self.phase3_router.desktop.open_file(f_target, dry_run=dry_run)
            else:
                from phase3.desktop_controller import DesktopController
                success, resp = DesktopController().open_file(f_target, dry_run=dry_run)
            res = {
                "intent": intent,
                "raw_text": raw_text,
                "response": resp,
                "executed": success,
                "status": "success" if success else "error"
            }

        elif intent == "email_compose":
            email_info = self.email_parser.parse_command(norm_text)
            recipient_name = email_info.get("recipient_name") or entity or "Someone"
            contact = self.contact_manager.get_contact(recipient_name)
            if contact:
                response = f"I found {contact['name']}'s email address. What should I write in the email?"
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": response,
                    "executed": True,
                    "status": "contact_found",
                    "contact_found": True,
                    "recipient_name": contact["name"],
                    "recipient_email": contact["email"],
                }
            else:
                response = f"I couldn't find that contact. What is their email address?"
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": response,
                    "executed": True,
                    "status": "contact_not_found",
                    "contact_found": False,
                    "recipient_name": recipient_name,
                    "recipient_email": None,
                }

        elif intent == "summarize_document":
            doc_query = entity or raw_text
            if dry_run:
                doc_name = entity or "document"
                response = f"[Knowledge Base] Summary generated for {doc_name}."
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": response,
                    "executed": True,
                    "status": "success",
                    "sources": [f"{doc_name}, page 1"],
                }
            elif self.rag_pipeline is not None:
                try:
                    sum_res = self.rag_pipeline.summarize_document(doc_query)
                    sources = sum_res.get("sources", [])
                    if sources:
                        print(f"[RAG Citations] Sources: {', '.join(sources)}")
                    res = {
                        "intent": intent,
                        "raw_text": raw_text,
                        "response": sum_res.get("answer", ""),
                        "executed": sum_res.get("status") == "success",
                        "status": "success" if sum_res.get("status") == "success" else "error",
                        "sources": sources,
                        "rag_data": sum_res
                    }
                except Exception as e:
                    print(f"[CommandRouter] Summarization error: {e}")
                    res = {
                        "intent": intent,
                        "raw_text": raw_text,
                        "response": f"I encountered an error summarizing the document: {e}",
                        "executed": False,
                        "status": "error"
                    }
            else:
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": "The local knowledge base module is currently unavailable.",
                    "executed": False,
                    "status": "unavailable"
                }

        elif intent == "rag_query":
            if dry_run:
                response = f"[Knowledge Base] Verified retrieval response for '{raw_text}'."
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": response,
                    "executed": True,
                    "status": "success",
                    "sources": ["proassist_major_project.md, page 1"],
                }
            elif self.rag_pipeline is not None:
                try:
                    rag_query_text = raw_text
                    lower_raw = raw_text.lower()
                    if any(p in lower_raw for p in ["check the file", "check file", "check the document", "check document", "read the file", "what does the file say", "what is in the file"]):
                        rag_query_text = f"Provide a complete summary and overview of the document: {raw_text}"

                    rag_res = self.rag_pipeline.ask(rag_query_text)
                    sources = rag_res.get("sources", [])
                    if sources:
                        print(f"[RAG Citations] Sources: {', '.join(sources)}")
                    res = {
                        "intent": intent,
                        "raw_text": raw_text,
                        "response": rag_res.get("answer", ""),
                        "executed": True,
                        "status": "success",
                        "sources": sources,
                        "rag_data": rag_res
                    }
                except Exception as e:
                    print(f"[CommandRouter] RAG query error: {e}")
                    res = {
                        "intent": intent,
                        "raw_text": raw_text,
                        "response": "I encountered an error querying the local knowledge base.",
                        "executed": False,
                        "status": "error"
                    }
            else:
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": "The local knowledge base module is currently unavailable.",
                    "executed": False,
                    "status": "unavailable"
                }

        elif intent == "general_question":
            if not dry_run and not is_internet_available():
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": "I need an active internet connection to answer that question.",
                    "executed": False,
                    "status": "offline_no_internet"
                }
            elif getattr(self, "online_llm", None) is not None:
                llm_res = self.online_llm.answer(raw_text, dry_run=dry_run)
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": llm_res.get("answer", ""),
                    "executed": llm_res.get("answered", False),
                    "status": llm_res.get("status", "success"),
                    "sources": llm_res.get("sources", []),
                }
            else:
                res = {
                    "intent": intent,
                    "raw_text": raw_text,
                    "response": "Online question answering module is unavailable.",
                    "executed": False,
                    "status": "unavailable"
                }

        else:
            # Check Phase 3 Router
            if getattr(self, "phase3_router", None) is not None:
                p3_res = self.phase3_router.execute(raw_text, dry_run=dry_run)
                if p3_res.get("handled"):
                    res = p3_res
                    if res.get("executed") or res.get("status") in ["success", "exit"]:
                        print("[CommandRouter] Result: SUCCESS")
                        print("[CommandRouter] Action completed successfully")
                    else:
                        print("[CommandRouter] Result: FAILED")
                    return res

            # Check if this could be an unpatterned question: offline RAG first -> online search fallback
            if not dry_run and re.match(r"^(what|how|who|why|when|where|tell me|explain|search|look up)\b", norm_text):
                found_in_rag = False
                if self.rag_pipeline is not None:
                    try:
                        rag_res = self.rag_pipeline.ask(raw_text)
                        chunks = rag_res.get("chunks", [])
                        ans = rag_res.get("answer", "")
                        if chunks and len(chunks) > 0 and chunks[0].get("score", 0.0) >= 0.60 and ans and "could not find information" not in ans.lower():
                            found_in_rag = True
                            res = {
                                "intent": "rag_query",
                                "raw_text": raw_text,
                                "response": ans,
                                "executed": True,
                                "status": "success",
                                "sources": rag_res.get("sources", []),
                                "rag_data": rag_res
                            }
                            print("[CommandRouter] Action completed successfully")
                            return res
                    except Exception:
                        pass

                if not found_in_rag:
                    clean_search_q = re.sub(r"^(?:what\s+is|what\s+are|tell\s+me\s+about|who\s+is|where\s+is|how\s+to|why\s+is|search\s+for|search|look\s+up)\s+", "", norm_text).strip()
                    if not is_internet_available():
                        res = {
                            "intent": "general_question",
                            "raw_text": raw_text,
                            "response": "I need an active internet connection to answer that question.",
                            "executed": False,
                            "status": "offline_no_internet"
                        }
                        return res
                    elif getattr(self, "online_llm", None) is not None:
                        llm_res = self.online_llm.answer(raw_text, dry_run=False)
                        res = {
                            "intent": "general_question",
                            "raw_text": raw_text,
                            "response": llm_res.get("answer", ""),
                            "executed": llm_res.get("answered", False),
                            "status": llm_res.get("status", "success"),
                            "sources": llm_res.get("sources", [])
                        }
                        print("[CommandRouter] Action completed successfully")
                        return res
                    elif getattr(self, "phase3_router", None) is not None:
                        success, resp = self.phase3_router.web.search_google(clean_search_q, dry_run=False)
                        res = {
                            "intent": "google_search",
                            "raw_text": raw_text,
                            "response": f"Not found in offline documents. {resp}",
                            "executed": success,
                            "status": "success" if success else "error"
                        }
                        print("[CommandRouter] Action completed successfully")
                        return res


            # Safe fallback for unknown commands
            response = f"I heard \"{raw_text}\", but I don't know how to handle that command yet."
            print("[CommandRouter] Action result: FAILED")
            print("[CommandRouter] Result: FAILED")
            return {
                "intent": "unknown",
                "raw_text": raw_text,
                "response": response,
                "executed": False,
                "status": "unknown"
            }

        if res.get("executed") or res.get("status") in ["success", "exit", "contact_found", "contact_not_found"]:
            print("[CommandRouter] Action result: SUCCESS")
            print("[CommandRouter] Result: SUCCESS")
            print("[CommandRouter] Action completed successfully")
        elif res.get("status") == "error":
            print("[CommandRouter] Action result: FAILED")
            print("[CommandRouter] Result: FAILED")
            print(f"[CommandRouter] Action failed: {res.get('response')}")

        return res
