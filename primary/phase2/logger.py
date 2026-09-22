"""
ProAssist AI - Phase 2 Verification Logger
Logs wake-word detections and speaker verification attempts to logs/voice_verification.log.
Never logs raw audio or voiceprint vectors for privacy and security.
"""

import datetime
from pathlib import Path
from phase2 import config as p2_config


class VerificationLogger:
    """Logs voice verification events to a persistent file."""

    def __init__(self, log_path: Path = None):
        if log_path is None:
            log_path = p2_config.VOICE_VERIFICATION_LOG_PATH
        self.log_path = Path(log_path)
        self._ensure_dir()

    def _ensure_dir(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_timestamp(self) -> str:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log_wake_word(self, wake_phrase: str):
        """Log a wake-word trigger event."""
        self._ensure_dir()
        ts = self._get_timestamp()
        entry = f'{ts} | WAKE_WORD | "{wake_phrase}"\n'
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(entry)

    def log_verification(
        self,
        score: float,
        threshold: float,
        result: str,
        user: str = None,
        reason: str = None,
    ):
        """
        Log a speaker verification attempt.
        Result should be 'AUTHORIZED' or 'REJECTED'.
        """
        self._ensure_dir()
        ts = self._get_timestamp()
        entry = f"{ts} | VERIFICATION | score={score:.4f} | threshold={threshold:.2f} | result={result.upper()}"
        if user and result.upper() == "AUTHORIZED":
            entry += f" | user={user}"
        if reason and result.upper() == "REJECTED":
            entry += f" | reason={reason}"
        entry += "\n"

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(entry)


# Singleton instance for convenience
_default_logger = None

def get_verification_logger() -> VerificationLogger:
    global _default_logger
    if _default_logger is None:
        _default_logger = VerificationLogger()
    return _default_logger
