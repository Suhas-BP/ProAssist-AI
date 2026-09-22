"""
Email Command Parser Module for ProAssist AI Phase 2
Recognizes email drafting intents and safely extracts the recipient's name
from spoken commands with speech normalization.
"""

import re


class EmailParser:
    """Parses email commands and confirmation speech."""

    def __init__(self):
        # Patterns for initiating email composition
        self.email_patterns = [
            # "write/send/compose/draft an? email to <name>"
            r"\b(?:write|send|compose|draft)\s+(?:an?\s+)?email\s+to\s+([a-zA-Z\s]+)",
            # "email to <name>"
            r"\bemail\s+to\s+([a-zA-Z\s]+)",
            # "email <name>"
            r"\bemail\s+([a-zA-Z]+)\b",
            # "mail <name>"
            r"\bmail\s+([a-zA-Z]+)\b",
            # "send mail to <name>"
            r"\bsend\s+mail\s+to\s+([a-zA-Z\s]+)",
        ]

        # Safe confirmation patterns
        self.confirmation_patterns = [
            r"\b(yes|yeah|yep|sure|send\s+it|send\s+the\s+email|okay\s+send|ok\s+send|please\s+send|confirm|send)\b"
        ]

        # Safe cancellation patterns
        self.cancellation_patterns = [
            r"\b(no|nope|cancel|do\s+not\s+send|dont\s+send|stop|discard|abort)\b"
        ]

    def _clean_text(self, text: str) -> str:
        """Removes punctuation and normalizes whitespace."""
        clean = re.sub(r"[^\w\s]", " ", text.lower())
        return " ".join(clean.split())

    def parse_command(self, text: str) -> dict:
        """
        Parses incoming spoken text to determine if it is an email command.
        Returns:
            {
                "is_email": bool,
                "recipient_name": str or None,
                "raw_text": str
            }
        """
        if not text:
            return {"is_email": False, "recipient_name": None, "raw_text": ""}

        cleaned = self._clean_text(text)

        for pat in self.email_patterns:
            match = re.search(pat, cleaned, re.IGNORECASE)
            if match:
                recipient = match.group(1).strip()
                # Exclude distractor words if matched
                exclude_words = {"me", "him", "her", "them", "us", "someone"}
                if recipient.lower() in exclude_words:
                    recipient = recipient.capitalize()
                else:
                    recipient = " ".join(w.capitalize() for w in recipient.split())

                return {
                    "is_email": True,
                    "recipient_name": recipient,
                    "raw_text": text
                }

        return {"is_email": False, "recipient_name": None, "raw_text": text}

    def is_confirmation(self, text: str) -> bool:
        """Returns True if text matches explicit email confirmation phrases."""
        if not text:
            return False
        cleaned = self._clean_text(text)
        for pat in self.confirmation_patterns:
            if re.search(pat, cleaned):
                return True
        return False

    def is_cancellation(self, text: str) -> bool:
        """Returns True if text matches explicit cancellation phrases."""
        if not text:
            return False
        cleaned = self._clean_text(text)
        for pat in self.cancellation_patterns:
            if re.search(pat, cleaned):
                return True
        return False
