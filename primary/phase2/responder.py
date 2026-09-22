"""
Responder Module for ProAssist AI Phase 2
Handles assistant responses via terminal logging and speech synthesis (pyttsx3)
using the project's existing local TTS settings without modifying Phase 1.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config


_cached_engine = None

def get_cached_tts_engine():
    """Returns a shared pyttsx3 engine instance to avoid expensive re-initialization."""
    global _cached_engine
    if _cached_engine is None:
        try:
            import pyttsx3
            _cached_engine = pyttsx3.init()
            rate = getattr(config, "TTS_RATE", 200)
            _cached_engine.setProperty("rate", rate)
        except Exception:
            _cached_engine = None
    return _cached_engine


class Responder:
    """Delivers responses to the user visually and aurally across languages."""

    def __init__(self, enable_tts: bool = config.ENABLE_TTS):
        self.enable_tts = enable_tts

    def speak(self, text: str, language: str = "en"):
        """Speaks text aloud using local pyttsx3 with runtime voice selection and fast cached engine."""
        if not self.enable_tts or not text:
            return

        global _cached_engine
        try:
            engine = get_cached_tts_engine()
            if engine is None:
                import pyttsx3
                engine = pyttsx3.init()
            
            rate = getattr(config, "TTS_RATE", 200)
            engine.setProperty("rate", rate)

            # Runtime SAPI5 voice detection
            if language in ["hi", "kn"]:
                matched_voice = None
                for v in (engine.getProperty("voices") or []):
                    v_name = (v.name or "").lower()
                    v_id = (v.id or "").lower()
                    if language == "hi" and ("hindi" in v_name or "kalpana" in v_name or "hemant" in v_name or "hi-in" in v_id):
                        matched_voice = v.id
                        break
                    elif language == "kn" and ("kannada" in v_name or "kn-in" in v_id):
                        matched_voice = v.id
                        break

                if matched_voice:
                    engine.setProperty("voice", matched_voice)
                    text_to_speak = text
                else:
                    lang_label = "Hindi" if language == "hi" else "Kannada"
                    print(f"[TTS Notice] Native {lang_label} voice not installed in Windows SAPI5. Audio speaking via system voice.")
                    text_to_speak = self._get_speech_fallback(text)
            else:
                text_to_speak = text

            engine.say(text_to_speak)
            engine.runAndWait()
        except Exception as e:
            print(f"[Responder TTS Error] {e}")
            _cached_engine = None

    def respond(self, text: str, speak: bool = True, language: str = "en") -> str:
        """
        Prints the response to the terminal and optionally speaks it aloud.
        Returns:
            The response text.
        """
        try:
            print(f"\n[PROASSIST] {text}\n")
        except UnicodeEncodeError:
            safe_text = text.encode("ascii", "backslashreplace").decode("ascii")
            print(f"\n[PROASSIST] {safe_text}\n")

        if speak:
            self.speak(text, language=language)
        return text

    @staticmethod
    def _get_speech_fallback(text: str) -> str:
        """Provides natural English speech fallback when Indic SAPI5 voices are not installed."""
        t = text.strip()
        if "खोल रहा हूँ" in t or "ತೆರೆಯುತ್ತಿದ್ದೇನೆ" in t:
            # Extract target name (first word)
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
        if "बदलकर" in t or "ಬದಲಾಯಿಸಲಾಗಿದೆ" in t:
            return "Language switched."
        if "संभालना नहीं आता" in t or "ತಿಳಿದಿಲ್ಲ" in t:
            return "I heard your request, but I don't know how to handle that command yet."
        # If text contains mostly Latin words, speak it directly
        latin_chars = sum(1 for c in t if 'a' <= c.lower() <= 'z' or c.isdigit() or c in ' :.,')
        if latin_chars >= len(t) * 0.5:
            return t
        return "Action completed."
