"""
Challenge-Response Liveness & Anti-Replay Module for ProAssist AI
Defeats pre-recorded replay attacks by asking the user to repeat a
randomized phrase (PPT Slide 24, Step 4), verifying both content (ASR)
and speaker identity (voice embedding).
"""

import random
import re
import pyttsx3
import numpy as np
import config
from wake_word.audio_stream import record_audio
from voice_auth.verifier import VoiceVerifier


class LivenessChecker:
    """Challenge-Response Anti-Replay Verifier."""

    def __init__(self, verifier: VoiceVerifier = None):
        self.verifier = verifier or VoiceVerifier()

        # Phonetically distinct word pools for random challenge generation
        self.colors = ["blue", "green", "red", "yellow", "orange", "purple", "golden", "silver"]
        self.nouns = ["elephant", "tiger", "falcon", "dolphin", "eagle", "panther", "dragon"]
        self.numbers = ["seven", "twelve", "twenty one", "forty two", "nine", "fifteen", "eight"]

        # Local Whisper model for offline challenge transcription
        from faster_whisper import WhisperModel
        print(f"[Liveness] Initializing local Whisper ASR for challenge verification...")
        self.asr_model = WhisperModel(
            config.WHISPER_MODEL_SIZE,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE
        )
        print("[Liveness] Challenge-response engine initialized.")

    def generate_challenge(self) -> str:
        """Generates a randomized 3-word challenge phrase (e.g., 'blue elephant seven')."""
        c = random.choice(self.colors)
        n = random.choice(self.nouns)
        num = random.choice(self.numbers)
        return f"{c} {n} {num}"

    def speak_prompt(self, text: str):
        """Speaks a prompt aloud via pyttsx3 if enabled."""
        if config.ENABLE_TTS:
            try:
                if not hasattr(self, "_tts_engine") or self._tts_engine is None:
                    self._tts_engine = pyttsx3.init()
                engine = self._tts_engine
                engine.setProperty("rate", getattr(config, "TTS_RATE", 200))
                engine.say(text)
                engine.runAndWait()
            except Exception as e:
                print(f"[Liveness] TTS prompt error: {e}")
                self._tts_engine = None

    def _normalize_text(self, text: str) -> list[str]:
        """Normalizes and tokenizes text into lowercase word tokens."""
        clean = re.sub(r"[^a-zA-Z0-9\s]", " ", text).lower()
        return [w.strip() for w in clean.split() if w.strip()]

    def verify_liveness_challenge(self, challenge_phrase: str = None,
                                  duration: float = config.LIVENESS_RECORD_DURATION) -> tuple[bool, dict]:
        """
        Issues challenge, records response, and verifies both phrase content and speaker identity.
        Returns:
            (passed: bool, report: dict)
        """
        challenge = challenge_phrase or self.generate_challenge()
        prompt_message = f"{config.LIVENESS_PROMPT_PREFIX} {challenge}"

        print("\n" + "=" * 60)
        print("          SECURITY LIVENESS CHALLENGE")
        print(f"  Target Phrase: \"{challenge.upper()}\"")
        print("=" * 60)

        # Announce challenge to user
        self.speak_prompt(prompt_message)
        print(f">> Please speak the phrase now ({duration}s)...")

        # Record user response
        audio_response = record_audio(duration_seconds=duration)
        print(">> Captured response. Performing dual verification...")

        # 1. Content Verification (ASR via faster-whisper)
        segments, _ = self.asr_model.transcribe(
            audio_response,
            beam_size=1,
            language="en"
        )
        transcribed_text = " ".join(seg.text for seg in segments).strip()
        spoken_tokens = self._normalize_text(transcribed_text)
        expected_tokens = self._normalize_text(challenge)

        # Calculate word overlap ratio
        matched_tokens = [tok for tok in expected_tokens if tok in spoken_tokens]
        content_accuracy = len(matched_tokens) / max(len(expected_tokens), 1)
        content_passed = bool(content_accuracy >= config.LIVENESS_TEXT_ACCURACY_THRESHOLD)

        # 2. Speaker Verification on the exact same audio
        spk_auth, spk_sim, spk_details = self.verifier.verify_audio(audio_response)
        spk_passed = bool(spk_sim >= config.LIVENESS_SIMILARITY_THRESHOLD)

        overall_passed = bool(content_passed and spk_passed)

        report = {
            "overall_passed": overall_passed,
            "challenge_phrase": challenge,
            "transcription": transcribed_text,
            "content_accuracy": round(content_accuracy, 2),
            "content_passed": content_passed,
            "speaker_similarity": round(spk_sim, 4),
            "speaker_passed": spk_passed,
            "matched_words": matched_tokens
        }

        print(f"  - Spoken Transcript   : \"{transcribed_text}\"")
        print(f"  - Content Match       : {content_accuracy * 100:.0f}% -> {'PASS' if content_passed else 'FAIL'}")
        print(f"  - Voice Similarity    : {spk_sim:.4f} -> {'PASS' if spk_passed else 'FAIL'}")
        print(f"  - Liveness Outcome    : {'ACCESS GRANTED' if overall_passed else 'ACCESS DENIED'}")
        print("=" * 60 + "\n")

        return overall_passed, report
