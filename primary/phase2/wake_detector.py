"""
Phase 2 Wake-Word Detector with Diagnostic Telemetry
Subclasses Phase 1 WhisperKeywordDetector to provide real-time diagnostic
logging without altering Phase 1 implementation or strict phrase matching.
"""

import sys
import time
from pathlib import Path
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from wake_word.detector import WhisperKeywordDetector
from phase2 import config as p2_config


class Phase2WakeDetector(WhisperKeywordDetector):
    """
    Phase 2 Wake-Word Detector.
    Preserves strict contiguous "Hey Agent" matching and INT8 Whisper inference
    while adding diagnostic tracing for audio stream status, RMS energy gating,
    and transcription telemetry.
    """

    def __init__(self,
                 target_phrase: str = config.WAKE_PHRASE,
                 buffer_seconds: float = p2_config.WAKE_BUFFER_SECONDS,
                 check_interval: float = p2_config.WAKE_CHECK_INTERVAL,
                 energy_threshold: float = p2_config.WAKE_ENERGY_THRESHOLD,
                 model = None):
        if model is not None:
            # Reuse existing WhisperModel instance
            self.target_phrase = target_phrase.lower().strip()
            self.buffer_seconds = buffer_seconds
            self.check_interval = check_interval
            self.energy_threshold = energy_threshold
            self.sample_rate = config.SAMPLE_RATE
            self.strict_regex = config.WAKE_PHRASE
            import re
            self.strict_regex = re.compile(r"\b(hey|hay)\s+agent\b", re.IGNORECASE)
            self.model = model
            self.max_buffer_samples = int(self.buffer_seconds * self.sample_rate)
            self.audio_buffer = np.zeros(self.max_buffer_samples, dtype=np.float32)
            self.last_check_time = time.time()
            self.new_samples_since_last_check = 0
            self.last_chunk_rms = 0.0
            print(f"[WakeWord] Reusing Whisper model for keyword detection (buffer={buffer_seconds}s, interval={check_interval}s, thresh={energy_threshold})")
        else:
            super().__init__(
                target_phrase=target_phrase,
                buffer_seconds=buffer_seconds,
                check_interval=check_interval,
                energy_threshold=energy_threshold
            )
            self.last_chunk_rms = 0.0

    def is_detected(self, chunk: np.ndarray) -> bool:
        """
        Processes an incoming int16 audio chunk with diagnostic tracing.
        """
        chunk_f32 = (chunk / 32768.0).astype(np.float32)
        chunk_len = len(chunk_f32)
        self.last_chunk_rms = float(np.sqrt(np.mean(chunk_f32 ** 2)))

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

        # 2. Require sufficient new audio data before inference
        min_new_samples = int(self.sample_rate * 0.3)
        if self.new_samples_since_last_check < min_new_samples:
            return False

        self.last_check_time = current_time
        self.new_samples_since_last_check = 0

        # 3. Energy threshold gating: check both peak sub-window and buffer RMS
        # This prevents quiet padding from diluting speech while filtering background silence
        buf_rms = float(np.sqrt(np.mean(self.audio_buffer ** 2)))
        peak_window_rms = max(float(np.sqrt(np.mean(w ** 2))) for w in np.array_split(self.audio_buffer, 4))
        has_speech = (peak_window_rms >= self.energy_threshold) or (buf_rms >= self.energy_threshold)

        if not has_speech:
            return False

        # Step 4: Show when speech is detected
        print(f"[WakeWord DEBUG] Speech detected | Peak RMS: {peak_window_rms:.4f} | Buffer RMS: {buf_rms:.4f} (threshold: {self.energy_threshold:.3f})")

        # Step 5: Run fast INT8 Whisper transcription (vad_filter=False to prevent dropping short wake phrases)
        try:
            segments, _ = self.model.transcribe(
                self.audio_buffer,
                beam_size=1,
                language="en",
                vad_filter=False
            )
            raw_transcript = " ".join(seg.text for seg in segments).strip()
            print(f"[WakeWord DEBUG] Whisper heard: \"{raw_transcript}\"")

            # Step 6: Show whether that transcription is checked against "hey agent"
            is_match = self.match_strict_phrase(raw_transcript)
            print(f"[WakeWord DEBUG] Checking strict match: \"{raw_transcript}\" against \"hey agent\" -> MATCH: {is_match}")

            # Step 7: Wake detector returns True
            if is_match:
                print(f"[WakeWord MATCH] Strict wake word 'hey agent' detected! Wake detector returned: TRUE")
                self.reset()
                return True
        except Exception as e:
            print(f"[WakeWord DEBUG] Whisper inference error: {e}")

        return False

    def match_strict_phrase(self, text: str) -> bool:
        """
        Enforces strict contiguous match for 'hey agent' / 'hay agent'.
        """
        if not text:
            return False
        import re
        clean_text = re.sub(r"[^\w\s]", " ", text.lower())
        if self.strict_regex.search(clean_text):
            return True
        return super().match_strict_phrase(text)

