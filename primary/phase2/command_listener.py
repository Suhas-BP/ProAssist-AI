"""
Command Listener Module for ProAssist AI Phase 2
Captures voice commands from the user and transcribes them into text
using the local offline faster-whisper engine.
Supports model reuse, dynamic endpointing (VAD), and text normalization.
"""

import sys
import re
import time
from pathlib import Path
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from wake_word.audio_stream import record_audio
from phase2 import config as p2_config


class CommandListener:
    """Listens for and transcribes spoken voice commands locally."""

    def __init__(self, model=None, model_size: str = None,
                 device: str = config.WHISPER_DEVICE,
                 compute_type: str = config.WHISPER_COMPUTE_TYPE,
                 multilingual: bool = getattr(p2_config, "MULTILINGUAL_ENABLED", True)):
        if model_size is None:
            model_size = getattr(p2_config, "MULTILINGUAL_MODEL_SIZE", "tiny") if multilingual else config.WHISPER_MODEL_SIZE
        self.multilingual = multilingual
        self.last_whisper_info = {}
        if model is not None:
            self.model = model
            print("[CommandListener] Reusing initialized Whisper model instance.")
        else:
            from faster_whisper import WhisperModel
            print(f"[CommandListener] Initializing Multilingual Whisper model ({model_size}) on {device} ({compute_type})...")
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        print("[CommandListener] Command listener ready.")

    @staticmethod
    def normalize_text(text: str) -> str:
        """
        Normalizes transcribed text by expanding contractions,
        stripping punctuation, and trimming extra spaces.
        Preserves Indic script (Hindi/Kannada) without applying English-only rules.
        """
        if not text:
            return ""
        t = text.strip()

        # Check if text is predominantly Indic script (Devanagari or Kannada)
        # and skip English-specific normalization to preserve the script for correct routing
        indic_count = sum(
            1 for ch in t
            if 0x0900 <= ord(ch) <= 0x097F   # Devanagari (Hindi)
            or 0x0C80 <= ord(ch) <= 0x0CFF   # Kannada
        )
        if indic_count > 0:
            # For Indic text: only strip trailing punctuation and collapse spaces
            t = re.sub(r"[?!.,;:\"]+", " ", t)
            return " ".join(t.split())

        # English normalization
        replacements = [
            (r"\bwhat's\b", "what is"),
            (r"\bthat's\b", "that is"),
            (r"\btoday's\b", "todays"),
            (r"\bit's\b", "it is"),
            (r"\bcan't\b", "cannot"),
            (r"\bi'm\b", "i am"),
        ]
        for pat, repl in replacements:
            t = re.sub(pat, repl, t, flags=re.IGNORECASE)
        # Strip trailing and sentence punctuation
        t = re.sub(r"[?!.,;:\"]+", " ", t)
        return " ".join(t.split())


    def record_command_with_vad(
        self,
        max_duration: float = p2_config.COMMAND_MAX_RECORD_DURATION,
        silence_timeout: float = p2_config.COMMAND_SILENCE_TIMEOUT,
        trailing_silence: float = p2_config.COMMAND_TRAILING_SILENCE,
        energy_threshold: float = p2_config.COMMAND_ENERGY_THRESHOLD,
    ) -> np.ndarray:
        """
        Dynamically records command audio using Voice Activity Detection:
        - Starts listening.
        - If speech doesn't begin within silence_timeout, aborts to avoid hanging.
        - Once speech begins, records until trailing_silence seconds of silence is detected
          or max_duration is reached.
        """
        import pyaudio

        chunk_size = 1024
        sample_rate = config.SAMPLE_RATE
        p = pyaudio.PyAudio()

        stream = None
        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=config.CHANNELS,
                rate=sample_rate,
                input=True,
                input_device_index=config.AUDIO_DEVICE_INDEX,
                frames_per_buffer=chunk_size,
            )

            frames = []
            speech_started = False
            last_speech_time = None
            start_time = time.time()
            baseline_noise = energy_threshold
            chunks_read = 0

            while True:
                now = time.time()
                elapsed = now - start_time
                if elapsed >= max_duration:
                    break

                try:
                    data = stream.read(chunk_size, exception_on_overflow=False)
                except IOError:
                    continue

                chunk_int16 = np.frombuffer(data, dtype=np.int16)
                chunk_f32 = chunk_int16.astype(np.float32) / 32768.0
                energy = float(np.sqrt(np.mean(chunk_f32 ** 2)))
                peak = float(np.max(np.abs(chunk_f32)))

                frames.append(chunk_f32)
                chunks_read += 1

                # Dynamically calibrate baseline noise floor during first 3 chunks (~190ms)
                if chunks_read <= 3 and energy < 0.005:
                    baseline_noise = max(baseline_noise, energy * 1.15)

                active_threshold = max(energy_threshold, baseline_noise)

                # Voice activity detection: check energy threshold or consonant peak
                if energy >= active_threshold or peak >= 0.018:
                    if not speech_started:
                        speech_started = True
                    last_speech_time = now
                else:
                    if not speech_started:
                        if elapsed >= silence_timeout:
                            break
                    else:
                        if (now - last_speech_time) >= trailing_silence:
                            break

            # Safety fallback: if speech_started wasn't flagged but speech levels exist in frames, keep audio
            if not speech_started:
                has_any_speech = any(float(np.max(np.abs(f))) >= 0.018 or float(np.sqrt(np.mean(f ** 2))) >= energy_threshold for f in frames)
                if not has_any_speech:
                    return np.zeros(0, dtype=np.float32)

            if not frames:
                return np.zeros(0, dtype=np.float32)

            return np.concatenate(frames)

        except Exception as e:
            print(f"[CommandListener] VAD capture error: {e}. Falling back to standard record.")
            return record_audio(duration_seconds=p2_config.COMMAND_RECORD_DURATION)
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            try:
                p.terminate()
            except Exception:
                pass

    @staticmethod
    def _has_unsupported_foreign_script(text: str) -> bool:
        """Checks if text contains unsupported foreign scripts (e.g. Thai, Japanese, Chinese, Cyrillic)."""
        if not text:
            return False
        for ch in text:
            cp = ord(ch)
            if cp > 0x024F:
                is_devanagari = 0x0900 <= cp <= 0x097F
                is_kannada = 0x0C80 <= cp <= 0x0CFF
                is_punct = 0x2000 <= cp <= 0x206F
                if not (is_devanagari or is_kannada or is_punct):
                    return True
        return False

    def transcribe_audio(self, audio: np.ndarray) -> str:
        """
        Transcribes a 1D float32 audio array sampled at 16 kHz.
        Constrains decoding strictly to ProAssist supported languages: English (en), Hindi (hi), and Kannada (kn).
        Returns:
            clean_text: Stripped, recognized text.
        """
        if len(audio) == 0:
            return ""

        energy = float(np.sqrt(np.mean(audio ** 2)))
        if energy < 0.0003:
            print(f"[CommandListener] Audio energy negligible ({energy:.5f}). No speech detected.")
            return ""

        # Remove DC offset and apply AGC peak normalization for clear voice recognition
        # Only apply AGC when there is meaningful speech energy (peak > 0.05) to avoid
        # amplifying ambient noise which causes Whisper to hallucinate random words
        audio_proc = audio.copy()
        audio_proc = audio_proc - float(np.mean(audio_proc))
        max_peak = float(np.max(np.abs(audio_proc)))
        if max_peak > 0.05:
            scale = min(0.70 / max_peak, 8.0)
            audio_proc = (audio_proc * scale).astype(np.float32)

        target_lang = "en"
        if self.multilingual:
            try:
                # Fast language detection on audio — use vad_filter=False so that
                # quiet Indic speech is not discarded as noise before detection
                det_lang, prob, all_probs = self.model.detect_language(audio_proc, vad_filter=False)
                supported = {"en", "hi", "kn"}
                filtered = {k: v for k, v in all_probs if k in supported}
                best_lang = max(filtered.keys(), key=lambda k: filtered[k]) if filtered else "en"

                # Only switch to Hindi or Kannada if significant confidence and exceeds English
                if best_lang in ("hi", "kn") and filtered.get(best_lang, 0) > 0.35 and filtered.get(best_lang, 0) > filtered.get("en", 0):
                    target_lang = best_lang
                else:
                    target_lang = "en"
            except Exception as e:
                print(f"[CommandListener] Language detection warning: {e}. Defaulting to 'en'.")
                target_lang = "en"
        else:
            target_lang = getattr(p2_config, "COMMAND_LANGUAGE", "en")


        try:
            cmd_prompt = "Word, Excel, PowerPoint, Paint, Settings, Camera, Notepad, Chrome, YouTube, Calculator, File Explorer, write, type, open, search, exit, goodbye, thank you, summarize, kholo, maadi, tereyiri."
            cmd_hotwords = "word excel powerpoint paint settings camera notepad chrome youtube calculator explorer kholo maadi tereyiri"
            segments, info = self.model.transcribe(
                audio_proc,
                beam_size=p2_config.COMMAND_WHISPER_BEAM_SIZE,
                language=target_lang,
                vad_filter=False,
                initial_prompt=cmd_prompt,
                hotwords=cmd_hotwords
            )
            valid_segments = []
            for seg in segments:
                # Discard hallucinated or low-confidence segments on near-silence/trailing noise
                no_speech = getattr(seg, "no_speech_prob", 0.0)
                avg_logprob = getattr(seg, "avg_logprob", 0.0)
                if no_speech > 0.65 or avg_logprob < -1.2:
                    continue
                valid_segments.append(seg.text)

            text = " ".join(valid_segments).strip()

            # Safety fallback: If Whisper somehow still produced unsupported foreign scripts (Thai, Japanese, etc.)
            # immediately re-decode with language="en"
            if self._has_unsupported_foreign_script(text):
                print(f"[CommandListener] Foreign script '{text}' detected. Re-decoding strictly in English...")
                segments, _ = self.model.transcribe(
                    audio_proc,
                    beam_size=p2_config.COMMAND_WHISPER_BEAM_SIZE,
                    language="en",
                    vad_filter=False,
                    initial_prompt=cmd_prompt,
                    hotwords=cmd_hotwords
                )
                valid_segments = [s.text for s in segments if getattr(s, "no_speech_prob", 0.0) <= 0.65]
                text = " ".join(valid_segments).strip()
                target_lang = "en"

            self.last_whisper_info = {
                "language": target_lang,
                "language_probability": getattr(info, "language_probability", 1.0)
            }
            return text
        except Exception as e:
            print(f"[CommandListener] Transcription error: {e}")
            return ""

    def listen_and_transcribe(self, duration_seconds: float = None) -> str:
        """
        Records microphone audio with dynamic endpointing and transcribes the speech.
        """
        print(f"\n[CommandListener] Listening for command... Speak now!")
        try:
            if duration_seconds is not None:
                audio_data = record_audio(duration_seconds=duration_seconds)
            else:
                audio_data = self.record_command_with_vad()

            if len(audio_data) == 0:
                print("[CommandListener] No speech audio detected.")
                return ""

            captured_s = len(audio_data) / config.SAMPLE_RATE
            rms = float(np.sqrt(np.mean(audio_data ** 2)))
            print(f"[CommandListener] Audio captured: {captured_s:.2f}s (RMS: {rms:.4f}). Transcribing...")
            raw_text = self.transcribe_audio(audio_data)
            normalized = self.normalize_text(raw_text)
            print(f"[CommandListener] Recognized Text: \"{normalized}\"")
            return normalized
        except Exception as e:
            print(f"[CommandListener] Recording failed: {e}")
            return ""
