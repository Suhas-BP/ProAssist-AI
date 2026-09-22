"""
Email Composer Module for ProAssist AI Phase 2
Constructs and validates structured email drafts (recipient, subject, body).
Keeps draft state strictly independent from the sending provider.
"""

from typing import Optional


class EmailDraft:
    """Represents a structured email message awaiting confirmation."""

    def __init__(self, recipient_name: str = "", recipient_email: str = "",
                 subject: str = "", body: str = ""):
        self.recipient_name = recipient_name.strip()
        self.recipient_email = recipient_email.strip().lower()
        self.subject = subject.strip()
        self.body = body.strip()
        self.is_confirmed = False

    def is_valid(self) -> bool:
        """Returns True if draft has valid recipient email, subject, and body."""
        return bool(self.recipient_email and self.subject and self.body)

    def confirm(self):
        """Marks draft as explicitly confirmed by user."""
        self.is_confirmed = True

    def format_preview(self) -> str:
        """Returns clean multi-line visual preview of email draft."""
        name_part = f"{self.recipient_name} " if self.recipient_name else ""
        return (
            f"To: {name_part}<{self.recipient_email}>\n"
            f"Subject: {self.subject}\n"
            f"Body:\n{self.body}"
        )

    def to_dict(self) -> dict:
        """Serializes draft to dictionary."""
        return {
            "recipient_name": self.recipient_name,
            "recipient_email": self.recipient_email,
            "subject": self.subject,
            "body": self.body,
            "is_confirmed": self.is_confirmed,
        }


class EmailComposer:
    """Manages the creation and population of email drafts."""

    def __init__(self):
        self.current_draft: Optional[EmailDraft] = None

    def start_draft(self, recipient_name: str, recipient_email: str) -> EmailDraft:
        """Initializes a new draft for the recipient."""
        self.current_draft = EmailDraft(
            recipient_name=recipient_name,
            recipient_email=recipient_email
        )
        return self.current_draft

    def set_subject(self, subject: str):
        """Sets the email subject."""
        if self.current_draft is not None:
            self.current_draft.subject = subject.strip()

    def set_body(self, body: str):
        """Sets the email body."""
        if self.current_draft is not None:
            self.current_draft.body = body.strip()

    def confirm_draft(self) -> bool:
        """Confirms the active draft if valid."""
        if self.current_draft and self.current_draft.is_valid():
            self.current_draft.confirm()
            return True
        return False

    def clear(self):
        """Clears current draft."""
        self.current_draft = None
