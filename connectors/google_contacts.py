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

import logging
import os
import re
import sys
import importlib.util as _ilu
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

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
            self._persona_token.write_text(creds.to_json(), encoding="utf-8")

        # cache_discovery=False avoids httplib2 writing the discovery doc via
        # the system locale (cp1252 on Windows), which breaks on non-ASCII chars.
        self._service = build("people", "v1", credentials=creds, cache_discovery=False)
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
    def _fetch_contacts(
        self, max_results: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Fetch and parse contacts from Google. Returns (contacts, failed_resource_names)."""
        page_token: str | None = None
        all_persons: list[dict] = []
        page_size = min(max_results, 1000)

        # Follow pagination — the API caps at 1000 per page.
        while True:
            kwargs: dict[str, Any] = dict(
                resourceName="people/me",
                pageSize=page_size,
                personFields="names,emailAddresses,phoneNumbers",
            )
            if page_token:
                kwargs["pageToken"] = page_token

            page = (
                self._svc()
                .people()
                .connections()
                .list(**kwargs)
                .execute()
            )
            all_persons.extend(page.get("connections", []))
            page_token = page.get("nextPageToken")
            if not page_token or len(all_persons) >= max_results:
                break

        contacts: list[dict[str, Any]] = []
        parse_errors: list[str] = []
        for person in all_persons:
            resource_name = person.get("resourceName", "(unknown)")
            try:
                names = person.get("names", [])
                display = names[0]["displayName"] if names else None
                if not display:
                    continue
                # Encode/decode round-trip to replace any invalid characters
                display = display.encode("utf-8", errors="replace").decode("utf-8")
                emails = [
                    e["value"].encode("utf-8", errors="replace").decode("utf-8")
                    for e in person.get("emailAddresses", [])
                ]
                phones = [
                    p["value"].encode("utf-8", errors="replace").decode("utf-8")
                    for p in person.get("phoneNumbers", [])
                ]
                contacts.append(
                    {
                        "name": display,
                        "emails": emails,
                        "phones": phones,
                        "source_id": resource_name,
                    }
                )
            except Exception as exc:
                log.warning(
                    "google_contacts: failed to parse %s — %s: %s",
                    resource_name, type(exc).__name__, exc,
                )
                parse_errors.append(resource_name)

        if parse_errors:
            log.warning(
                "google_contacts: %d contact(s) could not be parsed: %s",
                len(parse_errors), ", ".join(parse_errors),
            )

        return contacts, parse_errors

    def list_contacts(self, max_results: int = 50) -> list[dict[str, Any]]:
        contacts, _ = self._fetch_contacts(max_results)
        return contacts

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @command(
        description=(
            "Sync Google Contacts into YANA's persona/contact registry (shadow copy). "
            "New contacts are created. Existing ones (matched by Google source_id) have their "
            "name and addresses updated — YANA enrichment (aliases, context, tags, preferred channel) "
            "is never overwritten. Safe to run repeatedly. "
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
    def sync_contacts(
        self,
        owner: str,
        email_connector_id: str,
        phone_connector_id: str | None = None,
        channel_for_phone: str = "whatsapp",
    ) -> dict[str, Any]:
        raw, fetch_errors = self._fetch_contacts(max_results=1000)

        added_personas = 0
        updated_personas = 0
        added_contacts = 0
        skipped = 0
        skipped_names: list[str] = []

        existing_contact_ids = {c.id for c in self._registry._contacts}

        for entry in raw:
            display: str = entry["name"]
            emails: list[str] = entry["emails"]
            phones: list[str] = entry["phones"]
            source_id: str = entry["source_id"]

            if not display.strip():
                skipped += 1
                skipped_names.append(f"(sem nome / source_id={source_id})")
                continue

            # Find existing persona by source_id (reliable) or fall back to slugified name
            existing = self._registry.find_by_source("google", source_id) if source_id else None
            if existing is None:
                persona_id = _slugify(display)
                if not persona_id:
                    skipped += 1
                    skipped_names.append(f"{display!r} (slug vazio / source_id={source_id})")
                    continue
                existing = self._registry._personas.get(persona_id)

            if existing is not None:
                # YANA is source of truth — never overwrite name or enrichment
                # Only add new source reference if missing
                if not any(s.get("source_id") == source_id for s in existing.sources):
                    existing.sources.append({"provider": "google", "source_id": source_id})
                updated_personas += 1
                persona_id = existing.id
            else:
                persona_id = _slugify(display)
                if not persona_id:
                    skipped += 1
                    skipped_names.append(f"{display!r} (slug vazio / source_id={source_id})")
                    continue
                p = Persona(
                    id=persona_id,
                    name=display,
                    type="person",
                    owner=owner,
                    aliases=[display],
                    context="",
                    tags=[],
                    sources=[{"provider": "google", "source_id": source_id}],
                )
                self._registry._personas[persona_id] = p
                added_personas += 1

            # Sync email contacts
            for email in emails:
                contact_id = f"{persona_id}_email_{_slugify(email)}"
                if contact_id not in existing_contact_ids:
                    self._registry._contacts.append(Contact(
                        id=contact_id,
                        persona_id=persona_id,
                        channel="email",
                        address=email,
                        connector_id=email_connector_id,
                        preferred=len(emails) == 1 and not phones,
                    ))
                    existing_contact_ids.add(contact_id)
                    added_contacts += 1

            # Sync phone contacts
            if phone_connector_id:
                for phone in phones:
                    contact_id = f"{persona_id}_{channel_for_phone}_{_slugify(phone)}"
                    if contact_id not in existing_contact_ids:
                        self._registry._contacts.append(Contact(
                            id=contact_id,
                            persona_id=persona_id,
                            channel=channel_for_phone,
                            address=phone,
                            connector_id=phone_connector_id,
                            preferred=not emails,
                        ))
                        existing_contact_ids.add(contact_id)
                        added_contacts += 1

        self._registry.save()
        result: dict[str, Any] = {
            "added_personas": added_personas,
            "updated_personas": updated_personas,
            "added_contacts": added_contacts,
            "skipped": skipped,
            "total_processed": len(raw),
            "fetch_errors": len(fetch_errors),
        }
        if skipped_names:
            result["skipped_names"] = skipped_names
        if fetch_errors:
            result["fetch_error_ids"] = fetch_errors
        return result
