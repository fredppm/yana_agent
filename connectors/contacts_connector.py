"""
connectors/contacts_connector.py — ContactsConnector.

Exposes the ContactRegistry as a Connector so the LLM can call:

    find_persona(name)                   → persona info or ambiguity signal
    get_contact(persona_id, channel?)    → address + via_connector to use

Resolution contract:
  - find_persona returns ok=True with data if exactly one match.
  - find_persona returns ok=False, error="ambiguous" with a list of candidates
    if multiple personas share the alias — YANA should ask for clarification.
  - find_persona returns ok=False, error="not_found" if no match at all.
  - get_contact returns ok=False, error="not_found" if persona has no contacts,
    or ok=False, error="no_channel" if the requested channel is unavailable.

Register in orchestrator/config/connectors.yaml:

    - type: ContactsConnector
      id: contacts
      name: "Contacts"
      description: "Resolve personas and contacts — find who someone is and how to reach them"
      config: {}

For backward compatibility, optional file paths may be passed to activate YAML
mode (used by tests):

      config:
        personas_file: "orchestrator/config/personas.yaml"
        contacts_file: "orchestrator/config/contacts.yaml"
"""

from __future__ import annotations

import importlib.util as _ilu
import sys as _sys
from pathlib import Path
from typing import Any

from connectors import Connector, command, query

# ContactRegistry lives in orchestrator/contacts.py.
# Import via importlib to avoid naming collision with this file's package name.
_contacts_mod_path = Path(__file__).parent.parent / "orchestrator" / "contacts.py"
_spec = _ilu.spec_from_file_location("orchestrator.contacts", _contacts_mod_path)
_contacts_mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
_sys.modules["orchestrator.contacts"] = _contacts_mod
_spec.loader.exec_module(_contacts_mod)  # type: ignore[union-attr]
ContactRegistry = _contacts_mod.ContactRegistry


class ContactsConnector(Connector):
    connector_description = "Resolve personas and contacts — find who someone is and how to reach them"

    def __init__(
        self,
        personas_file: str | None = None,
        contacts_file: str | None = None,
    ) -> None:
        self._registry = ContactRegistry()

        if personas_file is not None:
            # YAML mode — activated by tests or legacy config
            personas_path = Path(personas_file)
            contacts_path = Path(contacts_file) if contacts_file is not None else None
            if not personas_path.is_absolute():
                personas_path = Path(__file__).parent.parent / personas_path
            if contacts_path is not None and not contacts_path.is_absolute():
                contacts_path = Path(__file__).parent.parent / contacts_path
            self._registry.load(personas_path, contacts_path)
        else:
            # DB mode — production; load once at startup; DB is the live source
            self._registry.load()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @query(
        description=(
            "List personas, optionally filtered by a name fragment. "
            "Use this when: the user asks to LIST contacts ('me lista as Fernandas'), "
            "the name might match multiple people, or you want to browse the registry. "
            "Do NOT use this to resolve a single specific person — use find_persona for that. "
            "filter: case-insensitive substring matched against id, name, and aliases. "
            "Returns a list of {id, name, aliases, vip, sources} objects."
        ),
        params={"filter": {"type": "string", "required": False}},
        returns={"type": "list"},
    )
    def list_personas(self, filter: str = "") -> list[dict[str, Any]]:
        needle = filter.strip().lower()
        results = []
        for p in self._registry._personas.values():
            if needle:
                in_id = needle in p.id.lower()
                in_name = needle in p.name.lower()
                in_aliases = any(needle in a.lower() for a in p.aliases)
                if not (in_id or in_name or in_aliases):
                    continue
            results.append({
                "id": p.id,
                "name": p.name,
                "aliases": p.aliases,
                "context": p.context,
                "vip": p.vip,
                "sources": p.sources,
            })
        results.sort(key=lambda x: x["name"].lower())
        return results

    @query(
        description=(
            "Resolve ONE specific person by name or alias. "
            "Use this only when the intent is to act on a single person "
            "('manda mensagem pra Fernanda', 'qual o email do João'). "
            "Do NOT use this for listing — use list_personas with a filter instead. "
            "Returns persona info if exactly one match. "
            "Returns error='ambiguous' with candidates if the name matches multiple people — "
            "call list_personas with the same filter to show the user the options. "
            "Returns error='not_found' if no match. "
            "After resolving, call list_contacts(persona_id) to see available channels."
        ),
        params={"name": {"type": "string", "required": True}},
        returns={"type": "object"},
    )
    def find_persona(self, name: str) -> dict[str, Any]:
        candidates = self._registry.find_persona_ambiguous(name)

        if len(candidates) == 0:
            raise ValueError("not_found")

        if len(candidates) > 1:
            # Signal ambiguity — caller should ask for clarification
            raise ValueError(
                f"ambiguous: {', '.join(f'{p.name} ({p.id})' for p in candidates)}"
            )

        p = candidates[0]
        return {
            "id": p.id,
            "name": p.name,
            "type": p.type,
            "context": p.context,
            "tags": p.tags,
            "vip": p.vip,
            "aliases": p.aliases,
        }

    @query(
        description=(
            "Get the contact address for a persona on a given channel. "
            "Pass channel to request a specific medium (email/whatsapp/slack/sms/telegram). "
            "Omit channel to use the persona's preferred channel. "
            "Returns the channel and address. Routing connector is resolved at send time "
            "from the connector registry — it is not stored in the contact."
        ),
        params={
            "persona_id": {"type": "string", "required": True},
            "channel": {"type": "string", "required": False},
        },
        returns={"type": "object"},
    )
    def get_contact(
        self, persona_id: str, channel: str | None = None
    ) -> dict[str, Any]:
        contact = self._registry.get_contact(persona_id, channel)
        if contact is None:
            if channel:
                raise ValueError(f"no_channel: {persona_id} has no {channel} contact")
            raise ValueError(f"not_found: no contacts for persona {persona_id}")
        return {
            "id": contact.id,
            "persona_id": contact.persona_id,
            "channel": contact.channel,
            "address": contact.address,
            "preferred": contact.preferred,
        }

    @query(
        description=(
            "Resolve a named channel (e.g. '#geral-vtex', 'canal geral da VTEX'). "
            "Named channels are destinations without a specific persona — large groups, "
            "mailing lists, broadcast channels. "
            "Returns channel info and via_connector to use for sending."
        ),
        params={"name": {"type": "string", "required": True}},
        returns={"type": "object"},
    )
    def get_named_channel(self, name: str) -> dict[str, Any]:
        nc = self._registry.get_named_channel(name)
        if nc is None:
            raise ValueError(f"not_found: named channel '{name}' not found")
        return {
            "id": nc.id,
            "name": nc.name,
            "channel": nc.channel,
            "address": nc.address,
            "via_connector": nc.via_connector,
        }

    # ------------------------------------------------------------------
    # Commands — YANA can add/update personas and contacts at runtime
    # ------------------------------------------------------------------

    @command(
        description=(
            "Add or update a persona. YANA calls this when learning about a new person, "
            "company, or organization from conversation."
        ),
        params={
            "id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "type": {"type": "string", "required": False},
            "aliases": {"type": "array", "required": False},
            "context": {"type": "string", "required": False},
            "tags": {"type": "array", "required": False},
            "vip": {"type": "boolean", "required": False},
        },
        returns={"type": "boolean"},
    )
    def upsert_persona(
        self,
        id: str,
        name: str,
        type: str = "person",
        aliases: list[str] | None = None,
        context: str = "",
        tags: list[str] | None = None,
        vip: bool = False,
    ) -> bool:
        Persona = _contacts_mod.Persona

        # Preserve sources if persona already exists
        existing = self._registry._personas.get(id)
        sources = existing.sources if existing is not None else []

        p = Persona(
            id=id,
            name=name,
            type=type,
            owner="fred",
            aliases=aliases or [],
            context=context,
            tags=tags or [],
            vip=vip,
            sources=sources,
        )
        self._registry._personas[id] = p
        self._registry.save()
        return True

    @command(
        description=(
            "Add or update a named channel. YANA calls this when the user teaches it "
            "about a new group, channel, or broadcast destination."
        ),
        params={
            "id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "channel": {"type": "string", "required": True},
            "address": {"type": "string", "required": True},
            "via_connector": {"type": "string", "required": True},
            "aliases": {"type": "array", "required": False},
        },
        returns={"type": "boolean"},
    )
    def upsert_named_channel(
        self,
        id: str,
        name: str,
        channel: str,
        address: str,
        via_connector: str,
        aliases: list[str] | None = None,
    ) -> bool:
        NamedChannel = _contacts_mod.NamedChannel

        nc = NamedChannel(
            id=id,
            name=name,
            channel=channel,
            address=address,
            via_connector=via_connector,
            aliases=aliases or [],
        )
        # Replace if exists, otherwise append
        self._registry._named_channels = [
            x for x in self._registry._named_channels if x.id != id
        ]
        self._registry._named_channels.append(nc)
        self._registry.save()
        return True

    @query(
        description=(
            "List all contact addresses for a persona — all channels (email, whatsapp, sms, etc). "
            "Use this when presenting full persona details or checking what channels are available. "
            "Returns a list of {channel, address, preferred, sources}."
        ),
        params={"persona_id": {"type": "string", "required": True}},
        returns={"type": "list"},
    )
    def list_contacts(self, persona_id: str) -> list[dict[str, Any]]:
        persona_contacts = [c for c in self._registry._contacts if c.persona_id == persona_id]
        return [
            {
                "channel": c.channel,
                "address": c.address,
                "preferred": c.preferred,
                "sources": c.sources,
            }
            for c in sorted(persona_contacts, key=lambda c: (not c.preferred, c.channel))
        ]

    @command(
        description=(
            "Add or update a contact address for a persona. "
            "Use this when the user tells you how to reach someone on a specific channel "
            "(e.g. 'a Fernanda, o WhatsApp dela é +55 21 99294-0714'). "
            "channel: 'email', 'whatsapp', 'sms', 'phone', 'slack', 'telegram'. "
            "Use 'phone' for a raw phone number when the delivery method is unknown — "
            "later, call upsert_contact again with channel='whatsapp' or 'sms' once confirmed. "
            "preferred: if true, marks this as the default channel for this persona. "
            "Returns error='not_found' if the persona_id does not exist."
        ),
        params={
            "persona_id": {"type": "string", "required": True},
            "channel": {"type": "string", "required": True},
            "address": {"type": "string", "required": True},
            "preferred": {"type": "boolean", "required": False},
        },
        returns={"type": "boolean"},
    )
    def upsert_contact(
        self,
        persona_id: str,
        channel: str,
        address: str,
        preferred: bool = False,
    ) -> bool:
        Contact = _contacts_mod.Contact

        if persona_id not in self._registry._personas:
            raise ValueError(f"not_found: persona '{persona_id}' does not exist")

        # If marking preferred, clear existing preferred flag for this persona
        if preferred:
            for c in self._registry._contacts:
                if c.persona_id == persona_id:
                    c.preferred = False

        # Build a stable id from persona + channel + address
        import re
        safe_addr = re.sub(r"[^a-z0-9]+", "_", address.lower()).strip("_")
        contact_id = f"{persona_id}_{channel}_{safe_addr}"

        # Preserve existing sources if contact already exists
        existing = next((c for c in self._registry._contacts if c.id == contact_id), None)
        sources = existing.sources if existing is not None else []

        # Replace if same id exists, otherwise append
        self._registry._contacts = [
            c for c in self._registry._contacts if c.id != contact_id
        ]
        self._registry._contacts.append(
            Contact(
                id=contact_id,
                persona_id=persona_id,
                channel=channel,
                address=address,
                preferred=preferred,
                sources=sources,
            )
        )
        self._registry.save()
        return True

    @command(
        description=(
            "Delete a persona and all their contacts from the registry. "
            "Use this to remove phantom or incorrect personas. "
            "Returns error='not_found' if the persona id does not exist."
        ),
        params={
            "persona_id": {"type": "string", "required": True},
        },
        returns={"type": "boolean"},
    )
    def delete_persona(self, persona_id: str) -> bool:
        if persona_id not in self._registry._personas:
            raise ValueError(f"not_found: persona '{persona_id}' does not exist")
        del self._registry._personas[persona_id]
        self._registry._contacts = [
            c for c in self._registry._contacts if c.persona_id != persona_id
        ]
        self._registry.save()
        return True

    @command(
        description=(
            "Set the preferred contact channel for a persona. "
            "After this, get_contact without a channel will return this channel. "
            "Returns error='not_found' if persona has no contacts. "
            "Returns error='no_channel' if the persona has no contact on that channel."
        ),
        params={
            "persona_id": {"type": "string", "required": True},
            "channel": {"type": "string", "required": True},
        },
        returns={"type": "boolean"},
    )
    def set_preferred_contact(self, persona_id: str, channel: str) -> bool:
        persona_contacts = [c for c in self._registry._contacts if c.persona_id == persona_id]
        if not persona_contacts:
            raise ValueError(f"not_found: no contacts for persona {persona_id}")

        target = [c for c in persona_contacts if c.channel == channel]
        if not target:
            raise ValueError(f"no_channel: {persona_id} has no {channel} contact")

        for c in persona_contacts:
            c.preferred = c.channel == channel
        self._registry.save()
        return True

    @command(
        description=(
            "Merge two personas into one — the duplicate is absorbed into the base. "
            "Use this when YANA has two entries for the same person, e.g. 'Fernanda Moreira' "
            "from Google and 'Fernanda Oliveira' from Apple that are actually the same person. "
            "After the merge: the base persona keeps its name, context, and tags; "
            "aliases and contacts from the duplicate are moved over; "
            "sources from both are merged (deduplicated by source_id); "
            "the duplicate persona and its contacts are deleted. "
            "Returns error='not_found' if either id does not exist."
        ),
        params={
            "base_id": {"type": "string", "required": True},
            "duplicate_id": {"type": "string", "required": True},
        },
        returns={"type": "boolean"},
    )
    def merge_personas(self, base_id: str, duplicate_id: str) -> bool:
        Contact = _contacts_mod.Contact

        if base_id not in self._registry._personas:
            raise ValueError(f"not_found: base persona '{base_id}' does not exist")
        if duplicate_id not in self._registry._personas:
            raise ValueError(f"not_found: duplicate persona '{duplicate_id}' does not exist")

        base = self._registry._personas[base_id]
        dup = self._registry._personas[duplicate_id]

        # Merge aliases (deduplicated, case-insensitive).
        # Also absorb the duplicate's name so searching by it still resolves.
        base_aliases_lower = {a.lower() for a in base.aliases}
        for alias in [dup.name] + dup.aliases:
            if alias.lower() not in base_aliases_lower:
                base.aliases.append(alias)
                base_aliases_lower.add(alias.lower())

        # Merge sources (deduplicated by source_id)
        existing_source_ids = {s.get("source_id") for s in base.sources}
        for s in dup.sources:
            if s.get("source_id") not in existing_source_ids:
                base.sources.append(s)
                existing_source_ids.add(s.get("source_id"))

        # Merge tags (deduplicated)
        base_tags = set(base.tags)
        for tag in dup.tags:
            if tag not in base_tags:
                base.tags.append(tag)
                base_tags.add(tag)

        # Promote vip if duplicate was vip
        if dup.vip:
            base.vip = True

        # Move contacts from duplicate to base, dedup by deterministic id
        import re
        existing_contact_ids = {c.id for c in self._registry._contacts if c.persona_id == base_id}
        dup_contacts = [c for c in self._registry._contacts if c.persona_id == duplicate_id]
        for dc in dup_contacts:
            safe_addr = re.sub(r"[^a-z0-9]+", "_", dc.address.lower()).strip("_")
            new_id = f"{base_id}_{dc.channel}_{safe_addr}"
            if new_id not in existing_contact_ids:
                self._registry._contacts.append(Contact(
                    id=new_id,
                    persona_id=base_id,
                    channel=dc.channel,
                    address=dc.address,
                    preferred=dc.preferred,
                    sources=dc.sources,
                ))
                existing_contact_ids.add(new_id)

        # Delete duplicate persona and its contacts
        del self._registry._personas[duplicate_id]
        self._registry._contacts = [
            c for c in self._registry._contacts if c.persona_id != duplicate_id
        ]

        self._registry.save()
        return True

    @command(
        description=(
            "Set or clear the VIP flag on a persona. "
            "VIP contacts get priority treatment in YANA's responses. "
            "Returns error='not_found' if the persona id does not exist."
        ),
        params={
            "persona_id": {"type": "string", "required": True},
            "vip": {"type": "boolean", "required": True},
        },
        returns={"type": "boolean"},
    )
    def set_vip(self, persona_id: str, vip: bool) -> bool:
        if persona_id not in self._registry._personas:
            raise ValueError(f"not_found: persona '{persona_id}' does not exist")
        self._registry._personas[persona_id].vip = vip
        self._registry.save()
        return True
