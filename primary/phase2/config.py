"""
ProAssist AI - Phase 2 Specific Configuration
Extends Phase 1 configuration with command listening and routing parameters
without modifying root config.py.
"""

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config

# =====================================================================
# PHASE 2 WAKE-WORD DETECTION SETTINGS (Calibrated & Reliable)
# =====================================================================
WAKE_BUFFER_SECONDS = 2.0                # Reliable 2.0s buffer capturing complete phrase
WAKE_CHECK_INTERVAL = 0.4                # 400ms check interval avoiding CPU saturation
WAKE_ENERGY_THRESHOLD = 0.013            # Calibrated above ambient noise floor (0.008) to trigger on speech

# Compatibility aliases
FAST_WAKE_BUFFER_SECONDS = 1.5
FAST_WAKE_CHECK_INTERVAL = 0.25
FAST_WAKE_ENERGY_THRESHOLD = 0.006



# =====================================================================
# PHASE 2 COMMAND LISTENING SETTINGS
# =====================================================================
COMMAND_RECORD_DURATION = 4.0            # Fallback seconds if fixed duration used
COMMAND_ENERGY_THRESHOLD = 0.0045        # Calibrated speech energy gate for clear voice detection (ambient ~0.002-0.003, speech >= 0.0045)
COMMAND_WHISPER_BEAM_SIZE = 1            # Beam size for fast transcription
COMMAND_LANGUAGE = "en"                  # Primary command language for Phase 2

# Dynamic Endpointing (VAD) settings
COMMAND_SILENCE_TIMEOUT = 4.0            # Max seconds of initial silence allowing user to formulate sentence
COMMAND_TRAILING_SILENCE = 0.85          # Reliable endpointing: 0.85s prevents cutting off multilingual speech with natural syllable pauses
COMMAND_MAX_RECORD_DURATION = 7.0        # Max duration cap allowing complete multi-clause commands

# Conversational Prompts
CONTINUOUS_PROMPT = "How can I help you?"
EXIT_RESPONSE = "Going back to wake-word listening."
COMMAND_PROMPT_MESSAGE = "I am listening for your command..."

# =====================================================================
# LOGGING SETTINGS
# =====================================================================
LOGS_DIR = PROJECT_ROOT / "logs"
VOICE_VERIFICATION_LOG_PATH = LOGS_DIR / "voice_verification.log"

# =====================================================================
# PHASE 5 MULTILINGUAL SETTINGS (English, Hindi, Kannada)
# =====================================================================
MULTILINGUAL_ENABLED = True
MULTILINGUAL_LANGUAGES = ["en", "hi", "kn"]
MULTILINGUAL_DEFAULT_LANGUAGE = "en"
MULTILINGUAL_MODEL_SIZE = "tiny"


