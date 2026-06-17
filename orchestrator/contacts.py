"""
contacts.py — Persona and Contact registry for YANA.

Loads personas.yaml and contacts.yaml, providing two resolution primitives
that the LLM calls as tools:

    find_persona(name)               → Persona | None
    get_contact(persona_id, channel) → Contact | None

Personas: real-world entities (people, companies, orgs) known to YANA.
Contacts: how to reach a Persona on a specific channel.
Named Channels: destinations without a Persona (e.g. a large Slack channel).

Both YAML files are owned by YANA and by Fred — either can edit them.
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

    Loaded once from config files; supports fuzzy name resolution for the LLM.
    """

    def __init__(self) -> None:
        self._personas: dict[str, Persona] = {}
        self._contacts: list[Contact] = []
        self._named_channels: list[NamedChannel] = []
        self._personas_path: Path | None = None
        self._contacts_path: Path | None = None

    def load(
        self,
        personas_path: Path,
        contacts_path: Path,
    ) -> None:
        self._personas_path = personas_path
        self._contacts_path = contacts_path
        self._load_personas(personas_path)
        self._load_contacts(contacts_path)

    def _load_personas(self, path: Path) -> None:
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

    def _load_contacts(self, path: Path) -> None:
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
        Return all Personas whose aliases match *name*.
        Used to detect ambiguity — if len > 1, YANA should ask for clarification.
        """
        needle = name.strip().lower()
        return [
            p for p in self._personas.values()
            if p.id == needle or any(a.lower() == needle for a in p.aliases)
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
        """Persist current state back to the YAML files loaded via load()."""
        if self._personas_path is not None:
            with open(self._personas_path, "w", encoding="utf-8") as f:
                yaml.dump({"personas": self.all_personas()}, f, allow_unicode=True, sort_keys=False)
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
