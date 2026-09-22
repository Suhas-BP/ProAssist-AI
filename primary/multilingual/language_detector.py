"""
Language Detector Module for ProAssist AI Phase 5
Accurately identifies English (en), Hindi (hi), and Kannada (kn) from
transcribed text and speech metadata, supporting native scripts and code-switching.
"""

import re
from typing import Dict, Any, Optional
from multilingual.config import (
    SUPPORTED_LANGUAGES,
    DEFAULT_LANGUAGE,
    CONFIDENCE_THRESHOLD,
    DEVANAGARI_RANGE,
    KANNADA_RANGE,
    HINDI_ROMAN_MARKERS,
    KANNADA_ROMAN_MARKERS,
    LANGUAGE_SWITCH_PATTERNS
)


class LanguageDetector:
    """Detects spoken/written language among English, Hindi, and Kannada."""

    def __init__(self, current_language: str = DEFAULT_LANGUAGE):
        self.current_language = current_language if current_language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE

    def _check_explicit_switch(self, text: str) -> Optional[str]:
        """Checks if the user explicitly commanded a language switch."""
        lower = text.lower().strip()
        for lang, patterns in LANGUAGE_SWITCH_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, lower, re.IGNORECASE):
                    return lang
        return None

    def detect(self, text: str, whisper_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Detects the language of the given text.

        Returns:
            dict: {
                "language": "en" | "hi" | "kn",
                "confidence": float,
                "name": str,
                "explicit_switch": bool
            }
        """
        if not text or not text.strip():
            return {
                "language": self.current_language,
                "confidence": 1.0,
                "name": SUPPORTED_LANGUAGES[self.current_language],
                "explicit_switch": False
            }

        raw_text = text.strip()

        # 1. Check for explicit language switch commands
        explicit_lang = self._check_explicit_switch(raw_text)
        if explicit_lang:
            self.current_language = explicit_lang
            return {
                "language": explicit_lang,
                "confidence": 0.99,
                "name": SUPPORTED_LANGUAGES[explicit_lang],
                "explicit_switch": True
            }

        # 2. Count Unicode script characters
        total_letters = 0
        devanagari_count = 0
        kannada_count = 0
        latin_count = 0

        for ch in raw_text:
            cp = ord(ch)
            if DEVANAGARI_RANGE[0] <= cp <= DEVANAGARI_RANGE[1]:
                devanagari_count += 1
                total_letters += 1
            elif KANNADA_RANGE[0] <= cp <= KANNADA_RANGE[1]:
                kannada_count += 1
                total_letters += 1
            elif ('a' <= ch <= 'z') or ('A' <= ch <= 'Z'):
                latin_count += 1
                total_letters += 1

        if total_letters > 0:
            dev_ratio = devanagari_count / total_letters
            kan_ratio = kannada_count / total_letters

            # High confidence native script detection
            if devanagari_count >= 2 or (devanagari_count > 0 and dev_ratio >= 0.06):
                confidence = min(0.99, 0.70 + dev_ratio * 0.3)
                self.current_language = "hi"
                return {
                    "language": "hi",
                    "confidence": round(confidence, 2),
                    "name": SUPPORTED_LANGUAGES["hi"],
                    "explicit_switch": False
                }

            if kannada_count >= 2 or (kannada_count > 0 and kan_ratio >= 0.06):
                confidence = min(0.99, 0.70 + kan_ratio * 0.3)
                self.current_language = "kn"
                return {
                    "language": "kn",
                    "confidence": round(confidence, 2),
                    "name": SUPPORTED_LANGUAGES["kn"],
                    "explicit_switch": False
                }

        # 3. Whisper metadata integration (if provided)
        if whisper_info and "language" in whisper_info:
            w_lang = whisper_info["language"]
            w_prob = whisper_info.get("language_probability", 0.0)
            if w_lang in SUPPORTED_LANGUAGES and w_prob >= CONFIDENCE_THRESHOLD:
                self.current_language = w_lang
                return {
                    "language": w_lang,
                    "confidence": round(w_prob, 2),
                    "name": SUPPORTED_LANGUAGES[w_lang],
                    "explicit_switch": False
                }

        # 4. Lexicon matching for Romanized / transliterated Hindi and Kannada
        clean_words = set(re.sub(r"[^\w\s]", " ", raw_text.lower()).split())
        hi_matches = len(clean_words.intersection(HINDI_ROMAN_MARKERS))
        kn_matches = len(clean_words.intersection(KANNADA_ROMAN_MARKERS))

        if hi_matches > kn_matches and hi_matches >= 1:
            confidence = min(0.92, 0.65 + hi_matches * 0.1)
            self.current_language = "hi"
            return {
                "language": "hi",
                "confidence": round(confidence, 2),
                "name": SUPPORTED_LANGUAGES["hi"],
                "explicit_switch": False
            }

        if kn_matches > hi_matches and kn_matches >= 1:
            confidence = min(0.92, 0.65 + kn_matches * 0.1)
            self.current_language = "kn"
            return {
                "language": "kn",
                "confidence": round(confidence, 2),
                "name": SUPPORTED_LANGUAGES["kn"],
                "explicit_switch": False
            }

        # 5. Default fallback to English
        return {
            "language": "en",
            "confidence": 0.90 if latin_count > 0 else 0.70,
            "name": SUPPORTED_LANGUAGES["en"],
            "explicit_switch": False
        }
