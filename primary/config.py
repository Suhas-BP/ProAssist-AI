"""
ProAssist AI - Phase 1 Configuration
Central configuration file for wake-word detection, speaker verification,
liveness check, and audio stream parameters.
"""

from pathlib import Path

# =====================================================================
# PATH CONFIGURATION
# =====================================================================
BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
DATA_DIR = BASE_DIR / "data"
VOICEPRINT_DIR = DATA_DIR / "voiceprint"

# Paths to models & stored user voiceprint
SPEAKER_MODEL_PATH = MODELS_DIR / "speaker_embedding.onnx"
CUSTOM_WAKE_WORD_MODEL_PATH = MODELS_DIR / "hey_agent.onnx"
VOICEPRINT_PATH = VOICEPRINT_DIR / "user_voiceprint.npy"
VOICEPRINT_META_PATH = VOICEPRINT_DIR / "voiceprint_meta.json"

# Ensure directories exist
VOICEPRINT_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# =====================================================================
# AUDIO STREAM CONFIGURATION
# =====================================================================
SAMPLE_RATE = 16000          # 16 kHz audio standard for speaker embedding & Whisper
CHANNELS = 1                 # Mono recording
CHUNK_SIZE = 1280            # 80ms buffer chunk (1280 samples @ 16kHz)
AUDIO_DEVICE_INDEX = None    # None for system default microphone, or specify device index

# =====================================================================
# WAKE-WORD CONFIGURATION
# =====================================================================
# Options:
# 1. "whisper_keyword": Spot exact phrase "Hey Agent" locally on CPU via faster-whisper INT8.
# 2. "openwakeword": Fast ONNX neural wake-word engine. Defaults to "hey_jarvis"
#    or a custom "models/hey_agent.onnx" model if supplied.
WAKE_WORD_ENGINE = "whisper_keyword"

# Wake phrase target (strict matching)
WAKE_PHRASE = "agent"

# OpenWakeWord specific settings
OPENWAKEWORD_MODEL_NAME = "hey_jarvis"   # "hey_jarvis" or path to custom "models/hey_agent.onnx"
OPENWAKEWORD_THRESHOLD = 0.5            # Activation confidence threshold (0.0 to 1.0)

# Local Whisper keyword spotter settings
WHISPER_MODEL_SIZE = "tiny.en"           # ~39MB model, fast local execution on CPU
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"
KEYWORD_SPOT_BUFFER_SECONDS = 2.0        # Sliding audio buffer window for keyword detection
KEYWORD_SPOT_INTERVAL_SECONDS = 0.35     # Fast interval between spotter inferences (0.35s)
KEYWORD_SPOT_ENERGY_THRESHOLD = 0.0055   # Calibrated speech gate for clear voice detection (ambient ~0.002-0.004, speech >= 0.0055)

# =====================================================================
# SPEAKER VERIFICATION & ENROLLMENT (PPT Slides 23 & 24)
# =====================================================================
# Cosine similarity threshold for authenticating the speaker.
# Calibrated for ResNet34 ONNX embedding with Kaldi 80-bin fbank:
# - Same speaker typical score: 0.82 to 0.90
# - Different speaker typical score: 0.15 to 0.35
# Configured threshold 0.50 provides reliable speaker authentication.
VOICE_SIMILARITY_THRESHOLD = 0.50

# Audio duration to capture right after wake word is detected.
# 4.0s gives the ResNet34 backbone more frames → better embedding quality.
AUTH_RECORD_DURATION = 4.0   # seconds

# Security lockout: how many consecutive failed auth attempts before
# the system enters a lockout period (prevents brute-force by imposters).
AUTH_MAX_ATTEMPTS = 3              # attempts before lockout
AUTH_LOCKOUT_SECONDS = 30          # seconds to refuse new wake-word activations

# Enrollment settings
ENROLLMENT_SAMPLES_COUNT = 3           # 3 to 5 voice samples as per PPT Slide 23
ENROLLMENT_SAMPLE_DURATION = 3.5       # seconds per sample

# Feature extraction parameters (Kaldi fbank standard for ResNet34)
NUM_MEL_BINS = 80
FRAME_LENGTH_MS = 25.0                 # 25 ms frame length (400 samples @ 16kHz)
FRAME_SHIFT_MS = 10.0                  # 10 ms frame shift (160 samples @ 16kHz)
PREEMPH_COEFF = 0.97                   # Standard Kaldi pre-emphasis
N_FFT = 512                            # Power of 2 >= 400
EMBEDDING_DIM = 256                    # Exact output dimension of speaker_embedding.onnx

# =====================================================================
# LIVENESS / ANTI-REPLAY CHALLENGE-RESPONSE (PPT Slide 24, Step 4)
# =====================================================================
# When True: After wake word is spotted, system issues a random challenge phrase
# (e.g. "blue elephant seven") and checks both speech content and voice embedding.
# When False: Directly verifies speaker embedding from the wake/follow-up utterance.
# Enabled by default for strong anti-spoofing protection.
ENABLE_LIVENESS = True

LIVENESS_RECORD_DURATION = 5.0          # Seconds to wait for challenge phrase (longer = more audio = better embedding)
LIVENESS_TEXT_ACCURACY_THRESHOLD = 0.50 # Minimum word-matching ratio (relaxed to handle accent/pace variation)
LIVENESS_SIMILARITY_THRESHOLD = 0.50    # Voice similarity required — matches VOICE_SIMILARITY_THRESHOLD


# =====================================================================
# AGENT FEEDBACK & RESPONSES
# =====================================================================
ENABLE_TTS = True                       # Use local pyttsx3 text-to-speech for voice feedback
TTS_RATE = 200                          # Fast, natural speech rate (words per minute)
WAKE_CONFIRMATION_PHRASE = "How can I help you?"
LIVENESS_PROMPT_PREFIX = "Please repeat:"

