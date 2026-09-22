"""
ProAssist AI - Phase 5 Multilingual Agent Package
Supports English (en), Hindi (hi), and Kannada (kn).
"""

from multilingual.config import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE
from multilingual.language_detector import LanguageDetector
from multilingual.intent_engine import MultilingualIntentEngine
from multilingual.response_manager import MultilingualResponseManager

__all__ = [
    "SUPPORTED_LANGUAGES",
    "DEFAULT_LANGUAGE",
    "LanguageDetector",
    "MultilingualIntentEngine",
    "MultilingualResponseManager",
]
