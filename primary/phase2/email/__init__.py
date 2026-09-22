"""
ProAssist AI Phase 2 - Voice Email Module
"""

from phase2.email.contact_manager import ContactManager
from phase2.email.email_parser import EmailParser
from phase2.email.email_composer import EmailComposer, EmailDraft
from phase2.email.email_sender import EmailSender, BaseEmailProvider, GmailOAuthProvider, MockEmailProvider
from phase2.email.email_flow import handle_email_flow

__all__ = [
    "ContactManager",
    "EmailParser",
    "EmailComposer",
    "EmailDraft",
    "EmailSender",
    "BaseEmailProvider",
    "GmailOAuthProvider",
    "MockEmailProvider",
    "handle_email_flow",
]
