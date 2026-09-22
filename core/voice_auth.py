"""Local primary-user voice enrollment and speaker verification.

Wake-word detection only starts this verification step. Authorization requires
the enrolled speaker embedding to pass the primary project's neural verifier.
Raw recordings are discarded after embeddings are generated.
"""
from __future__ import annotations

import json
import importlib.util
import sys
import threading
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000
# Long enough for the longest registration sentence, with a small pause after
# the user finishes. Capture is still local and fixed-length for stable VAD.
SAMPLE_SECONDS = 6
SAMPLES_REQUIRED = 3
MATCH_THRESHOLD = 0.72
REGISTRATION_SENTENCES = (
    "Hello, I’m your voice assistant. Please remember my voice for secure authentication.",
    "I am registering my voice with Pro-Assist AI for secure authentication.",
    "Unlock the workspace using my registered voice.",
)

AUTHENTICATION_SENTENCES = (
    "Silver clouds drift quietly.",
    "Morning light fills rooms.",
    "Dreams shape future journeys.",
    "Gentle winds cross mountains.",
    "Bright stars guide travelers.",
    "Curious minds discover possibilities.",
    "Quiet moments inspire creativity.",
    "Golden leaves fall softly.",
    "Swift rivers cross valleys.",
    "Kind words create connections.",
    "Fresh ideas spark change.",
    "Distant horizons invite exploration.",
    "Clever foxes navigate forests.",
    "Blue waves touch shores.",
    "Peaceful mornings bring clarity.",
)


class VoiceAuthenticator:
    def __init__(self, path: Path | None = None):
        base = Path(__file__).resolve().parent.parent
        self.path = path or base / "config" / "voice_auth.json"
        self.model_path = base / "config" / "speaker_embedding.onnx"
        self._lock = threading.Lock()
        self._model = None
        self._model_error: str | None = None

    def profile(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _speaker_model(self):
        if self._model is not None:
            return self._model
        if self._model_error:
            raise RuntimeError(self._model_error)
        try:
            primary = self.path.parent.parent / "primary"
            config_path = primary / "config.py"
            model_path = primary / "voice_auth" / "model.py"
            config_spec = importlib.util.spec_from_file_location(
                "_agent_primary_config", config_path
            )
            if config_spec is None or config_spec.loader is None:
                raise ImportError(f"could not load primary config: {config_path}")
            primary_config = importlib.util.module_from_spec(config_spec)
            config_spec.loader.exec_module(primary_config)

            model_spec = importlib.util.spec_from_file_location(
                "_agent_primary_speaker_model", model_path
            )
            if model_spec is None or model_spec.loader is None:
                raise ImportError(f"could not load primary verifier: {model_path}")
            model_module = importlib.util.module_from_spec(model_spec)
            previous_config = sys.modules.get("config")
            sys.modules["config"] = primary_config
            try:
                model_spec.loader.exec_module(model_module)
            finally:
                if previous_config is None:
                    sys.modules.pop("config", None)
                else:
                    sys.modules["config"] = previous_config

            self._model = model_module.SpeakerEmbeddingModel(self.model_path)
            return self._model
        except Exception as e:
            self._model_error = f"speaker verification model unavailable: {e}"
            raise RuntimeError(self._model_error) from e

    @staticmethod
    def _audio(samples) -> np.ndarray:
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        if x.size and np.max(np.abs(x)) > 1.0:
            x /= 32768.0
        return x

    def is_enrolled(self) -> bool:
        p = self.profile()
        embeddings = p.get("embeddings")
        return bool(
            p.get("version", 0) >= 2
            and p.get("name")
            and isinstance(embeddings, list)
            and len(embeddings) >= SAMPLES_REQUIRED
        )

    def enroll(self, name: str, recordings: list,
               phrases: list[str] | None = None) -> tuple[bool, str]:
        clean_name = " ".join((name or "").split())[:80]
        if not clean_name:
            return False, "Enter the primary user's name before recording."
        if len(recordings) != SAMPLES_REQUIRED:
            return False, "Three enrollment samples are required."
        phrases = phrases or list(REGISTRATION_SENTENCES)
        if len(phrases) != SAMPLES_REQUIRED:
            return False, "Three enrollment challenge phrases are required."
        try:
            model = self._speaker_model()
            embeddings = []
            for recording in recordings:
                audio = self._audio(recording)
                if audio.size < SAMPLE_RATE * 2:
                    return False, "Each sample needs at least two seconds of clear speech."
                embedding, diagnostics = model.generate_embedding(audio, apply_vad=True)
                if diagnostics.get("raw_peak", 0.0) < 0.02:
                    return False, "A sample was too quiet; please enroll again."
                embeddings.append(embedding.tolist())
            payload = {
                "version": 2,
                "name": clean_name,
                "phrases": phrases,
                "authentication_sentences": list(AUTHENTICATION_SENTENCES),
                "threshold": MATCH_THRESHOLD,
                "embeddings": embeddings,
            }
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return True, f"Voice enrollment complete for {clean_name}."
        except Exception as e:
            return False, f"Voice enrollment failed: {e}"

    def verify(self, recording) -> tuple[bool, float, str]:
        p = self.profile()
        name = str(p.get("name") or "primary user")
        if not self.is_enrolled():
            return False, 0.0, name
        try:
            candidate, diagnostics = self._speaker_model().generate_embedding(
                self._audio(recording), apply_vad=True
            )
            if diagnostics.get("raw_peak", 0.0) < 0.02:
                return False, 0.0, name
            scores = []
            for saved in p["embeddings"]:
                reference = np.asarray(saved, dtype=np.float32)
                if reference.shape == candidate.shape:
                    scores.append(float(np.dot(candidate, reference)))
            score = max(scores, default=0.0)
            # Never trust a weak/legacy value persisted by the old matcher.
            threshold = max(float(p.get("threshold", MATCH_THRESHOLD)), MATCH_THRESHOLD)
            return score >= threshold, score, name
        except Exception as e:
            print(f"[AUTH] Verification failed closed: {e}")
            return False, 0.0, name

    def record_enrollment(self, progress=None, capture=None) -> list[np.ndarray]:
        import sounddevice as sd
        recordings = []
        for number in range(1, SAMPLES_REQUIRED + 1):
            phrase = REGISTRATION_SENTENCES[number - 1]
            if progress:
                progress(number, phrase)
            count = SAMPLE_RATE * SAMPLE_SECONDS
            if capture is not None:
                data = capture(count)
            else:
                data = sd.rec(count, samplerate=SAMPLE_RATE, channels=1, dtype="int16")
                sd.wait()
                data = data[:, 0]
            recordings.append(np.asarray(data, dtype=np.int16).reshape(-1).copy())
        return recordings
