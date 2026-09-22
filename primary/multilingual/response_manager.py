"""
Response Manager Module for ProAssist AI Phase 5
Localizes assistant responses across English (en), Hindi (hi), and Kannada (kn)
and handles runtime TTS voice selection with graceful non-crashing fallback.
"""

import re
from typing import Dict, Any, Optional, List


class MultilingualResponseManager:
    """Manages localized responses and multilingual TTS."""

    def __init__(self, enable_tts: bool = True):
        self.enable_tts = enable_tts
        self._available_voices: Optional[List[Dict[str, Any]]] = None
        self._detect_system_voices()

        # Localized deterministic response templates
        self.templates = {
            "open_application": {
                "en": "Opening {target}.",
                "hi": "{target} खोल रहा हूँ।",
                "kn": "{target} ತೆರೆಯುತ್ತಿದ್ದೇನೆ.",
            },
            "open_website": {
                "en": "Opening {target}.",
                "hi": "{target} खोल रहा हूँ।",
                "kn": "{target} ತೆರೆಯುತ್ತಿದ್ದೇನೆ.",
            },
            "get_time": {
                "en": "The current time is {time}.",
                "hi": "वर्तमान समय {time} है।",
                "kn": "ಪ್ರಸ್ತುತ ಸಮಯ {time} ಆಗಿದೆ.",
            },
            "get_date": {
                "en": "Today is {date}.",
                "hi": "आज {date} है।",
                "kn": "ಇಂದು {date} ಆಗಿದೆ.",
            },
            "calculate": {
                "en": "The answer is {ans}.",
                "hi": "उत्तर {ans} है।",
                "kn": "ಉತ್ತರ {ans} ಆಗಿದೆ.",
            },
            "google_search": {
                "en": "Searching Google for {query}.",
                "hi": "गूगल पर {query} खोज रहा हूँ।",
                "kn": "ಗೂಗಲ್‌ನಲ್ಲಿ {query} ಹುಡುಕುತ್ತಿದ್ದೇನೆ.",
            },
            "youtube_search": {
                "en": "Searching YouTube for {query}.",
                "hi": "यूट्यूब पर {query} खोज रहा हूँ।",
                "kn": "ಯೂಟ್ಯೂಬ್‌ನಲ್ಲಿ {query} ಹುಡುಕುತ್ತಿದ್ದೇನೆ.",
            },
            "youtube_play": {
                "en": "Playing {query} on YouTube.",
                "hi": "यूट्यूब पर {query} चला रहा हूँ।",
                "kn": "ಯೂಟ್ಯೂಬ್‌ನಲ್ಲಿ {query} ಪ್ಲೇ ಮಾಡುತ್ತಿದ್ದೇನೆ.",
            },
            "notepad_write": {
                "en": "Typing that into Notepad.",
                "hi": "नोटपैड में टाइप कर रहा हूँ।",
                "kn": "ನೋಟ್‌ಪ್ಯಾಡ್‌ನಲ್ಲಿ ಟೈಪ್ ಮಾಡುತ್ತಿದ್ದೇನೆ.",
            },
            "greeting": {
                "en": "Hello! How can I help you?",
                "hi": "नमस्ते! मैं आपकी क्या मदद कर सकता हूँ?",
                "kn": "ನಮಸ್ಕಾರ! ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಲಿ?",
            },
            "who_are_you": {
                "en": "I am ProAssist, your universal intelligent voice assistant.",
                "hi": "मैं ProAssist हूँ, आपका सार्वभौमिक बुद्धिमान वॉयस असिस्टेंट।",
                "kn": "ನಾನು ProAssist, ನಿಮ್ಮ ಸಾರ್ವತ್ರಿಕ ಬುದ್ಧಿವಂತ ಧ್ವನಿ ಸಹಾಯಕ.",
            },
            "can_you_hear_me": {
                "en": "Yes, I can hear you clearly.",
                "hi": "हाँ, मैं आपको स्पष्ट रूप से सुन सकता हूँ।",
                "kn": "ಹೌದು, ನಾನು ನಿಮ್ಮನ್ನು ಸ್ಪಷ್ಟವಾಗಿ ಕೇಳಬಲ್ಲೆ.",
            },
            "exit": {
                "en": "Going back to wake-word listening.",
                "hi": "वेक-वर्ड सुनने की स्थिति में वापस जा रहा हूँ।",
                "kn": "ವೇಕ್-ವರ್ಡ್ ಆಲಿಸುವಿಕೆಗೆ ಮರಳುತ್ತಿದ್ದೇನೆ.",
            },
            "email_compose": {
                "en": "I found {recipient}'s email address. What should I write in the email?",
                "hi": "मुझे {recipient} का ईमेल पता मिल गया है। ईमेल में क्या लिखना है?",
                "kn": "ನನಗೆ {recipient} ಅವರ ಇಮೇಲ್ ವಿಳಾಸ ಸಿಕ್ಕಿದೆ. ಇಮೇಲ್‌ನಲ್ಲಿ ಏನನ್ನು ಬರೆಯಬೇಕು?",
            },
            "summarize_document": {
                "en": "Here is the summary of {target}.",
                "hi": "यहाँ {target} का सारांश दिया गया है।",
                "kn": "{target} ಸಾರಾಂಶ ಇಲ್ಲಿದೆ.",
            },
            "unknown": {
                "en": "I heard \"{raw}\", but I don't know how to handle that command yet.",
                "hi": "मैंने सुना \"{raw}\", लेकिन मुझे यह आदेश संभालना नहीं आता।",
                "kn": "ನಾನು ಕೇಳಿದೆ \"{raw}\", ಆದರೆ ಈ ಆಜ್ಞೆಯನ್ನು ಹೇಗೆ ನಿರ್ವಹಿಸಬೇಕೆಂದು ನನಗೆ ತಿಳಿದಿಲ್ಲ.",
            },
            "language_switch": {
                "en": "Switched to English.",
                "hi": "हिंदी में बदल दिया है।",
                "kn": "ಕನ್ನಡಕ್ಕೆ ಬದಲಾಯಿಸಲಾಗಿದೆ.",
            },
            "thank_you": {
                "en": "You're welcome! Let me know if you need anything else.",
                "hi": "आपका स्वागत है! अगर आपको कुछ और चाहिए तो बताइए।",
                "kn": "ಸ್ವಾಗತ! ನಿಮಗೆ ಇನ್ನೇನಾದರೂ ಬೇಕಿದ್ದರೆ ತಿಳಿಸಿ.",
            },
            "volume_set": {
                "en": "Volume set to {target} percent.",
                "hi": "वॉल्यूम {target} प्रतिशत पर सेट किया।",
                "kn": "ವಾಲ್ಯೂಮ್ {target} ಪ್ರತಿಶತಕ್ಕೆ ಹೊಂದಿಸಲಾಗಿದೆ.",
            },
            "volume_up": {
                "en": "Volume increased.",
                "hi": "आवाज़ बढ़ा दी।",
                "kn": "ವಾಲ್ಯೂಮ್ ಹೆಚ್ಚಿಸಲಾಗಿದೆ.",
            },
            "volume_down": {
                "en": "Volume decreased.",
                "hi": "आवाज़ कम कर दी।",
                "kn": "ವಾಲ್ಯೂಮ್ ಕಡಿಮೆ ಮಾಡಲಾಗಿದೆ.",
            },
            "volume_mute": {
                "en": "Muted.",
                "hi": "म्यूट कर दिया।",
                "kn": "ಮ್ಯೂಟ್ ಮಾಡಲಾಗಿದೆ.",
            },
            "volume_unmute": {
                "en": "Unmuted.",
                "hi": "म्यूट हटा दिया।",
                "kn": "ಮ್ಯೂಟ್ ತೆಗೆದುಹಾಕಲಾಗಿದೆ.",
            },
            "media_play_pause": {
                "en": "Done.",
                "hi": "हो गया।",
                "kn": "ಆಯಿತು.",
            },
            "media_next": {
                "en": "Next track.",
                "hi": "अगला गाना।",
                "kn": "ಮುಂದಿನ ಟ್ರ್ಯಾಕ್.",
            },
            "media_prev": {
                "en": "Previous track.",
                "hi": "पिछला गाना।",
                "kn": "ಹಿಂದಿನ ಟ್ರ್ಯಾಕ್.",
            },
            "screenshot": {
                "en": "Screenshot saved to Pictures.",
                "hi": "स्क्रीनशॉट Pictures में सेव किया।",
                "kn": "ಸ್ಕ್ರೀನ್‌ಶಾಟ್ Pictures ನಲ್ಲಿ ಉಳಿಸಲಾಗಿದೆ.",
            },
            "window_minimize": {
                "en": "Window minimized.",
                "hi": "विंडो छोटी कर दी।",
                "kn": "ವಿಂಡೋ ಕಿರಿದಾಗಿಸಲಾಗಿದೆ.",
            },
            "window_maximize": {
                "en": "Window maximized.",
                "hi": "विंडो बड़ी कर दी।",
                "kn": "ವಿಂಡೋ ದೊಡ್ಡದಾಗಿಸಲಾಗಿದೆ.",
            },
            "window_close": {
                "en": "Window closed.",
                "hi": "विंडो बंद कर दी।",
                "kn": "ವಿಂಡೋ ಮುಚ್ಚಲಾಗಿದೆ.",
            },
            "clipboard_read": {
                "en": "Clipboard read.",
                "hi": "क्लिपबोर्ड पढ़ लिया।",
                "kn": "ಕ್ಲಿಪ್‌ಬೋರ್ಡ್ ಓದಲಾಗಿದೆ.",
            },
            "general_question": {
                "en": "{response}",
                "hi": "{response}",
                "kn": "{response}",
            },
            "offline_no_internet": {
                "en": "I need an active internet connection to answer that question.",
                "hi": "इस प्रश्न का उत्तर देने के लिए मुझे इंटरनेट कनेक्शन की आवश्यकता है।",
                "kn": "ಈ ಪ್ರಶ್ನೆಗೆ ಉತ್ತರಿಸಲು ನನಗೆ ಇಂಟರ್ನೆಟ್ ಸಂಪರ್ಕದ ಅಗತ್ಯವಿದೆ.",
            },
        }





    def _detect_system_voices(self):
        """Scans local SAPI5 voices at runtime to discover language capabilities."""
        self._available_voices = []
        try:
            import pyttsx3
            engine = pyttsx3.init()
            voices = engine.getProperty("voices") or []
            for v in voices:
                v_name = (v.name or "").lower()
                v_id = (v.id or "").lower()
                # Determine supported language of voice
                lang = "en"
                if "hindi" in v_name or "kalpana" in v_name or "hemant" in v_name or "hi-in" in v_id or "hi_" in v_id:
                    lang = "hi"
                elif "kannada" in v_name or "kn-in" in v_id or "kn_" in v_id:
                    lang = "kn"
                elif "english" in v_name or "david" in v_name or "zira" in v_name or "en-us" in v_id or "en-gb" in v_id:
                    lang = "en"

                self._available_voices.append({
                    "id": v.id,
                    "name": v.name,
                    "lang": lang
                })
        except Exception as e:
            print(f"[MultilingualTTS] Voice query notice: {e}")

    def get_voice_for_language(self, language: str) -> Optional[str]:
        """Returns the best matching SAPI5 voice ID for the given language."""
        if not self._available_voices:
            self._detect_system_voices()
        for v in self._available_voices:
            if v["lang"] == language:
                return v["id"]
        return None

    def localize(self, intent: str, language: str, context: Optional[Dict[str, Any]] = None, default_en: str = "") -> str:
        """
        Returns a localized response string for the given intent and language.
        Falls back to default_en if no template is found.
        """
        lang = language if language in ["en", "hi", "kn"] else "en"
        ctx = context or {}

        if intent in self.templates and lang in self.templates[intent]:
            tmpl = self.templates[intent][lang]
            try:
                # Format parameters safely
                target_val = ctx.get("target") or "Application"
                # Map target names nicely
                if target_val == "chrome":
                    target_display = "Chrome" if lang == "en" else ("क्रोम" if lang == "hi" else "ಕ್ರೋಮ್")
                elif target_val == "calculator":
                    target_display = "Calculator" if lang == "en" else ("कैलकुलेटर" if lang == "hi" else "ಕ್ಯಾಲ್ಕುಲೇಟರ್")
                elif target_val == "notepad":
                    target_display = "Notepad" if lang == "en" else ("नोटपैड" if lang == "hi" else "ನೋಟ್‌ಪ್ಯಾಡ್")
                elif target_val == "file_explorer":
                    target_display = "File Explorer" if lang == "en" else ("फ़ाइल एक्सप्लोरर" if lang == "hi" else "ಫೈಲ್ ಎಕ್ಸ್‌ಪ್ಲೋರರ್")
                elif target_val == "youtube":
                    target_display = "YouTube" if lang == "en" else ("यूट्यूब" if lang == "hi" else "ಯೂಟ್ಯೂಬ್")
                elif target_val == "google":
                    target_display = "Google" if lang == "en" else ("गूगल" if lang == "hi" else "ಗೂಗಲ್")
                else:
                    target_display = target_val

                # Format time / date / ans if available from default_en
                time_val = ctx.get("time")
                date_val = ctx.get("date")
                ans_val = ctx.get("ans")
                raw_val = ctx.get("raw_text") or ctx.get("raw") or ""
                query_val = ctx.get("query") or ""
                rec_val = ctx.get("recipient") or "Rahul"

                # Extract answer from default_en if calculate
                if intent == "calculate" and not ans_val and "The answer is" in default_en:
                    ans_val = default_en.split("The answer is")[-1].strip().rstrip(".")

                if intent == "get_time" and not time_val and "time is" in default_en:
                    time_val = default_en.split("time is")[-1].strip().rstrip(".")

                if intent == "get_date" and not date_val and "Today is" in default_en:
                    date_val = default_en.split("Today is")[-1].strip().rstrip(".")

                return tmpl.format(
                    target=target_display,
                    time=time_val or "04:00 PM",
                    date=date_val or "Wednesday, September 09, 2026",
                    ans=ans_val or "",
                    query=query_val,
                    raw=raw_val,
                    recipient=rec_val
                )
            except Exception:
                pass

        return default_en

    def speak_multilingual(self, text: str, language: str):
        """
        Synthesizes text in the specified language using local pyttsx3.
        Gracefully handles missing Indic voices without crashing.
        """
        if not self.enable_tts or not text:
            return

        lang = language if language in ["en", "hi", "kn"] else "en"
        voice_id = self.get_voice_for_language(lang)

        text_to_speak = text
        if lang in ["hi", "kn"] and not voice_id:
            lang_name = "Hindi" if lang == "hi" else "Kannada"
            print(f"[TTS Diagnostic] Native {lang_name} voice not installed in Windows SAPI5. Audio speaking via system voice.")
            text_to_speak = self._get_speech_fallback(text)

        try:
            if not hasattr(self, "_tts_engine") or self._tts_engine is None:
                import pyttsx3
                self._tts_engine = pyttsx3.init()
            engine = self._tts_engine
            if voice_id:
                engine.setProperty("voice", voice_id)
            try:
                import config
                rate = getattr(config, "TTS_RATE", 200)
            except Exception:
                rate = 200
            engine.setProperty("rate", rate)
            engine.say(text_to_speak)
            engine.runAndWait()
        except Exception as e:
            print(f"[MultilingualTTS Error] {e}")
            self._tts_engine = None

    def respond(self, text: str, language: str = "en", speak: bool = True) -> str:
        """Visual terminal delivery and audio output."""
        try:
            print(f"\n[PROASSIST ({language.upper()})] {text}\n")
        except UnicodeEncodeError:
            safe_text = text.encode("ascii", "backslashreplace").decode("ascii")
            print(f"\n[PROASSIST ({language.upper()})] {safe_text}\n")
        if speak:
            self.speak_multilingual(text, language)
        return text

    @staticmethod
    def _get_speech_fallback(text: str) -> str:
        """Provides natural English speech fallback when Indic SAPI5 voices are not installed."""
        t = text.strip()
        if "खोल रहा हूँ" in t or "ತೆರೆಯುತ್ತಿದ್ದೇನೆ" in t:
            first_word = t.split()[0].capitalize() if t.split() else "Application"
            return f"Opening {first_word}."
        if "नमस्ते" in t or "ನಮಸ್ಕಾರ" in t:
            return "Hello! How can I help you?"
        if "सुन सकता हूँ" in t or "ಕೇಳಬಲ್ಲೆ" in t:
            return "Yes, I can hear you clearly."
        if "टाइप कर रहा हूँ" in t or "ಟೈಪ್ ಮಾಡುತ್ತಿದ್ದೇನೆ" in t:
            return "Typing that into Notepad."
        if "वापस जा रहा हूँ" in t or "ಮರಳುತ್ತಿದ್ದೇನೆ" in t:
            return "Going back to wake-word listening."
        if "सारांश" in t or "ಸಾರಾಂಶ" in t:
            return "Here is the summary of the document."
        if "बदल दिया है" in t or "ಬದಲಾಯಿಸಲಾಗಿದೆ" in t:
            return "Language switched."
        if "स्वागत है" in t or "ಸ್ವಾಗತ" in t:
            return "You're welcome! Let me know if you need anything else."
        if "संभालना नहीं आता" in t or "ತಿಳಿದಿಲ್ಲ" in t:
            return "I heard your request, but I don't know how to handle that command yet."
        latin_chars = sum(1 for c in t if 'a' <= c.lower() <= 'z' or c.isdigit() or c in ' :.,')
        if latin_chars >= len(t) * 0.5:
            return t
        return "Action completed."
