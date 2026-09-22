"""
Local wake detection for AGENT.

Design goals:
  • ZERO cost when the feature is off — openwakeword is imported ONLY inside
    start()/install helpers, never at module load. If the user never enables
    wake word, none of this touches the app.
  • ZERO latency on the audio path — the microphone callback only ever does a
    cheap, non-blocking queue push (feed()); the actual model inference runs in
    this module's own background thread, so the real-time audio thread and the
    Gemini stream are never slowed.
  • Fully local & offline — audio fed here never leaves the machine; there is no
    network call except the one-time model download the user triggers from the UI.

openwakeword ships small ONNX models (a few MB each) and runs comfortably on a
CPU. The currently bundled upstream model is retained for compatibility; it
detects its original legacy phrase, then AGENT requires the local passphrase.
"""
from __future__ import annotations

import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable
import numpy as np

# Agent recognition requires the trained custom model. The upstream model is
# retained only as a download compatibility constant and must not be presented
# as an Agent detector.
WAKE_MODEL = "hey_jarvis"
WAKE_PHRASE = "Agent"
WHISPER_MODEL_SIZE = "tiny.en"
WHISPER_BUFFER_SECONDS = 2.0
WHISPER_CHECK_INTERVAL = 0.35
WHISPER_ENERGY_THRESHOLD = 0.0055
# Output location for the official openWakeWord training notebook. A trained
# ``agent.onnx`` placed here takes precedence over the compatibility model.
CUSTOM_MODEL = Path(__file__).resolve().parent.parent / "config" / "wake_words" / "agent.onnx"
# Score in [0,1]; above this counts as a detection. Tunable per environment.
DEFAULT_THRESHOLD = 0.5
# Mic frames arrive at 16 kHz int16; this is just the detector's input rate.
SAMPLE_RATE = 16000


def active_model() -> str:
    """Return the model path used for Agent recognition."""
    return str(CUSTOM_MODEL)


def using_custom_model() -> bool:
    return custom_model_ready()


def custom_model_ready() -> bool:
    """Return whether the custom model and all external tensor data exist."""
    if not CUSTOM_MODEL.is_file():
        return False
    # ONNX models may store large initializers beside the model. The Agent
    # model currently references this file, so do not advertise readiness when
    # the model was copied without its tensor data.
    try:
        raw = CUSTOM_MODEL.read_bytes()
        marker = b"Agent.onnx.data"
        return marker not in raw or CUSTOM_MODEL.with_name(marker.decode()).is_file()
    except OSError:
        return False


def is_installed() -> bool:
    """True if the openwakeword package is importable (no model check)."""
    try:
        import importlib.util
        return importlib.util.find_spec("openwakeword") is not None
    except Exception:
        return False


def is_ready() -> bool:
    """True if openwakeword is installed AND its model files are present on disk.

    This is a cheap, DETERMINISTIC file-existence check. It deliberately does NOT
    construct a Model to probe readiness — doing that is slow and, worse, can clash
    with the detector's own Model when it's already running, which intermittently
    returned False and made the UI flicker to 'not downloaded'. Never raises.
    """
    if not is_installed():
        try:
            import importlib.util
            return importlib.util.find_spec("faster_whisper") is not None
        except Exception:
            return False
    try:
        import openwakeword
        models_dir = Path(openwakeword.__file__).resolve().parent / "resources" / "models"
        if not models_dir.is_dir():
            return False
        has_wake = custom_model_ready()
        has_mel = (any(models_dir.glob("melspectrogram*.onnx"))
                   or any(models_dir.glob("melspectrogram*.tflite")))
        has_emb = (any(models_dir.glob("embedding_model*.onnx"))
                   or any(models_dir.glob("embedding_model*.tflite")))
        if has_wake and has_mel and has_emb:
            return True
        import importlib.util
        return importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        return False


def install_and_download(logger: Callable[[str], None] = print,
                         notify: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """
    One-click setup for the UI button: pip-install openwakeword if missing, then
    download the wake model. Returns (ok, message). Never raises — every failure
    is reported through the returned message and the logger.
    """
    _tell = notify or (lambda _msg: None)
    try:
        if not is_installed():
            logger("Wake word: installing openwakeword (one-time)…")
            _tell("Wake word: installing openwakeword (one-time)…")
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "openwakeword"],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
                return False, f"pip install failed: {tail[0][:160]}"
        # Download the pretrained melspectrogram/embedding + wake models.
        logger("Wake word: downloading models…")
        _tell("Wake word: downloading models…")
        try:
            import openwakeword.utils as _u
            try:
                _u.download_models([WAKE_MODEL])
            except TypeError:
                _u.download_models()   # older signature downloads the default set
        except Exception as e:
            return False, f"model download failed: {e}"

        if not is_ready():
            return False, "installed, but the wake model could not be loaded."
        logger("Wake word: ready.")
        return True, "Wake word installed and ready."
    except Exception as e:
        return False, f"setup error: {e}"


class WakeWordDetector:
    """
    Runs the wake model in a dedicated thread. The mic thread calls feed() with
    raw int16 frames; detections invoke on_detect() (called from this thread —
    the callback must marshal to whatever loop/UI it needs).
    """

    def __init__(self, on_detect: Callable[[], None],
                 threshold: float = DEFAULT_THRESHOLD,
                 logger: Callable[[str], None] = print,
                 notify: Callable[[str], None] | None = None):
        self._on_detect = on_detect
        self._threshold = threshold
        self._logger    = logger
        # See PluginRegistry: `logger` is the console and gets everything,
        # `notify` is the activity log and gets only what the user must act on.
        self._notify    = notify or (lambda _msg: None)
        self._queue: queue.Queue = queue.Queue(maxsize=50)
        self._thread: threading.Thread | None = None
        self._running = False
        self._model = None
        self._ready = False
        self._whisper = None

    def start(self) -> bool:
        """Load the model and spawn the inference thread. Returns True on success.
        Safe to call again — a no-op if already running. Never raises."""
        if self._running:
            return True
        try:
            from openwakeword.model import Model
            model_path = active_model()
            if not custom_model_ready():
                raise RuntimeError("custom Agent ONNX model is incomplete")
            self._model = Model(wakeword_models=[model_path], inference_framework="onnx")
            self._model_key = Path(model_path).stem.lower()
        except Exception as e:
            try:
                from faster_whisper import WhisperModel
                self._whisper = WhisperKeywordDetector(WhisperModel)
                self._model = None
                self._logger(
                    "Wake word Agent: custom ONNX unavailable; "
                    "using local Whisper keyword fallback."
                )
            except Exception as whisper_error:
                message = (
                    "Wake word Agent unavailable. The custom ONNX model is "
                    "incomplete and faster-whisper could not start: "
                    f"{whisper_error}"
                )
                self._logger(message)
                self._notify(message)
                self._model = None
                return False
        self._running = True
        self._ready = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="WakeWordThread")
        self._thread.start()
        label = "custom Agent" if self._whisper is None else "Whisper fallback"
        self._logger(
            f"Wake detection ready for '{WAKE_PHRASE}' ({label} model); "
            "voice passphrase verification is enabled."
        )
        return True

    def stop(self) -> None:
        self._running = False
        # unblock the thread if it's waiting on the queue
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        self._model = None
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def feed(self, frame_int16) -> None:
        """Called from the mic callback (real-time thread). Must stay cheap and
        never block — the frame is copied and dropped if the queue is backed up."""
        if not self._running:
            return
        try:
            # frame_int16 is a numpy int16 array (possibly 2-D mono) — flatten to 1-D
            data = frame_int16[:, 0].copy() if getattr(frame_int16, "ndim", 1) > 1 else frame_int16.copy()
            self._queue.put_nowait(data)
        except queue.Full:
            pass
        except Exception:
            pass

    def _loop(self) -> None:
        import numpy as np
        while self._running:
            try:
                frame = self._queue.get()
                if frame is None or not self._running:
                    break
                if self._whisper is not None:
                    if self._whisper.is_detected(frame):
                        self._drain()
                        self._on_detect()
                    continue
                scores = self._model.predict(np.asarray(frame, dtype=np.int16))
                score = 0.0
                if isinstance(scores, dict):
                    # A custom model's score key is its filename stem; older
                    # installations retain the compatibility model's key.
                    for k, v in scores.items():
                        if self._model_key in k.lower():
                            score = max(score, float(v))
                    if score == 0.0 and scores:
                        score = max(float(v) for v in scores.values())
                if score >= self._threshold:
                    # drain any backlog so we don't double-fire on the same utterance
                    self._drain()
                    try:
                        self._on_detect()
                    except Exception as e:
                        self._logger(f"Wake word: on_detect error — {e}")
            except Exception as e:
                self._logger(f"Wake word: inference error — {e}")

    def _drain(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except Exception:
            pass


class WhisperKeywordDetector:
    """Small local fallback adapted from the primary project's detector."""

    def __init__(self, whisper_model_cls):
        self.sample_rate = SAMPLE_RATE
        self.model = whisper_model_cls(
            WHISPER_MODEL_SIZE, device="cpu", compute_type="int8"
        )
        self.buffer = np.zeros(
            int(WHISPER_BUFFER_SECONDS * self.sample_rate), dtype=np.float32
        )
        self.last_check = time.monotonic()
        self.new_samples = 0

    @staticmethod
    def _matches(text: str) -> bool:
        words = re.sub(r"[^\w\s]", " ", text.lower()).split()
        if "agent" not in words:
            return False
        index = words.index("agent")
        if index == 0:
            return True
        return words[index - 1] in {
            "hey", "hay", "hi", "hello", "ok", "okay",
            "yo", "there", "um", "uh", "please", "so",
        }

    def is_detected(self, frame) -> bool:
        import numpy as np
        x = np.asarray(frame, dtype=np.int16).reshape(-1).astype(np.float32) / 32768.0
        if not x.size:
            return False
        count = min(x.size, self.buffer.size)
        self.buffer = np.roll(self.buffer, -count)
        self.buffer[-count:] = x[-count:]
        self.new_samples += x.size
        if time.monotonic() - self.last_check < WHISPER_CHECK_INTERVAL:
            return False
        if self.new_samples < int(self.sample_rate * 0.2):
            return False
        self.last_check = time.monotonic()
        self.new_samples = 0
        if float(np.sqrt(np.mean(self.buffer * self.buffer))) < WHISPER_ENERGY_THRESHOLD:
            return False
        try:
            segments, _ = self.model.transcribe(
                self.buffer,
                beam_size=1,
                language="en",
                vad_filter=False,
                condition_on_previous_text=False,
                hotwords="agent hey agent",
            )
            text = " ".join(segment.text for segment in segments).strip()
            self.last_check = time.monotonic()
            if self._matches(text):
                self.buffer.fill(0)
                return True
        except Exception as e:
            print(f"[Wake] Whisper inference error: {e}")
        return False
