"""
Email Sender Module for ProAssist AI Phase 2
Provides secure, provider-agnostic email dispatch.
Supports Gmail API via OAuth 2.0 with strict explicit confirmation gating.
Never prints or logs secret credentials, passwords, or access tokens.
"""

import os
import base64
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from phase2.email.email_composer import EmailDraft



class BaseEmailProvider:
    """Abstract base class for email sending providers."""

    def is_configured(self) -> bool:
        raise NotImplementedError

    def send(self, to_email: str, subject: str, body: str) -> dict:
        raise NotImplementedError


class GmailOAuthProvider(BaseEmailProvider):
    """
    Gmail API provider using OAuth 2.0.
    Looks for client credentials in data/gmail_credentials.json or environment variables.
    Fails gracefully if unconfigured.
    """

    def __init__(self, credentials_file: Path = None, token_file: Path = None):
        data_dir = PROJECT_ROOT / "data"
        self.credentials_file = Path(credentials_file) if credentials_file else data_dir / "gmail_credentials.json"
        self.token_file = Path(token_file) if token_file else data_dir / "gmail_token.json"

    def is_configured(self) -> bool:
        """Returns True only if valid credentials or tokens are present on disk."""
        return self.token_file.exists() or self.credentials_file.exists()

    def send(self, to_email: str, subject: str, body: str) -> dict:
        """Sends an email using Gmail API."""
        if not self.is_configured():
            return {
                "status": "not_configured",
                "message": "Email sending is not configured yet."
            }

        try:
            # Dynamic imports to avoid requiring google-api-python-client when unconfigured
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            if not self.token_file.exists():
                return {
                    "status": "not_configured",
                    "message": "Email sending is not configured yet (OAuth token missing)."
                }

            creds = Credentials.from_authorized_user_file(str(self.token_file))
            service = build("gmail", "v1", credentials=creds)

            import importlib
            mime_mod = importlib.import_module("email.mime.text")
            message = mime_mod.MIMEText(body)
            message["to"] = to_email
            message["subject"] = subject

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            return {
                "status": "success",
                "message": "Email sent successfully."
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to send email: {e}"
            }


class MockEmailProvider(BaseEmailProvider):
    """Mock provider for unit and regression testing without sending real emails."""

    def __init__(self, is_configured: bool = True):
        self._configured = is_configured
        self.sent_messages = []

    def is_configured(self) -> bool:
        return self._configured

    def send(self, to_email: str, subject: str, body: str) -> dict:
        if not self._configured:
            return {
                "status": "not_configured",
                "message": "Email sending is not configured yet."
            }

        msg = {
            "to": to_email,
            "subject": subject,
            "body": body
        }
        self.sent_messages.append(msg)
        return {
            "status": "success",
            "message": "Email sent successfully."
        }


class EmailSender:
    """Orchestrates email dispatch with mandatory explicit confirmation."""

    def __init__(self, provider: BaseEmailProvider = None):
        self.provider = provider or GmailOAuthProvider()

    def send_email(self, draft: EmailDraft, confirmed: bool = False) -> dict:
        """
        Sends an email only after verifying completeness and explicit confirmation.
        """
        if draft is None or not draft.is_valid():
            return {
                "status": "error",
                "message": "Draft is incomplete or missing required fields."
            }

        # Mandatory confirmation security gate
        if not confirmed and not draft.is_confirmed:
            return {
                "status": "unconfirmed",
                "message": "Confirmation required before sending."
            }

        # Check provider configuration
        if not self.provider.is_configured():
            return {
                "status": "not_configured",
                "message": "Email sending is not configured yet."
            }

        return self.provider.send(
            to_email=draft.recipient_email,
            subject=draft.subject,
            body=draft.body
        )
