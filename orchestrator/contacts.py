"""
contacts.py — Persona and Contact registry for YANA.

Provides two resolution primitives that the LLM calls as tools:

    find_persona(name)               → Persona | None
    get_contact(persona_id, channel) → Contact | None

Personas: real-world entities (people, companies, orgs) known to YANA.
Contacts: how to reach a Persona on a specific channel.
Named Channels: destinations without a Persona (e.g. a large Slack channel).

Storage backends:
  - DB mode (default): reads/writes PostgreSQL via store/contacts.py.
  - YAML mode (legacy/tests): reads/writes YAML files, activated by passing
    paths to load().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Persona:
    id: str
    name: str
    type: str  # "person" | "company" | "org"
    owner: str
    aliases: list[str] = field(default_factory=list)
    context: str = ""
    tags: list[str] = field(default_factory=list)
    # Shadow copy tracking — list of {provider, source_id} dicts
    # e.g. [{"provider": "google", "source_id": "people/c1234567"}]
    sources: list[dict] = field(default_factory=list)


@dataclass
class Contact:
    id: str
    persona_id: str
    channel: str  # "email" | "whatsapp" | "slack" | "sms" | "telegram"
    address: str
    connector_id: str
    preferred: bool = False


@dataclass
class NamedChannel:
    id: str
    name: str
    channel: str
    address: str
    connector_id: str
    aliases: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ContactRegistry:
    """
    In-memory registry of Personas, Contacts, and Named Channels.

    Default mode: DB backend via store/contacts.py (PostgreSQL in production,
    injectable SQLAlchemy engine for tests).

    Legacy/test mode: YAML backend — activated when paths are passed to load().
    Preserves full backward compatibility with existing tests.
    """

    def __init__(self, engine: Any = None) -> None:
        """
        Args:
            engine: Optional SQLAlchemy engine for DB mode.  Pass a SQLite
                in-memory engine in unit tests to avoid a real database.
                If None and DB mode is active, uses store._get_engine().
        """
        self._personas: dict[str, Persona] = {}
        self._contacts: list[Contact] = []
        self._named_channels: list[NamedChannel] = []

        # YAML-mode state (populated only when paths are given to load())
        self._use_db: bool = True
        self._personas_path: Path | None = None
        self._contacts_path: Path | None = None

        # DB-mode engine (None → resolved lazily from store._get_engine())
        self._engine = engine

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(
        self,
        personas_path: Path | None = None,
        contacts_path: Path | None = None,
    ) -> None:
        """
        Load the registry.

        Call with no arguments (or engine injected via __init__) to use DB mode.
        Call with both path arguments to use YAML mode (legacy / tests).
        """
        if personas_path is not None:
            # YAML mode — legacy and tests
            self._use_db = False
            self._personas_path = Path(personas_path)
            self._contacts_path = Path(contacts_path) if contacts_path is not None else None
            self._load_from_yaml(self._personas_path, self._contacts_path)
        else:
            self._use_db = True
            self._load_from_db()

    def _load_from_yaml(self, personas_path: Path, contacts_path: Path | None) -> None:
        self._personas = {}
        self._contacts = []
        self._named_channels = []
        self._load_personas_yaml(personas_path)
        if contacts_path is not None:
            self._load_contacts_yaml(contacts_path)

    def _load_personas_yaml(self, path: Path) -> None:
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for entry in data.get("personas", []):
            p = Persona(
                id=entry["id"],
                name=entry["name"],
                type=entry.get("type", "person"),
                owner=entry.get("owner", ""),
                aliases=entry.get("aliases", []),
                context=entry.get("context", ""),
                tags=entry.get("tags", []),
                sources=entry.get("sources", []),
            )
            self._personas[p.id] = p

    def _load_contacts_yaml(self, path: Path) -> None:
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for entry in data.get("contacts", []):
            c = Contact(
                id=entry["id"],
                persona_id=entry["persona_id"],
                channel=entry["channel"],
                address=entry["address"],
                connector_id=entry["connector_id"],
                preferred=entry.get("preferred", False),
            )
            self._contacts.append(c)
        for entry in data.get("named_channels", []):
            nc = NamedChannel(
                id=entry["id"],
                name=entry["name"],
                channel=entry["channel"],
                address=entry["address"],
                connector_id=entry["connector_id"],
                aliases=entry.get("aliases", []),
            )
            self._named_channels.append(nc)

    def _load_from_db(self) -> None:
        from store.contacts import list_contacts_sync, list_named_channels_sync, list_personas_sync

        self._personas = {}
        self._contacts = []
        self._named_channels = []

        for d in list_personas_sync(engine=self._engine):
            p = Persona(
                id=d["id"],
                name=d["name"],
                type=d["type"],
                owner=d["owner"],
                aliases=d["aliases"],
                context=d["context"],
                tags=d["tags"],
                sources=d["sources"],
            )
            self._personas[p.id] = p

        for d in list_contacts_sync(engine=self._engine):
            c = Contact(
                id=d["id"],
                persona_id=d["persona_id"],
                channel=d["channel"],
                address=d["address"],
                connector_id=d["connector_id"],
                preferred=d["preferred"],
            )
            self._contacts.append(c)

        for d in list_named_channels_sync(engine=self._engine):
            nc = NamedChannel(
                id=d["id"],
                name=d["name"],
                channel=d["channel"],
                address=d["address"],
                connector_id=d["connector_id"],
                aliases=d["aliases"],
            )
            self._named_channels.append(nc)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def find_persona(self, name: str) -> Persona | None:
        """
        Resolve a name to a Persona.

        Tries exact ID match first, then alias match (case-insensitive).
        Returns None if no match — caller should ask for clarification.
        Returns the first match if multiple aliases match the same name.
        """
        needle = name.strip().lower()

        # Exact ID match
        if needle in self._personas:
            return self._personas[needle]

        # Alias match
        matches = [
            p for p in self._personas.values()
            if any(a.lower() == needle for a in p.aliases)
        ]
        return matches[0] if len(matches) == 1 else None

    def find_persona_ambiguous(self, name: str) -> list[Persona]:
        """
        Return all Personas whose id or aliases match *name*.

        Resolution order:
        1. Exact id or alias match (case-insensitive) — highest priority.
        2. If no exact matches, fall back to "first-word" match: any persona
           whose first alias word equals *name* (e.g. "Fernanda" matches
           "Fernanda Silva", "Fernanda Santos").

        If len > 1, YANA should ask the user for clarification.
        """
        needle = name.strip().lower()

        exact = [
            p for p in self._personas.values()
            if p.id == needle or any(a.lower() == needle for a in p.aliases)
        ]
        if exact:
            return exact

        # First-word fallback: "Fernanda" → any alias whose first word is "fernanda"
        return [
            p for p in self._personas.values()
            if any(a.split()[0].lower() == needle for a in p.aliases if a.split())
        ]

    def get_contact(
        self,
        persona_id: str,
        channel: str | None = None,
    ) -> Contact | None:
        """
        Return the Contact for *persona_id* on *channel*.

        If *channel* is None, returns the preferred contact.
        If no preferred contact exists, returns the first contact for that persona.
        Returns None if persona has no contacts at all.
        """
        persona_contacts = [c for c in self._contacts if c.persona_id == persona_id]
        if not persona_contacts:
            return None

        if channel:
            channel_contacts = [c for c in persona_contacts if c.channel == channel]
            return channel_contacts[0] if channel_contacts else None

        preferred = [c for c in persona_contacts if c.preferred]
        return preferred[0] if preferred else persona_contacts[0]

    def find_by_source(self, provider: str, source_id: str) -> Persona | None:
        """Find a Persona by its external source reference."""
        for p in self._personas.values():
            for s in p.sources:
                if s.get("provider") == provider and s.get("source_id") == source_id:
                    return p
        return None

    def get_named_channel(self, name: str) -> NamedChannel | None:
        """Resolve a Named Channel by name or alias (case-insensitive)."""
        needle = name.strip().lower()
        for nc in self._named_channels:
            if nc.id == needle or nc.name.lower() == needle:
                return nc
            if any(a.lower() == needle for a in nc.aliases):
                return nc
        return None

    # ------------------------------------------------------------------
    # Serialisation helpers (for YANA to add/update entries)
    # ------------------------------------------------------------------

    def all_personas(self) -> list[dict[str, Any]]:
        return [
            {
                "id": p.id,
                "name": p.name,
                "type": p.type,
                "owner": p.owner,
                "aliases": p.aliases,
                "context": p.context,
                "tags": p.tags,
                **({"sources": p.sources} if p.sources else {}),
            }
            for p in self._personas.values()
        ]

    def all_contacts(self) -> list[dict[str, Any]]:
        return [
            {
                "id": c.id,
                "persona_id": c.persona_id,
                "channel": c.channel,
                "address": c.address,
                "connector_id": c.connector_id,
                "preferred": c.preferred,
            }
            for c in self._contacts
        ]

    def all_named_channels(self) -> list[dict[str, Any]]:
        return [
            {
                "id": nc.id,
                "name": nc.name,
                "channel": nc.channel,
                "address": nc.address,
                "connector_id": nc.connector_id,
                "aliases": nc.aliases,
            }
            for nc in self._named_channels
        ]

    def save(self) -> None:
        """Persist current in-memory state to the configured backend."""
        if self._use_db:
            self._save_to_db()
        else:
            self._save_to_yaml()

    def _save_to_yaml(self) -> None:
        """Write current state back to the YAML files (legacy/test mode)."""
        if self._personas_path is not None:
            with open(self._personas_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    {"personas": self.all_personas()},
                    f,
                    allow_unicode=True,
                    sort_keys=False,
                )
        if self._contacts_path is not None:
            with open(self._contacts_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    {
                        "contacts": self.all_contacts(),
                        "named_channels": self.all_named_channels(),
                    },
                    f,
                    allow_unicode=True,
                    sort_keys=False,
                )

    def _save_to_db(self) -> None:
        """Write current in-memory state to the DB (production mode)."""
        from store.contacts import (
            delete_named_channel_sync,
            delete_persona_sync,
            list_contacts_sync,
            list_named_channels_sync,
            list_personas_sync,
            upsert_contact_sync,
            upsert_named_channel_sync,
            upsert_persona_sync,
        )

        engine = self._engine

        # Sync personas: upsert all in-memory, delete any removed from DB
        current_ids = set(self._personas.keys())
        for d in self.all_personas():
            upsert_persona_sync(d, engine=engine)
        for d in list_personas_sync(engine=engine):
            if d["id"] not in current_ids:
                delete_persona_sync(d["id"], engine=engine)

        # Sync contacts: full replacement per persona_id
        db_contact_ids = {d["id"] for d in list_contacts_sync(engine=engine)}
        mem_contact_ids = {c.id for c in self._contacts}
        # Upsert all in-memory contacts
        for c in self._contacts:
            upsert_contact_sync(self._contact_to_dict(c), engine=engine)
        # Delete any contacts removed from memory
        for cid in db_contact_ids - mem_contact_ids:
            # We need to delete by id — use a targeted delete
            from store.contacts import _session as _store_session
            from store.models import ContactRecord
            with _store_session(engine) as s:
                r = s.get(ContactRecord, cid)
                if r:
                    s.delete(r)
                    s.commit()

        # Sync named channels: upsert all in-memory, delete removed
        db_nc_ids = {d["id"] for d in list_named_channels_sync(engine=engine)}
        mem_nc_ids = {nc.id for nc in self._named_channels}
        for nc in self._named_channels:
            upsert_named_channel_sync(self._nc_to_dict(nc), engine=engine)
        for ncid in db_nc_ids - mem_nc_ids:
            delete_named_channel_sync(ncid, engine=engine)

    @staticmethod
    def _contact_to_dict(c: Contact) -> dict[str, Any]:
        return {
            "id": c.id,
            "persona_id": c.persona_id,
            "channel": c.channel,
            "address": c.address,
            "connector_id": c.connector_id,
            "preferred": c.preferred,
        }

    @staticmethod
    def _nc_to_dict(nc: NamedChannel) -> dict[str, Any]:
        return {
            "id": nc.id,
            "name": nc.name,
            "channel": nc.channel,
            "address": nc.address,
            "connector_id": nc.connector_id,
            "aliases": nc.aliases,
        }
