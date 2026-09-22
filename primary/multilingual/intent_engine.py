"""
Multilingual Intent Engine for ProAssist AI Phase 5
Translates user utterances in English, Hindi, and Kannada into
language-independent structured intents and generates canonical commands
for the existing central CommandRouter.
"""

import re
from typing import Dict, Any, Optional
from multilingual.language_detector import LanguageDetector


class MultilingualIntentEngine:
    """Understands intents across English, Hindi, and Kannada."""

    def __init__(self, detector: Optional[LanguageDetector] = None):
        self.detector = detector or LanguageDetector()

        # Application and Website name mappings
        self.app_aliases = {
            # Chrome / Browser
            "chrome": "chrome",
            "google chrome": "chrome",
            "क्रोम": "chrome",
            "गूगल क्रोम": "chrome",
            "ಕ್ರೋಮ್": "chrome",
            "ಗೂಗಲ್ ಕ್ರೋಮ್": "chrome",
            "browser": "browser",
            "ब्राउज़र": "browser",
            "ಬ್ರೌಸರ್": "browser",
            "edge": "microsoft edge",
            "microsoft edge": "microsoft edge",
            # Calculator
            "calculator": "calculator",
            "calc": "calculator",
            "कैलकुलेटर": "calculator",
            "कैलकुलेटर ऐप": "calculator",
            "ಕ್ಯಾಲ್ಕುಲೇಟರ್": "calculator",
            # Notepad
            "notepad": "notepad",
            "नोटपैड": "notepad",
            "ನೋಟ್‌ಪ್ಯಾಡ್": "notepad",
            "ನೋಟ್ ಪ್ಯಾಡ್": "notepad",
            # Word / MS Word
            "word": "word",
            "ms word": "word",
            "microsoft word": "word",
            "वर्ड": "word",
            "ವರ್ಡ್": "word",
            # Excel
            "excel": "excel",
            "ms excel": "excel",
            "microsoft excel": "excel",
            "एक्सेल": "excel",
            "ಎಕ್ಸೆಲ್": "excel",
            # PowerPoint
            "powerpoint": "powerpoint",
            "ppt": "powerpoint",
            "ms powerpoint": "powerpoint",
            "पॉवरपॉइंट": "powerpoint",
            "ಪವರ್ ಪಾಯಿಂಟ್": "powerpoint",
            # Paint
            "paint": "paint",
            "mspaint": "paint",
            "पेंट": "paint",
            "ಪೇಂಟ್": "paint",
            # Settings
            "settings": "settings",
            "सेटिंग्स": "settings",
            "ಸೆಟ್ಟಿಂಗ್ಸ್": "settings",
            # Camera
            "camera": "camera",
            "कैमरा": "camera",
            "ಕ್ಯಾಮೆರಾ": "camera",
            # OneNote
            "onenote": "onenote",
            "one note": "onenote",
            # Sticky Notes
            "sticky notes": "sticky notes",
            "sticky note": "sticky notes",
            # Terminal / CMD
            "terminal": "terminal",
            "cmd": "cmd",
            "command prompt": "cmd",
            # VS Code / Code
            "vscode": "vs code",
            "vs code": "vs code",
            "code": "vs code",
            "visual studio code": "vs code",
            # File Explorer
            "file explorer": "file_explorer",
            "explorer": "file_explorer",
            "फाइल एक्सप्लोरर": "file_explorer",
            "ಫೈಲ್ ಎಕ್ಸ್‌ಪ್ಲೋರರ್": "file_explorer",
            "downloads": "downloads",
            "डाउनलोड": "downloads",
            "ಡೌನ್‌ಲೋಡ್": "downloads",
            "documents": "documents",
            "दस्तावेज़ फ़ोल्डर": "documents",
            "ದಾಖಲೆಗಳು": "documents",
            # Media / Web
            "spotify": "spotify",
            "vlc": "vlc",
            "youtube": "youtube",
            "यूट्यूब": "youtube",
            "ಯೂಟ್ಯೂಬ್": "youtube",
            "google": "google",
            "गूगल": "google",
            "ಗೂಗಲ್": "google",
            "gmail": "gmail",
            "जीमेल": "gmail",
            "ಜಿಮೇಲ್": "gmail",
            "github": "github",
            "गिटहब": "github",
            "ಗಿಟ್‌ಹಬ್": "github",
        }

        # Action verbs across languages
        self.open_verbs = [
            r"\b(open|launch|start|run)\b",
            r"(खोलो|शुरू\s+करो|चलाओ|खोलें|खोलिए)",
            r"(ತೆರೆಯಿರಿ|ಪ್ರಾರಂಭಿಸಿ|ತೆರೆ|ಹಾಕಿ)",
            r"\b(kholo|chalao|khole|kholiye|tereyiri|shuru|karo|maadi|haki|open\s+karo|open\s+maadi)\b"
        ]

        self.play_verbs = [
            r"\b(play|run)\b",
            r"(बजाओ|चलाओ|प्ले\s+करो|प्ले|bajao|chalao|play\s+karo)",
            r"(ಪ್ಲೇ\s+ಮಾಡಿ|ಹಾಕಿ|ಪ್ಲೇ|play\s+madi|haki)"
        ]

        self.search_verbs = [
            r"\b(search|find|look\s+up|google)\b",
            r"(खोजो|सर्च\s+करो|ढूंढो|सर्च|khojo|search\s+karo|dhundho)",
            r"(ಹುಡುಕಿ|ಸರ್ಚ್\s+ಮಾಡಿ|ಸರ್ಚ್|huduki|search\s+madi)"
        ]

        self.exit_verbs = [
            r"\b(stop|exit|quit|go\s+to\s+sleep|bye|goodbye|cancel|that\s+(is\s+)?all)\b",
            r"(रुको|बंद\s+करो|सो\s+जाओ|बस\s+इतना\s+ही|अलविदा|रद्द\s+करो|ruko|band\s+karo|so\s+jao|alvida)",
            r"(ನಿಲ್ಲಿಸಿ|ಸಾಕು|ಮುಕ್ತಾಯ|ವಿದಾಯ|ರದ್ದು\s+ಮಾಡಿ|ನಿದ್ರೆಗೆ\s+ಹೋಗಿ|nillisi|saku|vidaya)"
        ]

    def _extract_target(self, text: str) -> Optional[str]:
        """Finds any recognized application or website target in text."""
        lower = text.lower()
        # Check longest aliases first
        sorted_aliases = sorted(self.app_aliases.keys(), key=len, reverse=True)
        for alias in sorted_aliases:
            if alias in lower:
                return self.app_aliases[alias]
        return None

    def _normalize_math_expression(self, text: str) -> str:
        """Converts Hindi and Kannada math operators and numerals to standard form."""
        replacements = [
            # Hindi
            (r"\bप्लस\b", "plus"),
            (r"\bधन\b", "plus"),
            (r"\bऔर\b", "plus"),
            (r"\bमाइनस\b", "minus"),
            (r"\bऋण\b", "minus"),
            (r"\bघटाओ\b", "minus"),
            (r"\bकम\b", "minus"),
            (r"\bगुणा\b", "times"),
            (r"\bगुना\b", "times"),
            (r"\bइंटू\b", "times"),
            (r"\bभागा\b", "divided by"),
            (r"\bविभाजित\b", "divided by"),
            (r"\bबटे\b", "divided by"),
            # Kannada
            (r"\bಮತ್ತು\b", "plus"),
            (r"\bಕೂಡಿಸು\b", "plus"),
            (r"\bಪ್ಲಸ್\b", "plus"),
            (r"\bಕಳೆ\b", "minus"),
            (r"\bಮೈನಸ್\b", "minus"),
            (r"\bಗುಣಿಸು\b", "times"),
            (r"\bಇಂಟು\b", "times"),
            (r"\bಭಾಗಿಸು\b", "divided by"),
            (r"\bಡಿವೈಡೆಡ್\b", "divided by"),
        ]
        res = text
        for pat, rep in replacements:
            res = re.sub(pat, rep, res, flags=re.IGNORECASE)
        return res

    def parse_intent(self, text: str) -> Dict[str, Any]:
        """
        Parses a multilingual command into a language-independent structured intent.

        Returns:
            dict: {
                "intent": str,
                "language": "en" | "hi" | "kn",
                "target": Optional[str],
                "query": Optional[str],
                "recipient": Optional[str],
                "canonical_command": str,
                "raw_text": str
            }
        """
        raw_text = text.strip()
        det_result = self.detector.detect(raw_text)
        lang = det_result["language"]
        lower = raw_text.lower()

        # Default fallback structure
        result: Dict[str, Any] = {
            "intent": "unknown",
            "language": lang,
            "target": None,
            "query": None,
            "recipient": None,
            "canonical_command": raw_text,
            "raw_text": raw_text
        }

        # 0. Language Switch Commands
        if det_result.get("explicit_switch"):
            lang_names = {"en": "English", "hi": "Hindi", "kn": "Kannada"}
            result["intent"] = "language_switch"
            result["target"] = lang
            result["canonical_command"] = f"switch to {lang_names.get(lang, 'English')}"
            return result

        # 1. Exit Commands
        for pat in self.exit_verbs:
            if re.search(pat, lower, re.IGNORECASE):
                result["intent"] = "exit"
                result["canonical_command"] = "stop"
                return result

        # 2. Conversational Checks
        # can_you_hear_me
        if (
            re.search(r"\b(can\s+you\s+hear\s+me|are\s+you\s+listening)\b", lower)
            or re.search(r"(सुन\s+सकते\s+हो|मेरी\s+आवाज|सुन\s+रहे\s+हो)", lower)
            or re.search(r"(ಕೇಳಿಸುತ್ತಿದೆಯೇ|ನನ್ನ\s+ಧ್ವನಿ|ಕೇಳಿಸುತ್ತಾ)", lower)
        ):
            result["intent"] = "can_you_hear_me"
            result["canonical_command"] = "can you hear me"
            return result

        # who_are_you
        if (
            re.search(r"\b(who\s+are\s+you|what\s+is\s+your\s+name)\b", lower)
            or re.search(r"(आप\s+कौन\s+हैं|तुम्हारा\s+नाम\s+क्या|तू\s+कौन\s+है)", lower)
            or re.search(r"(ನೀವು\s+ಯಾರು|ನಿಮ್ಮ\s+ಹೆಸರೇನು|ಯಾರು\s+ನೀವು)", lower)
        ):
            result["intent"] = "who_are_you"
            result["canonical_command"] = "who are you"
            return result

        # greeting
        is_greeting_kw = bool(
            re.search(r"\b(hello|hi|hey|good\s+morning|good\s+evening)\b", lower)
            or re.search(r"(नमस्ते|नमस्कार|हेलो|हाय)", lower)
            or re.search(r"(ನಮಸ್ಕಾರ|ಹಲೋ|ಹಾಯ್)", lower)
        )
        has_action_kw = any(w in lower for w in [
            "notepad", "नोटपैड", "ನೋಟ್‌ಪ್ಯಾಡ್", "chrome", "क्रोम", "ಕ್ರೋಮ್",
            "youtube", "यूट्यूब", "ಯೂಟ್ಯೂಬ್", "search", "सर्च", "ಸರ್ಚ್",
            "type", "write", "लिखो", "ಬರೆಯಿರಿ", "calculate", "play",
            "file", "फाइल", "ದಿನಾಂಕ", "ಸಮಯ", "summarize", "summary", "सारांश", "ಸಾರಾಂಶ"
        ])
        if is_greeting_kw and not has_action_kw:
            result["intent"] = "greeting"
            result["canonical_command"] = "hello"
            return result

        # get_time
        if (
            re.search(r"\b(what\s+time\s+is\s+it|the\s+time|current\s+time|time\s+kya\s+hua|kya\s+time\s+hua)\b", lower)
            or re.search(r"(समय\s+क्या\s+है|कितने\s+बजे\s+हैं|वक्त\s+क्या\s+हुआ|समय\s+बताओ|samay\s+kya\s+hai|kitne\s+baje\s+hai|waqt\s+kya\s+hai|samay\s+batao|time\s+batao)", lower)
            or re.search(r"(ಸಮಯ\s+ಎಷ್ಟು|ಈಗ\s+ಸಮಯ\s+ಎಷ್ಟು|ಸಮಯ\s+ತಿಳಿಸಿ|samaya\s+eshtu)", lower)
        ):
            result["intent"] = "get_time"
            result["canonical_command"] = "what time is it"
            return result

        # get_date
        if (
            re.search(r"\b(what\s+is\s+today'?s?\s+date|what\s+day\s+is\s+it|current\s+date|aaj\s+kya\s+date\s+hai|today'?s?\s+date\s+kya\s+hai)\b", lower)
            or re.search(r"(आज\s+की\s+तारीख|आज\s+कौन\s+सा\s+दिन|आज\s+क्या\s+तारीख|तारीख\s+बताओ|aaj\s+ki\s+tarikh|aaj\s+kya\s+din\s+hai|tarikh\s+batao|date\s+batao)", lower)
            or re.search(r"(ಇಂದಿನ\s+ದಿನಾಂಕ|ಇಂದು\s+ಯಾವ\s+ದಿನ|ದಿನಾಂಕ\s+ತಿಳಿಸಿ|indina\s+dinanka)", lower)
        ):
            result["intent"] = "get_date"
            result["canonical_command"] = "what is today's date"
            return result

        # 3. YouTube Play
        has_youtube = "youtube" in lower or "यूट्यूब" in lower or "ಯೂಟ್ಯೂಬ್" in lower
        is_play = any(re.search(p, lower, re.IGNORECASE) for p in self.play_verbs)
        if has_youtube and is_play:
            # Extract video/song name
            cleaned = re.sub(r"\b(youtube|on|play|video|song)\b", " ", lower, flags=re.IGNORECASE)
            cleaned = re.sub(r"(यूट्यूब|ಯೂಟ್ಯೂಬ್|पर|ನಲ್ಲಿ|में|बजाओ|चलाओ|प्ले\s+करो|ಪ್ಲೇ\s+ಮಾಡಿ|ಹಾಕಿ|ಪ್ಲೇ|गाना|ಹಾಡು)", " ", cleaned)
            query_val = " ".join(cleaned.split()).strip()
            result["intent"] = "youtube_play"
            result["target"] = "youtube"
            result["query"] = query_val or "Believer"
            result["canonical_command"] = f"play {result['query']} on youtube"
            return result

        # 4. YouTube Search
        is_search = any(re.search(p, lower, re.IGNORECASE) for p in self.search_verbs)
        if has_youtube and is_search:
            cleaned = re.sub(r"\b(youtube|for|on|search|find)\b", " ", lower, flags=re.IGNORECASE)
            cleaned = re.sub(r"(यूट्यूब|ಯೂಟ್ಯೂಬ್|पर|ನಲ್ಲಿ|में|खोजो|सर्च\s+करो|ढूंढो|ಹುಡುಕಿ|ಸರ್ಚ್\s+ಮಾಡಿ|ಸರ್ಚ್|ಮಾಡಿ)", " ", cleaned)
            query_val = " ".join(cleaned.split()).strip()
            result["intent"] = "youtube_search"
            result["target"] = "youtube"
            result["query"] = query_val or "music"
            result["canonical_command"] = f"search youtube for {result['query']}"
            return result

        # 5. Google Search
        has_google = "google" in lower or "गूगल" in lower or "ಗೂಗಲ್" in lower
        if (has_google or "web" in lower or "इंटरनेट" in lower or "ಇಂಟರ್ನೆಟ್" in lower) and is_search:
            cleaned = re.sub(r"\b(google|for|the\s+web|web|search|find|look\s+up)\b", " ", lower, flags=re.IGNORECASE)
            cleaned = re.sub(r"(गूगल|ಗೂಗಲ್|पर|ನಲ್ಲಿ|में|खोजो|सर्च\s+करो|ढूंढो|ಹುಡುಕಿ|ಸರ್ಚ್\s+ಮಾಡಿ|ಸರ್ಚ್|ಮಾಡಿ)", " ", cleaned)
            query_val = " ".join(cleaned.split()).strip()
            result["intent"] = "google_search"
            result["target"] = "google"
            result["query"] = query_val or "news"
            result["canonical_command"] = f"search google for {result['query']}"
            return result

        # 6. Notepad Writing
        has_notepad = "notepad" in lower or "नोटपैड" in lower or "ನೋಟ್‌ಪ್ಯಾಡ್" in lower or "ನೋಟ್ ಪ್ಯಾಡ್" in lower
        has_write = (
            re.search(r"\b(type|write)\b", lower)
            or re.search(r"(लिखो|टाइप\s+करो|दर्ज\s+करो)", lower)
            or re.search(r"(ಬರೆಯಿರಿ|ಟೈಪ್\s+ಮಾಡಿ)", lower)
        )
        if has_notepad and has_write:
            cleaned = lower
            for np_term in ["notepad", "नोटपैड", "ನೋಟ್‌ಪ್ಯಾಡ್", "ನೋಟ್ ಪ್ಯಾಡ್", "in", "में", "ನಲ್ಲಿ"]:
                cleaned = cleaned.replace(np_term, " ")
            for verb in ["type", "write", "लिखो", "टाइप करो", "ಬರೆಯಿರಿ", "ಟೈಪ್ ಮಾಡಿ", "that"]:
                cleaned = cleaned.replace(verb, " ")
            text_val = " ".join(cleaned.split()).strip()
            result["intent"] = "notepad_write"
            result["target"] = "notepad"
            result["query"] = text_val or "Project completed"
            result["canonical_command"] = f"type {result['query']} in notepad"
            return result

        # 7. Math / Calculation
        has_calc_word = (
            re.search(r"\b(calculate|what\s+is\s+\d+|math)\b", lower)
            or re.search(r"(जोड़ो|घटाओ|गुणा|गणना\s+करो|कितना\s+होता\s+है)", lower)
            or re.search(r"(ಕೂಡಿಸು|ಕಳೆ|ಗುಣಿಸು|ಲೆಕ್ಕ\s+ಮಾಡಿ|ಎಷ್ಟು\s+ಆಗುತ್ತದೆ)", lower)
            or bool(re.search(r"\d+\s*(plus|minus|times|divided|\+|\-|\*|\/|प्लस|माइनस|गुना|ಮತ್ತು|ಕಳೆ|ಗುಣಿಸು)\s*\d+", lower))
        )
        if has_calc_word:
            normalized_math = self._normalize_math_expression(lower)
            # Match numbers and operator
            num_match = re.search(r"(\d+)\s*(plus|minus|times|divided\s+by|\+|\-|\*|\/)\s*(\d+)", normalized_math)
            if num_match:
                n1, op, n2 = num_match.groups()
                result["intent"] = "calculate"
                result["canonical_command"] = f"calculate {n1} {op} {n2}"
                return result

        # 8. Open Application or Website
        target = self._extract_target(lower)
        is_open = any(re.search(p, lower, re.IGNORECASE) for p in self.open_verbs)
        if target:
            if target in ["youtube", "google", "gmail", "github"]:
                result["intent"] = "open_website"
                result["target"] = target
                result["canonical_command"] = f"open {target}"
                return result
            else:
                result["intent"] = "open_application"
                result["target"] = target
                canonical_name = target.replace("_", " ")
                result["canonical_command"] = f"open {canonical_name}"
                return result

        # Dynamic laptop application launch when open verb is present
        if is_open:
            cand = lower
            for verb_pat in self.open_verbs:
                cand = re.sub(verb_pat, " ", cand, flags=re.IGNORECASE)
            cand = re.sub(
                r"\b(the|my|app|application|software|program|tool|ko|alli|nalli|mein|par|ge|annu|karo|maadi|kolo|haki|shuru|please)\b",
                " ",
                cand,
                flags=re.IGNORECASE
            )
            cand = re.sub(r"(ऐप|को|में|पर|ಅಪ್ಲಿಕೇಶನ್|ಗೆ|ಅನ್ನು|ನಲ್ಲಿ)", " ", cand)
            cand = " ".join(cand.split()).strip()
            if len(cand) >= 2 and not any(k in cand for k in ["file", "document", "pdf", "email", "summary", "saransh", "time", "date", "kya", "stop"]):
                result["intent"] = "open_application"
                result["target"] = cand
                result["canonical_command"] = f"open {cand}"
                return result

        # 9. Email Compose
        has_email = "email" in lower or "ईमेल" in lower or "ಇಮೇಲ್" in lower
        has_mail_verb = (
            re.search(r"\b(write|send|compose)\b", lower)
            or re.search(r"(लिखो|भेजो|तैयार\s+करो)", lower)
            or re.search(r"(ಬರೆಯಿರಿ|ಕಳುಹಿಸಿ)", lower)
        )
        if has_email or has_mail_verb:
            # Extract recipient name
            # e.g., "राहुल को ईमेल लिखो", "ರಾಹುಲ್‌ಗೆ ಇಮೇಲ್ ಬರೆಯಿರಿ", "write an email to Rahul"
            rec_match = (
                re.search(r"email\s+to\s+([a-zA-Z]+)", lower)
                or re.search(r"([a-zA-Z\u0900-\u097F]+)\s*को\s*ईमेल", lower)
                or re.search(r"([a-zA-Z\u0C80-\u0CFF]+)\s*ಗೆ\s*ಇಮೇಲ್", lower)
            )
            rec_name = rec_match.group(1).strip() if rec_match else "Rahul"
            result["intent"] = "email_compose"
            result["recipient"] = rec_name
            result["canonical_command"] = f"write an email to {rec_name}"
            return result

        # 10. Document / PDF Summarization
        is_summary = (
            bool(re.search(r"\b(summarize|summary|overview|brief)\b", lower))
            or bool(re.search(r"(सारांश|संक्षेप|विवरण|samkshipt|saransh|summary)", lower))
            or bool(re.search(r"(ಸಾರಾಂಶ|ಸಂಕ್ಷಿಪ್ತ|ವಿವರಣೆ|saransha)", lower))
        )
        if is_summary:
            cleaned_doc = lower
            for kw in [
                "summarize", "summary", "of", "the", "file", "files", "document", "documents", "pdf",
                "सारांश", "संक्षेप", "का", "की", "के", "बताओ", "दो", "दस्तावेज़", "फ़ाइल", "फाइल",
                "ಸಾರಾಂಶ", "ಸಂಕ್ಷಿಪ್ತ", "ದಾಖಲೆ", "ಕಡತ", "ಫೈಲ್", "ತಿಳಿಸಿ", "ನೀಡಿ", "ಹೇಳಿ", "ಕೊಡಿ",
                "batao", "karo", "kodi", "thilisi"
            ]:
                cleaned_doc = re.sub(rf"\b{re.escape(kw)}\b", " ", cleaned_doc)
            doc_target = " ".join(cleaned_doc.split()).strip()
            result["intent"] = "summarize_document"
            result["target"] = doc_target or None
            result["canonical_command"] = f"summarize {doc_target}" if doc_target else "summarize the document"
            return result

        # 11. RAG / Knowledge Base Queries
        has_rag_keywords = (
            re.search(r"\b(according\s+to|what\s+does\s+the\s+document|proassist|architecture|project|biometric|threshold)\b", lower)
            or re.search(r"(दस्तावेज़|परियोजना|वास्तुकला|प्रोजेक्ट|बायोमेट्रिक|सीमा|थ्रेशोल्ड)", lower)
            or re.search(r"(ದಾಖಲೆ|ಯೋಜನೆ|ವಾಸ್ತುಶಿಲ್ಪ|ಪ್ರಾಜೆಕ್ಟ್|ಬಯೋಮೆಟ್ರಿಕ್|ಮಿತಿ)", lower)
            or (lang in ["hi", "kn"] and re.search(r"(क्या\s+है|बताओ|ಏನು|ತಿಳಿಸಿ)", lower))
        )
        if has_rag_keywords:
            result["intent"] = "rag_query"
            result["canonical_command"] = raw_text
            return result

        # 11. Fallback / Unknown
        result["intent"] = "unknown"
        result["canonical_command"] = raw_text
        return result
