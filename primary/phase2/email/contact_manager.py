"""
Contact Manager Module for ProAssist AI Phase 2
Handles local contact lookup, email validation, and persistent storage
in data/contacts.json without storing sensitive credentials.
"""

import json
import re
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_CONTACTS_PATH = PROJECT_ROOT / "data" / "contacts.json"


class ContactManager:
    """Manages local recipient contact lookups and updates."""

    def __init__(self, contacts_path: Path = None):
        self.contacts_path = Path(contacts_path) if contacts_path else DEFAULT_CONTACTS_PATH
        self._ensure_file()

    def _ensure_file(self):
        """Ensures the contacts directory and file exist."""
        self.contacts_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.contacts_path.exists():
            with open(self.contacts_path, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=2)

    def load_contacts(self) -> dict:
        """Loads contacts dictionary from JSON."""
        self._ensure_file()
        try:
            with open(self.contacts_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def save_contacts(self, contacts: dict):
        """Saves contacts dictionary to JSON."""
        self.contacts_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.contacts_path, "w", encoding="utf-8") as f:
            json.dump(contacts, f, indent=2)

    @staticmethod
    def is_valid_email(email: str) -> bool:
        """Validates that an email address follows standard syntax."""
        if not email or not isinstance(email, str):
            return False
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        return bool(re.match(pattern, email.strip()))

    @staticmethod
    def parse_spoken_email(spoken_text: str) -> str:
        """
        Converts spoken email phrasing into valid email text:
        e.g. 'rahul at example dot com' -> 'rahul@example.com'
        """
        if not spoken_text:
            return ""
        text = spoken_text.lower().strip()
        text = re.sub(r"\s+at\s+", "@", text)
        text = re.sub(r"\s+dot\s+", ".", text)
        text = re.sub(r"\s+", "", text)
        return text

    def get_contact(self, name: str) -> dict | None:
        """
        Searches for a contact by spoken name (case-insensitive).
        Returns dict with 'name' and 'email' or None.
        """
        if not name:
            return None
        clean_name = name.lower().strip()
        contacts = self.load_contacts()

        # Direct key lookup
        if clean_name in contacts:
            return contacts[clean_name]

        # Name field match
        for key, info in contacts.items():
            if info.get("name", "").lower() == clean_name:
                return info

        # Partial word boundary match
        for key, info in contacts.items():
            if clean_name in key or clean_name in info.get("name", "").lower():
                return info

        return None

    def add_contact(self, name: str, email: str) -> dict:
        """
        Adds a new contact to local storage after validating email.
        Raises ValueError if email is invalid.
        """
        clean_name = name.strip()
        clean_email = email.strip().lower()

        if not self.is_valid_email(clean_email):
            raise ValueError(f"Invalid email address: '{clean_email}'")

        contacts = self.load_contacts()
        key = clean_name.lower()
        contact_entry = {
            "name": clean_name.capitalize(),
            "email": clean_email
        }
        contacts[key] = contact_entry
        self.save_contacts(contacts)
        return contact_entry
