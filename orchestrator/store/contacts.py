"""store/contacts.py — Personas, Contacts, NamedChannels persistence."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .engine import _get_engine
from .models import ContactRecord, NamedChannelRecord, PersonaRecord


def _session(engine=None) -> Session:
    return Session(engine or _get_engine())


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------


def list_personas_sync(engine=None) -> list[dict]:
    with _session(engine) as s:
        return [_persona_to_dict(r) for r in s.query(PersonaRecord).all()]


def get_persona_sync(persona_id: str, engine=None) -> dict | None:
    with _session(engine) as s:
        r = s.get(PersonaRecord, persona_id)
        return _persona_to_dict(r) if r else None


def upsert_persona_sync(d: dict, engine=None) -> None:
    with _session(engine) as s:
        r = s.get(PersonaRecord, d["id"])
        if r is None:
            r = PersonaRecord(id=d["id"])
        r.name = d["name"]
        r.type = d.get("type", "person")
        r.owner = d.get("owner", "")
        r.aliases_json = json.dumps(d.get("aliases", []), ensure_ascii=False)
        r.context = d.get("context", "")
        r.tags_json = json.dumps(d.get("tags", []), ensure_ascii=False)
        r.sources_json = json.dumps(d.get("sources", []), ensure_ascii=False)
        s.merge(r)
        s.commit()


def delete_persona_sync(persona_id: str, engine=None) -> bool:
    with _session(engine) as s:
        r = s.get(PersonaRecord, persona_id)
        if not r:
            return False
        s.delete(r)
        s.commit()
        return True


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


def list_contacts_sync(engine=None) -> list[dict]:
    with _session(engine) as s:
        return [_contact_to_dict(r) for r in s.query(ContactRecord).all()]


def upsert_contact_sync(d: dict, engine=None) -> None:
    with _session(engine) as s:
        r = s.get(ContactRecord, d["id"])
        if r is None:
            r = ContactRecord(id=d["id"])
        r.persona_id = d["persona_id"]
        r.channel = d["channel"]
        r.address = d["address"]
        r.connector_id = d["connector_id"]
        r.preferred = 1 if d.get("preferred") else 0
        s.merge(r)
        s.commit()


def delete_contacts_for_persona_sync(persona_id: str, engine=None) -> None:
    with _session(engine) as s:
        s.query(ContactRecord).filter(ContactRecord.persona_id == persona_id).delete()
        s.commit()


def update_contacts_preferred_sync(persona_id: str, channel: str, engine=None) -> None:
    """Set preferred=True for the given channel, False for all others of that persona."""
    with _session(engine) as s:
        rows = s.query(ContactRecord).filter(ContactRecord.persona_id == persona_id).all()
        for r in rows:
            r.preferred = 1 if r.channel == channel else 0
        s.commit()


# ---------------------------------------------------------------------------
# Named Channels
# ---------------------------------------------------------------------------


def list_named_channels_sync(engine=None) -> list[dict]:
    with _session(engine) as s:
        return [_nc_to_dict(r) for r in s.query(NamedChannelRecord).all()]


def upsert_named_channel_sync(d: dict, engine=None) -> None:
    with _session(engine) as s:
        r = s.get(NamedChannelRecord, d["id"])
        if r is None:
            r = NamedChannelRecord(id=d["id"])
        r.name = d["name"]
        r.channel = d["channel"]
        r.address = d["address"]
        r.connector_id = d["connector_id"]
        r.aliases_json = json.dumps(d.get("aliases", []), ensure_ascii=False)
        s.merge(r)
        s.commit()


def delete_named_channel_sync(nc_id: str, engine=None) -> bool:
    with _session(engine) as s:
        r = s.get(NamedChannelRecord, nc_id)
        if not r:
            return False
        s.delete(r)
        s.commit()
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _persona_to_dict(r: PersonaRecord) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "type": r.type,
        "owner": r.owner,
        "aliases": json.loads(r.aliases_json),
        "context": r.context,
        "tags": json.loads(r.tags_json),
        "sources": json.loads(r.sources_json),
    }


def _contact_to_dict(r: ContactRecord) -> dict:
    return {
        "id": r.id,
        "persona_id": r.persona_id,
        "channel": r.channel,
        "address": r.address,
        "connector_id": r.connector_id,
        "preferred": bool(r.preferred),
    }


def _nc_to_dict(r: NamedChannelRecord) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "channel": r.channel,
        "address": r.address,
        "connector_id": r.connector_id,
        "aliases": json.loads(r.aliases_json),
    }
