"""
Voice Authentication and Verifier Module for ProAssist AI
Validates live speaker audio against enrolled voiceprint using
cosine similarity and a configurable threshold (PPT Slide 24).
"""

from pathlib import Path
import json
import numpy as np
import config
from wake_word.audio_stream import record_audio
from voice_auth.model import SpeakerEmbeddingModel, compute_cosine_similarity


class VoiceVerifier:
    def __init__(self, voiceprint_path: Path = config.VOICEPRINT_PATH,
                 threshold: float = config.VOICE_SIMILARITY_THRESHOLD):
        self.voiceprint_path = Path(voiceprint_path)
        self.threshold = threshold
        self.model = SpeakerEmbeddingModel()
        self.enrolled_voiceprint = None
        self.enrolled_meta = {}

        self.load_voiceprint()

    def is_enrolled(self) -> bool:
        return self.voiceprint_path.exists()

    def load_voiceprint(self) -> bool:
        if not self.voiceprint_path.exists():
            self.enrolled_voiceprint = None
            return False

        self.enrolled_voiceprint = np.load(self.voiceprint_path)
        norm = np.linalg.norm(self.enrolled_voiceprint)
        if abs(norm - 1.0) > 1e-3 and norm > 0:
            self.enrolled_voiceprint = self.enrolled_voiceprint / norm

        if config.VOICEPRINT_META_PATH.exists():
            try:
                with open(config.VOICEPRINT_META_PATH, "r", encoding="utf-8") as f:
                    self.enrolled_meta = json.load(f)
            except Exception:
                self.enrolled_meta = {}

        return True

    def verify_audio(self, audio: np.ndarray) -> tuple[bool, float, dict]:
        if self.enrolled_voiceprint is None:
            if not self.load_voiceprint():
                return False, 0.0, {"error": "No voiceprint enrolled"}

        live_emb, diag = self.model.generate_embedding(audio, apply_vad=True)
        similarity = compute_cosine_similarity(live_emb, self.enrolled_voiceprint)
        is_authenticated = bool(similarity >= self.threshold)

        details = {
            "authenticated": is_authenticated,
            "similarity": round(similarity, 4),
            "threshold": self.threshold,
            "user": self.enrolled_meta.get("user_name", "User"),
            "diagnostics": diag
        }

        return is_authenticated, similarity, details

    def record_and_verify(self, duration_seconds: float = config.AUTH_RECORD_DURATION) -> tuple[bool, float, dict]:
        audio = record_audio(duration_seconds=duration_seconds)
        return self.verify_audio(audio)
