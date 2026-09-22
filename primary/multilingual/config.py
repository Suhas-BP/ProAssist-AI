"""
ProAssist AI - Phase 5 Multilingual Configuration
Defines language codes, script ranges, thresholds, and prompts for
English (en), Hindi (hi), and Kannada (kn).
"""

from typing import Dict, List, Set

# Supported ISO 639-1 language codes
SUPPORTED_LANGUAGES: Dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "kn": "Kannada",
}

DEFAULT_LANGUAGE: str = "en"
CONFIDENCE_THRESHOLD: float = 0.60

# Unicode Script Ranges
DEVANAGARI_RANGE = (0x0900, 0x097F)
KANNADA_RANGE = (0x0C80, 0x0CFF)
LATIN_RANGE = (0x0041, 0x007A)

# Romanized keyword lexicons for code-switching and transliterated queries
HINDI_ROMAN_MARKERS: Set[str] = {
    "kholo", "shuru", "chalao", "bajao", "band", "ruko", "batao", "samjhao",
    "kya", "hai", "kaise", "kitna", "kitne", "tithi", "tareekh", "samay",
    "namaste", "namaskar", "alvida", "likho", "bhejo", "dhanyawad", "khojo",
    "dastavej", "pucho", "sun", "rahe", "ho", "kaun", "mera", "meri", "aap",
    "tum", "aaj", "kal", "abhi", "kar", "karo", "aur", "mein", "par", "se",
    "ko", "ye", "yeh", "woh", "voh", "bhi"
}

KANNADA_ROMAN_MARKERS: Set[str] = {
    "tereyiri", "prarambhisi", "haaki", "nillisi", "saaku", "saku", "heli",
    "thilisi", "yenu", "yaavudu", "hege", "eshtu", "dinanka", "samaya",
    "namaskara", "vidaya", "bareyiri", "kaluhisi", "huduki", "dakhale",
    "kelisuttideye", "yaaru", "nanna", "neevu", "indu", "naale", "eega",
    "maadi", "mattu", "nalli", "inda", "ge", "idu", "avu", "kooda"
}

# Explicit language switch command phrases
LANGUAGE_SWITCH_PATTERNS = {
    "en": [
        r"\b(speak\s+in\s+english|talk\s+in\s+english|answer\s+in\s+english|in\s+english|switch\s+to\s+english)\b"
    ],
    "hi": [
        r"\b(speak\s+in\s+hindi|talk\s+in\s+hindi|answer\s+in\s+hindi|in\s+hindi|switch\s+to\s+hindi)\b",
        r"\b(हिंदी\s+में\s+(बोलो|बात\s+करो|उत्तर\s+दो|जवाब\s+दो))\b",
        r"\b(hindi\s+mein\s+bolo)\b"
    ],
    "kn": [
        r"\b(speak\s+in\s+kannada|talk\s+in\s+kannada|answer\s+in\s+kannada|in\s+kannada|switch\s+to\s+kannada)\b",
        r"\b(ಕನ್ನಡದಲ್ಲಿ\s+(ಮಾತನಾಡಿ|ಹೇಳಿ|ಉತ್ತರಿಸಿ|ಮಾತಾಡಿ))\b",
        r"\b(kannadadalli\s+mathanadi)\b"
    ]
}

# Prompt suffixes instructing Ollama on target language
OLLAMA_LANGUAGE_DIRECTIVES: Dict[str, str] = {
    "en": "Answer clearly and concisely in English.",
    "hi": "उत्तर स्पष्ट और संक्षेप में हिंदी (Devanagari script) में दें।",
    "kn": "ಉತ್ತರವನ್ನು ಸ್ಪಷ್ಟವಾಗಿ ಮತ್ತು ಸಂಕ್ಷಿಪ್ತವಾಗಿ ಕನ್ನಡದಲ್ಲಿ (Kannada script) ನೀಡಿ.",
}
