"""
connectors/contacts_connector.py — ContactsConnector.

Exposes the ContactRegistry as a Connector so the LLM can call:

    find_persona(name)                   → persona info or ambiguity signal
    get_contact(persona_id, channel?)    → address + connector_id to use

Resolution contract:
  - find_persona returns ok=True with data if exactly one match.
  - find_persona returns ok=False, error="ambiguous" with data=[list of matches]
    if multiple personas share the alias — YANA should ask for clarification.
  - find_persona returns ok=False, error="not_found" if no match at all.
  - get_contact returns ok=False, error="not_found" if persona has no contacts,
    or ok=False, error="no_channel" if the requested channel is unavailable.

Register in orchestrator/config/connectors.yaml:

    - type: ContactsConnector
      id: contacts
      name: "Contacts"
      description: "Resolve personas and contacts — find who someone is and how to reach them"
      config:
        personas_file: "orchestrator/config/personas.yaml"
        contacts_file: "orchestrator/config/contacts.yaml"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from connectors import Connector, ConnectorResult, command, query

# ContactRegistry lives in orchestrator/contacts.py.
# Import via importlib to avoid naming collision with this file's package name.
import importlib.util as _ilu
import sys as _sys

_contacts_mod_path = Path(__file__).parent.parent / "orchestrator" / "contacts.py"
_spec = _ilu.spec_from_file_location("orchestrator.contacts", _contacts_mod_path)
_contacts_mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
_sys.modules["orchestrator.contacts"] = _contacts_mod
_spec.loader.exec_module(_contacts_mod)  # type: ignore[union-attr]
ContactRegistry = _contacts_mod.ContactRegistry

_DEFAULT_PERSONAS = "orchestrator/config/personas.yaml"
_DEFAULT_CONTACTS = "orchestrator/config/contacts.yaml"


class ContactsConnector(Connector):
    connector_description = "Resolve personas and contacts — find who someone is and how to reach them"

    def __init__(
        self,
        personas_file: str | None = None,
        contacts_file: str | None = None,
    ) -> None:
        self._registry = ContactRegistry()
        personas_path = Path(personas_file or _DEFAULT_PERSONAS)
        contacts_path = Path(contacts_file or _DEFAULT_CONTACTS)
        # Resolve relative paths from the project root
        if not personas_path.is_absolute():
            personas_path = Path(__file__).parent.parent / personas_path
        if not contacts_path.is_absolute():
            contacts_path = Path(__file__).parent.parent / contacts_path
        self._registry.load(personas_path, contacts_path)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @query(
        description=(
            "Find a persona by name or alias. "
            "Returns persona info if exactly one match. "
            "Returns error='ambiguous' with a list of candidates if the name is ambiguous — "
            "ask the user to clarify. "
            "Returns error='not_found' if no persona matches."
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
        }

    @query(
        description=(
            "Get the contact address for a persona on a given channel. "
            "Pass channel to request a specific medium (email/whatsapp/slack/sms/telegram). "
            "Omit channel to use the persona's preferred channel. "
            "Returns address and connector_id to use for sending."
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
            "connector_id": contact.connector_id,
            "preferred": contact.preferred,
        }

    @query(
        description=(
            "Resolve a named channel (e.g. '#geral-vtex', 'canal geral da VTEX'). "
            "Named channels are destinations without a specific persona — large groups, "
            "mailing lists, broadcast channels. "
            "Returns channel info and connector_id to use for sending."
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
            "connector_id": nc.connector_id,
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
    ) -> bool:
        Persona = _contacts_mod.Persona

        p = Persona(
            id=id,
            name=name,
            type=type,
            owner="fred",
            aliases=aliases or [],
            context=context,
            tags=tags or [],
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
            "connector_id": {"type": "string", "required": True},
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
        connector_id: str,
        aliases: list[str] | None = None,
    ) -> bool:
        NamedChannel = _contacts_mod.NamedChannel

        nc = NamedChannel(
            id=id,
            name=name,
            channel=channel,
            address=address,
            connector_id=connector_id,
            aliases=aliases or [],
        )
        # Replace if exists, otherwise append
        self._registry._named_channels = [
            x for x in self._registry._named_channels if x.id != id
        ]
        self._registry._named_channels.append(nc)
        self._registry.save()
        return True
