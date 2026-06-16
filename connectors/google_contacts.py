"""
connectors/google_contacts.py — Google Contacts (People API) connector.

Two operations:
  list_contacts(max_results?)          → raw Google contact data (query)
  import_contacts(owner, email_connector_id, phone_connector_id?, channel_for_phone?)
                                       → upserts Personas + Contacts into YAML (command)

import_contacts is designed to be run once (or periodically) to seed the registry.
Personas that already exist (by id) are merged — aliases and context are updated,
existing entries are not overwritten.

Setup:
  1. Enable the People API in your Google Cloud project
  2. Add scope 'https://www.googleapis.com/auth/contacts.readonly' to your OAuth consent
  3. Configure in connectors.yaml:

       - type: GoogleContactsConnector
         id: google_contacts
         name: "Google Contacts"
         description: "Import contacts from Google into YANA's registry"
         config:
           app_credential: "~/.yana/google_credentials.json"
           persona_token: "~/.yana/tokens/google_contacts.json"
           personas_file: "orchestrator/config/personas.yaml"
           contacts_file: "orchestrator/config/contacts.yaml"
"""

from __future__ import annotations

import os
import re
import sys
import importlib.util as _ilu
from pathlib import Path
from typing import Any

from connectors import Connector, command, query

# Reuse the ContactRegistry from orchestrator/contacts.py
_contacts_mod_path = Path(__file__).parent.parent / "orchestrator" / "contacts.py"
if "orchestrator.contacts" not in sys.modules:
    _spec = _ilu.spec_from_file_location("orchestrator.contacts", _contacts_mod_path)
    _contacts_mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
    sys.modules["orchestrator.contacts"] = _contacts_mod
    _spec.loader.exec_module(_contacts_mod)  # type: ignore[union-attr]

_contacts_mod = sys.modules["orchestrator.contacts"]
ContactRegistry = _contacts_mod.ContactRegistry
Contact = _contacts_mod.Contact
Persona = _contacts_mod.Persona

_SCOPES = ["https://www.googleapis.com/auth/contacts.readonly"]

_DEFAULT_PERSONAS = "orchestrator/config/personas.yaml"
_DEFAULT_CONTACTS = "orchestrator/config/contacts.yaml"


def _slugify(name: str) -> str:
    """Turn a display name into a lowercase id safe for YAML keys."""
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


class GoogleContactsConnector(Connector):
    connector_description = (
        "Import contacts from Google Contacts into YANA's persona/contact registry"
    )

    def __init__(
        self,
        app_credential: str | None = None,
        persona_token: str | None = None,
        personas_file: str | None = None,
        contacts_file: str | None = None,
    ) -> None:
        self._app_credential = Path(
            app_credential
            or os.environ.get("GOOGLE_CREDENTIALS_FILE", "~/.yana/google_credentials.json")
        ).expanduser()
        self._persona_token = Path(
            persona_token
            or os.environ.get("GOOGLE_TOKEN_FILE", "~/.yana/tokens/google_contacts.json")
        ).expanduser()

        personas_path = Path(personas_file or _DEFAULT_PERSONAS)
        contacts_path = Path(contacts_file or _DEFAULT_CONTACTS)
        if not personas_path.is_absolute():
            personas_path = Path(__file__).parent.parent / personas_path
        if not contacts_path.is_absolute():
            contacts_path = Path(__file__).parent.parent / contacts_path

        self._registry = ContactRegistry()
        self._registry.load(personas_path, contacts_path)
        self._service = None  # lazy

    # ------------------------------------------------------------------
    # Auth helper
    # ------------------------------------------------------------------

    def _svc(self) -> Any:
        if self._service is not None:
            return self._service
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if self._persona_token.exists():
            creds = Credentials.from_authorized_user_file(str(self._persona_token), _SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._app_credential), _SCOPES
                )
                creds = flow.run_local_server(port=0)
            self._persona_token.parent.mkdir(parents=True, exist_ok=True)
            self._persona_token.write_text(creds.to_json())

        self._service = build("people", "v1", credentials=creds)
        return self._service

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @query(
        description=(
            "List raw contacts from Google Contacts. "
            "Returns display names, emails, and phone numbers. "
            "Use import_contacts to upsert them into YANA's registry."
        ),
        params={"max_results": {"type": "number", "required": False}},
        returns={"type": "list"},
    )
    def list_contacts(self, max_results: int = 50) -> list[dict[str, Any]]:
        result = (
            self._svc()
            .people()
            .connections()
            .list(
                resourceName="people/me",
                pageSize=min(max_results, 1000),
                personFields="names,emailAddresses,phoneNumbers",
            )
            .execute()
        )
        contacts = []
        for person in result.get("connections", []):
            names = person.get("names", [])
            emails = [e["value"] for e in person.get("emailAddresses", [])]
            phones = [p["value"] for p in person.get("phoneNumbers", [])]
            display = names[0]["displayName"] if names else None
            if display:
                contacts.append(
                    {"name": display, "emails": emails, "phones": phones}
                )
        return contacts

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @command(
        description=(
            "Import Google Contacts into YANA's persona/contact registry. "
            "Creates a Persona for each contact and adds email/phone Contact entries. "
            "Existing personas (matched by id) are skipped — call again to refresh aliases. "
            "owner: persona owner label (usually 'fred'). "
            "email_connector_id: connector to use for email contacts (e.g. 'gmail_fred_personal'). "
            "phone_connector_id: connector to use for phone contacts (e.g. 'whatsapp'). "
            "channel_for_phone: 'whatsapp' or 'sms' — defaults to 'whatsapp'."
        ),
        params={
            "owner": {"type": "string", "required": True},
            "email_connector_id": {"type": "string", "required": True},
            "phone_connector_id": {"type": "string", "required": False},
            "channel_for_phone": {"type": "string", "required": False},
        },
        returns={"type": "object"},
    )
    def import_contacts(
        self,
        owner: str,
        email_connector_id: str,
        phone_connector_id: str | None = None,
        channel_for_phone: str = "whatsapp",
    ) -> dict[str, Any]:
        raw = self.list_contacts(max_results=1000)

        added_personas = 0
        added_contacts = 0
        skipped = 0

        for entry in raw:
            display: str = entry["name"]
            emails: list[str] = entry["emails"]
            phones: list[str] = entry["phones"]

            persona_id = _slugify(display)
            if not persona_id:
                skipped += 1
                continue

            # Upsert persona (skip if already present — preserve YANA's richer context)
            if persona_id not in self._registry._personas:
                p = Persona(
                    id=persona_id,
                    name=display,
                    type="person",
                    owner=owner,
                    aliases=[display],
                    context="",
                    tags=[],
                )
                self._registry._personas[persona_id] = p
                added_personas += 1

            # Add email contacts not already in the registry
            existing_ids = {c.id for c in self._registry._contacts}
            for email in emails:
                contact_id = f"{persona_id}_email_{_slugify(email)}"
                if contact_id not in existing_ids:
                    c = Contact(
                        id=contact_id,
                        persona_id=persona_id,
                        channel="email",
                        address=email,
                        connector_id=email_connector_id,
                        preferred=len(emails) == 1 and not phones,
                    )
                    self._registry._contacts.append(c)
                    added_contacts += 1

            # Add phone contacts if connector provided
            if phone_connector_id:
                for phone in phones:
                    contact_id = f"{persona_id}_{channel_for_phone}_{_slugify(phone)}"
                    if contact_id not in existing_ids:
                        c = Contact(
                            id=contact_id,
                            persona_id=persona_id,
                            channel=channel_for_phone,
                            address=phone,
                            connector_id=phone_connector_id,
                            preferred=not emails,
                        )
                        self._registry._contacts.append(c)
                        added_contacts += 1

        self._registry.save()
        return {
            "added_personas": added_personas,
            "added_contacts": added_contacts,
            "skipped": skipped,
            "total_processed": len(raw),
        }
