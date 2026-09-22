"""
Wake-Word Detection Module for ProAssist AI
Supports dual-mode local wake-word detection:
1. Whisper Keyword Spotter: Strict on-device contiguous "Hey Agent" matching using faster-whisper.
2. OpenWakeWord: Neural ONNX detector supporting built-in models (e.g. hey_jarvis) or
   a custom trained models/hey_agent.onnx when available.
"""

import os
import time
import re
from pathlib import Path
import numpy as np
import config


class BaseWakeWordDetector:
    """Base class defining the Wake-Word Detector interface."""

    def is_detected(self, chunk: np.ndarray) -> bool:
        raise NotImplementedError

    def reset(self):
        pass

    def get_last_detected_audio(self):
        return None


class WhisperKeywordDetector(BaseWakeWordDetector):
    """
    On-device keyword spotter using local faster-whisper (tiny.en INT8 on CPU).
    Enforces STRICT wake phrase matching for "Agent".
    Includes energy gating and sample buffering to avoid unnecessary Whisper inference.
    """

    def __init__(self, target_phrase: str = config.WAKE_PHRASE,
                 buffer_seconds: float = config.KEYWORD_SPOT_BUFFER_SECONDS,
                 check_interval: float = config.KEYWORD_SPOT_INTERVAL_SECONDS,
                 energy_threshold: float = config.KEYWORD_SPOT_ENERGY_THRESHOLD):
        from faster_whisper import WhisperModel

        self.target_phrase = target_phrase.lower().strip()
        self.buffer_seconds = buffer_seconds
        self.check_interval = check_interval
        self.energy_threshold = energy_threshold
        self.sample_rate = config.SAMPLE_RATE

        # Regex for contiguous salutations before 'agent'
        self.strict_regex = re.compile(r"\b(hey|hay|hi|hello|ok|okay)?\s*agent\b", re.IGNORECASE)

        print(f"[WakeWord] Loading local Whisper keyword spotter ({config.WHISPER_MODEL_SIZE})...")
        self.model = WhisperModel(
            config.WHISPER_MODEL_SIZE,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE
        )

        self.max_buffer_samples = int(self.buffer_seconds * self.sample_rate)
        self.audio_buffer = np.zeros(self.max_buffer_samples, dtype=np.float32)
        self.last_check_time = time.time()
        self.new_samples_since_last_check = 0
        self.last_detected_audio = None

        print(f"[WakeWord] Whisper keyword spotter ready. Strict target phrase: \"{self.target_phrase}\"")

    def normalize_transcript(self, text: str) -> str:
        """Removes punctuation and normalizes spacing."""
        clean = re.sub(r"[^\w\s]", " ", text)
        return " ".join(clean.lower().split())

    def match_strict_phrase(self, text: str) -> bool:
        """
        Validates that the wake phrase appears strictly as a wake-up invocation.
        When target is 'agent':
          - Triggers on standalone or vocative 'Agent' (e.g. 'Agent', 'agent!', 'Agent please listen').
          - Allows optional salutations ('Hey Agent', 'Hi Agent', 'Hello Agent', 'Okay Agent', 'hay agent').
          - Strictly rejects non-wake-word sentences containing 'agent'
            (e.g. 'Hey, what did the insurance agent say?', 'secret agent', 'travel agent', 'an agent', 'the agent').
        """
        if not text:
            return False

        clean = re.sub(r"[^\w\s]", " ", text)
        words = clean.lower().split()
        if not words:
            return False

        target = self.target_phrase.lower()
        if target == "agent":
            if "agent" not in words and "agents" not in words:
                return False

            clean_str = " ".join(words)

            # 1. Reject compound nouns / modifiers before 'agent' / 'agents'
            distractor_patterns = [
                r"\b(insurance|secret|travel|estate|real\s+estate|booking|clearing|sales|support|special|double|free|field|fbi|cia|smart|software|autonomous)\s+agents?\b",
                r"\b(an|the|a|this|that|my|your|his|her|our|their|each|every|some|any|no)\s+agents?\b",
                r"\bwhat\s+(is|does|are)\s+(an?|the)?\s*agents?\b",
                r"\b(call|contact|hire|meet|ask|email|phone|find|tell)\s+(the|an?|my|your|our|their)\s+agents?\b",
                r"\b(is|was|are|were|be|being|been)\s+an?\s+agents?\b",
            ]
            for dp in distractor_patterns:
                if re.search(dp, clean_str, re.IGNORECASE):
                    return False

            # 2. Allowed and disallowed contextual tokens
            allowed_salutations = {"hey", "hay", "hi", "hello", "ok", "okay", "yo", "there"}
            disallowed_prev = {
                "the", "a", "an", "this", "that", "these", "those",
                "my", "your", "his", "her", "our", "their", "any", "some", "every", "each", "no",
                "as", "by", "for", "with", "from", "to", "at", "about", "of", "like", "than",
                "is", "was", "are", "were", "be", "being", "been",
                "call", "calling", "contact", "hire", "find", "become", "becomes"
            }

            # 3. Verify contextual invocation
            for idx, w in enumerate(words):
                if w in ("agent", "agents"):
                    # Case A: First word in utterance (e.g. "Agent", "Agent open chrome")
                    if idx == 0:
                        return True

                    prev1 = words[idx - 1]

                    # Case B: Preceded by salutation (e.g. "Hey Agent", "... problem hey agent")
                    if prev1 in allowed_salutations:
                        return True

                    # Case C: Preceded by "Hey there Agent"
                    if idx >= 2 and words[idx - 2] in allowed_salutations and prev1 == "there":
                        return True

                    # Case D: Preceded by conversational filler ("um agent", "so agent", "please agent")
                    if prev1 in {"um", "uh", "ah", "oh", "so", "well", "please", "yes", "yeah"}:
                        return True

                    # Case E: Preceded by general speech, not a modifier or determiner
                    if prev1 not in disallowed_prev:
                        return True

            return False
        else:
            # Fallback for other phrases (e.g. "hey agent")
            pattern = rf"\b{re.escape(target)}\b"
            return bool(re.search(pattern, " ".join(words), re.IGNORECASE))

    def is_detected(self, chunk: np.ndarray) -> bool:
        """
        Processes an incoming int16 chunk.
        Runs Whisper inference only when:
        1. Minimum time interval has elapsed.
        2. Sufficient new audio data has been ingested.
        3. Buffer energy exceeds background silence threshold.
        """
        if chunk is None or len(chunk) == 0:
            return False

        chunk_f32 = (chunk / 32768.0).astype(np.float32)
        chunk_len = len(chunk_f32)
        if chunk_len == 0:
            return False

        # Slide ring buffer
        if chunk_len >= self.max_buffer_samples:
            self.audio_buffer[:] = chunk_f32[-self.max_buffer_samples:]
        else:
            self.audio_buffer = np.roll(self.audio_buffer, -chunk_len)
            self.audio_buffer[-chunk_len:] = chunk_f32

        self.new_samples_since_last_check += chunk_len
        current_time = time.time()

        # 1. Rate limiting
        if (current_time - self.last_check_time) < self.check_interval:
            return False

        # 2. Avoid running on identical / static buffer without enough new audio
        min_new_samples = int(self.sample_rate * 0.2)  # 200ms of new audio for fast response
        if self.new_samples_since_last_check < min_new_samples:
            return False

        self.last_check_time = current_time
        self.new_samples_since_last_check = 0

        # 3. Energy threshold gating: check sub-window RMS, buffer RMS, and peak amplitude
        # Calibrated to clearly accept soft/normal conversational speech without triggering on ambient noise
        buf_rms = float(np.sqrt(np.mean(self.audio_buffer ** 2)))
        peak = float(np.max(np.abs(self.audio_buffer)))
        sub_rms = max(float(np.sqrt(np.mean(w ** 2))) for w in np.array_split(self.audio_buffer, 4))
        
        has_speech = (sub_rms >= self.energy_threshold) or (buf_rms >= self.energy_threshold) or (peak >= max(0.018, self.energy_threshold * 2.0))
        if not has_speech:
            return False

        # Diagnostic audio levels when speech/sound is detected
        effective_rms = max(sub_rms, buf_rms)
        print(f"[Mic DEBUG] RMS={effective_rms:.4f} Peak={peak:.4f} Samples={len(self.audio_buffer)}")
        print(f"[WakeWord DEBUG] Audio received: {self.buffer_seconds:.2f}s")

        # DC offset removal and Automatic Gain Control (AGC) peak normalization:
        # Ensures Whisper gets clear, normalized audio regardless of microphone hardware gain
        audio_proc = self.audio_buffer.copy()
        audio_proc = audio_proc - float(np.mean(audio_proc))
        max_peak = float(np.max(np.abs(audio_proc)))
        if max_peak > 0.003:
            gain_factor = min(0.70 / max_peak, 8.0)
            audio_proc = (audio_proc * gain_factor).astype(np.float32)

        # Run fast INT8 Whisper transcription on local CPU with neural VAD filter
        try:
            segments, _ = self.model.transcribe(
                audio_proc,
                beam_size=1,
                language="en",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=150, threshold=0.35),
                condition_on_previous_text=False,
                hotwords="agent hey agent"
            )
            raw_transcript = " ".join(seg.text for seg in segments).strip()
            print(f'[WakeWord DEBUG] Whisper transcript: "{raw_transcript}"')

            if self.match_strict_phrase(raw_transcript):
                print(f"[WakeWord DEBUG] Strict match: TRUE")
                print(f"[WakeWord] STRICT MATCH DETECTED: \"{raw_transcript}\"")
                self.last_detected_audio = self.audio_buffer.copy()
                self.reset()
                return True
            else:
                print(f"[WakeWord DEBUG] No wake word detected")
        except Exception as e:
            print(f"[WakeWord ERROR] Whisper inference failed: {e}")
        finally:
            self.last_check_time = time.time()

        return False

    def get_last_detected_audio(self) -> np.ndarray:
        """Returns a copy of the audio buffer that triggered wake detection."""
        if self.last_detected_audio is not None:
            return self.last_detected_audio.copy()
        return self.audio_buffer.copy()

    def reset(self):
        """Clears the audio buffer."""
        self.audio_buffer.fill(0)
        self.last_check_time = time.time()
        self.new_samples_since_last_check = 0


class OpenWakeWordDetector(BaseWakeWordDetector):
    """
    Wake-word detector using openWakeWord ONNX neural network.
    Supports built-in models (e.g. hey_jarvis) or custom models/hey_agent.onnx.
    """

    def __init__(self, model_name: str = config.OPENWAKEWORD_MODEL_NAME,
                 threshold: float = config.OPENWAKEWORD_THRESHOLD):
        from openwakeword.model import Model

        self.model_name = model_name
        self.threshold = threshold

        # Check if the requested model is "hey_agent" or points to a custom file
        custom_target = Path(model_name)
        if not custom_target.is_file() and (model_name == "hey_agent" or model_name.endswith("hey_agent.onnx")):
            custom_path = config.CUSTOM_WAKE_WORD_MODEL_PATH
            if not custom_path.is_file():
                raise FileNotFoundError(
                    f"Custom wake-word model '{custom_path.name}' not found at: {custom_path}\n"
                    "OpenWakeWord does NOT bundle a pre-trained 'Hey Agent' model out-of-the-box.\n"
                    "To detect 'Hey Agent', either:\n"
                    "  1. Set WAKE_WORD_ENGINE = 'whisper_keyword' in config.py (local on-device exact matching).\n"
                    "  2. Or train a custom 'hey_agent.onnx' model using openWakeWord's Colab notebook "
                    f"and place it at {custom_path}."
                )
            model_target = str(custom_path)
        elif custom_target.is_file():
            model_target = str(custom_target)
        else:
            model_target = model_name

        print(f"[WakeWord] Initializing OpenWakeWord model: '{model_target}'...")
        self.model = Model(wakeword_models=[model_target])
        self.active_model_key = list(self.model.models.keys())[0] if self.model.models else model_name
        print(f"[WakeWord] OpenWakeWord loaded key '{self.active_model_key}'. Trigger threshold: {self.threshold}")

    def is_detected(self, chunk: np.ndarray) -> bool:
        predictions = self.model.predict(chunk)
        for name, score in predictions.items():
            if score >= self.threshold:
                print(f"[WakeWord] Detected '{name}' (Confidence: {score:.2f})")
                self.reset()
                return True
        return False

    def reset(self):
        self.model.reset()


def get_wake_word_detector(engine_type: str = None) -> BaseWakeWordDetector:
    engine = engine_type or config.WAKE_WORD_ENGINE
    if engine == "openwakeword":
        return OpenWakeWordDetector()
    elif engine == "whisper_keyword":
        return WhisperKeywordDetector()
    else:
        raise ValueError(f"Unknown wake-word engine: '{engine}'. Choose 'whisper_keyword' or 'openwakeword'.")
