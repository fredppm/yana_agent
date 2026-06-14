"""
tests/test_contacts.py — Unit tests for contacts.py (ContactRegistry).

No external deps, no file system side effects (uses tmp_path).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from contacts import Contact, ContactRegistry, NamedChannel, Persona


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(yaml.dump(data))
    return p


@pytest.fixture
def registry(tmp_path: Path) -> ContactRegistry:
    personas = _write(
        tmp_path,
        "personas.yaml",
        {
            "personas": [
                {
                    "id": "fred",
                    "name": "Fred",
                    "type": "person",
                    "owner": "fred",
                    "aliases": ["eu", "Fred", "Frederico"],
                    "context": "dono do sistema",
                    "tags": ["owner"],
                },
                {
                    "id": "ana",
                    "name": "Ana",
                    "type": "person",
                    "owner": "fred",
                    "aliases": ["Ana", "esposa"],
                    "context": "esposa do Fred",
                    "tags": ["family"],
                },
                {
                    "id": "joao_pt",
                    "name": "João Personal Trainer",
                    "type": "person",
                    "owner": "fred",
                    "aliases": ["João"],
                    "context": "personal trainer",
                    "tags": ["health"],
                },
                {
                    "id": "joao_contador",
                    "name": "João Contador",
                    "type": "person",
                    "owner": "fred",
                    "aliases": ["João"],
                    "context": "contador",
                    "tags": ["finance"],
                },
            ]
        },
    )
    contacts = _write(
        tmp_path,
        "contacts.yaml",
        {
            "contacts": [
                {
                    "id": "fred_email",
                    "persona_id": "fred",
                    "channel": "email",
                    "address": "fred@example.com",
                    "connector_id": "gmail_fred_personal",
                    "preferred": True,
                },
                {
                    "id": "ana_whatsapp",
                    "persona_id": "ana",
                    "channel": "whatsapp",
                    "address": "+55999999999",
                    "connector_id": "whatsapp_personal",
                    "preferred": True,
                },
                {
                    "id": "ana_email",
                    "persona_id": "ana",
                    "channel": "email",
                    "address": "ana@example.com",
                    "connector_id": "gmail_fred_personal",
                    "preferred": False,
                },
            ],
            "named_channels": [
                {
                    "id": "vtex_slack_general",
                    "name": "canal geral da VTEX",
                    "channel": "slack",
                    "address": "C123456",
                    "connector_id": "slack_vtex",
                    "aliases": ["#geral-vtex", "canal geral"],
                }
            ],
        },
    )
    reg = ContactRegistry()
    reg.load(personas, contacts)
    return reg


# ---------------------------------------------------------------------------
# find_persona
# ---------------------------------------------------------------------------


def test_find_persona_by_id(registry: ContactRegistry) -> None:
    p = registry.find_persona("fred")
    assert p is not None
    assert p.id == "fred"


def test_find_persona_by_alias_exact(registry: ContactRegistry) -> None:
    p = registry.find_persona("esposa")
    assert p is not None
    assert p.id == "ana"


def test_find_persona_by_alias_case_insensitive(registry: ContactRegistry) -> None:
    p = registry.find_persona("FRED")
    assert p is not None
    assert p.id == "fred"


def test_find_persona_unknown_returns_none(registry: ContactRegistry) -> None:
    assert registry.find_persona("contador") is None


def test_find_persona_ambiguous_returns_none(registry: ContactRegistry) -> None:
    # "João" matches two personas — should return None
    assert registry.find_persona("João") is None


def test_find_persona_ambiguous_returns_multiple(registry: ContactRegistry) -> None:
    matches = registry.find_persona_ambiguous("João")
    assert len(matches) == 2
    ids = {p.id for p in matches}
    assert ids == {"joao_pt", "joao_contador"}


# ---------------------------------------------------------------------------
# get_contact
# ---------------------------------------------------------------------------


def test_get_contact_preferred(registry: ContactRegistry) -> None:
    c = registry.get_contact("fred")
    assert c is not None
    assert c.channel == "email"
    assert c.preferred is True


def test_get_contact_by_channel(registry: ContactRegistry) -> None:
    c = registry.get_contact("ana", channel="email")
    assert c is not None
    assert c.address == "ana@example.com"


def test_get_contact_prefers_preferred_over_first(registry: ContactRegistry) -> None:
    # Ana has whatsapp (preferred=True) and email (preferred=False)
    c = registry.get_contact("ana")
    assert c is not None
    assert c.channel == "whatsapp"


def test_get_contact_unknown_persona_returns_none(registry: ContactRegistry) -> None:
    assert registry.get_contact("unknown_id") is None


def test_get_contact_missing_channel_returns_none(registry: ContactRegistry) -> None:
    assert registry.get_contact("fred", channel="slack") is None


# ---------------------------------------------------------------------------
# get_named_channel
# ---------------------------------------------------------------------------


def test_get_named_channel_by_id(registry: ContactRegistry) -> None:
    nc = registry.get_named_channel("vtex_slack_general")
    assert nc is not None
    assert nc.channel == "slack"


def test_get_named_channel_by_name(registry: ContactRegistry) -> None:
    nc = registry.get_named_channel("canal geral da VTEX")
    assert nc is not None
    assert nc.id == "vtex_slack_general"


def test_get_named_channel_by_alias(registry: ContactRegistry) -> None:
    nc = registry.get_named_channel("#geral-vtex")
    assert nc is not None
    assert nc.id == "vtex_slack_general"


def test_get_named_channel_unknown_returns_none(registry: ContactRegistry) -> None:
    assert registry.get_named_channel("nonexistent") is None


# ---------------------------------------------------------------------------
# Empty / missing files
# ---------------------------------------------------------------------------


def test_load_missing_files_does_not_raise(tmp_path: Path) -> None:
    reg = ContactRegistry()
    reg.load(tmp_path / "missing_personas.yaml", tmp_path / "missing_contacts.yaml")
    assert reg.find_persona("anyone") is None
    assert reg.get_contact("anyone") is None


# ---------------------------------------------------------------------------
# CommunicationChannel interface on GmailConnector
# ---------------------------------------------------------------------------


def test_gmail_is_communication_channel() -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "connectors"))
    from connectors import CommunicationChannel
    from gmail import GmailConnector

    assert issubclass(GmailConnector, CommunicationChannel)
