"""
tests/test_contacts_connector.py — Contract tests for ContactsConnector.

Verifies the connector's @query/@command operations via the call() API,
matching the error contracts defined in the docstring.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# Make connectors/ importable
_CONNECTORS_DIR = Path(__file__).parent.parent.parent / "connectors"
if str(_CONNECTORS_DIR) not in sys.path:
    sys.path.insert(0, str(_CONNECTORS_DIR))

from contacts_connector import ContactsConnector  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture — connector with in-memory YAML config
# ---------------------------------------------------------------------------


@pytest.fixture
def connector(tmp_path: Path) -> ContactsConnector:
    personas_path = tmp_path / "personas.yaml"
    contacts_path = tmp_path / "contacts.yaml"

    personas_path.write_text(
        yaml.dump(
            {
                "personas": [
                    {
                        "id": "fred",
                        "name": "Fred",
                        "type": "person",
                        "owner": "fred",
                        "aliases": ["eu", "Fred"],
                        "context": "dono do sistema",
                        "tags": ["owner"],
                    },
                    {
                        "id": "ana",
                        "name": "Ana",
                        "type": "person",
                        "owner": "fred",
                        "aliases": ["Ana", "esposa"],
                        "context": "esposa",
                        "tags": ["family"],
                    },
                    {
                        "id": "joao_pt",
                        "name": "João PT",
                        "type": "person",
                        "owner": "fred",
                        "aliases": ["João"],
                        "context": "personal trainer",
                        "tags": [],
                    },
                    {
                        "id": "joao_contador",
                        "name": "João Contador",
                        "type": "person",
                        "owner": "fred",
                        "aliases": ["João"],
                        "context": "contador",
                        "tags": [],
                    },
                ]
            }
        )
    )

    contacts_path.write_text(
        yaml.dump(
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
                        "address": "+55999",
                        "connector_id": "whatsapp",
                        "preferred": True,
                    },
                ],
                "named_channels": [
                    {
                        "id": "vtex_general",
                        "name": "canal geral VTEX",
                        "channel": "slack",
                        "address": "C123",
                        "connector_id": "slack_vtex",
                        "aliases": ["#geral-vtex"],
                    }
                ],
            }
        )
    )

    return ContactsConnector(
        personas_file=str(personas_path),
        contacts_file=str(contacts_path),
    )


# ---------------------------------------------------------------------------
# find_persona
# ---------------------------------------------------------------------------


def test_find_persona_exact_match(connector: ContactsConnector) -> None:
    result = connector.call("find_persona", {"name": "fred"})
    assert result.ok
    assert result.data["id"] == "fred"
    assert result.data["name"] == "Fred"


def test_find_persona_by_alias(connector: ContactsConnector) -> None:
    result = connector.call("find_persona", {"name": "esposa"})
    assert result.ok
    assert result.data["id"] == "ana"


def test_find_persona_not_found(connector: ContactsConnector) -> None:
    result = connector.call("find_persona", {"name": "contador"})
    assert not result.ok
    assert "not_found" in result.error


def test_find_persona_ambiguous(connector: ContactsConnector) -> None:
    result = connector.call("find_persona", {"name": "João"})
    assert not result.ok
    assert "ambiguous" in result.error
    assert "joao_pt" in result.error or "João PT" in result.error


def test_find_persona_by_first_word(connector: ContactsConnector) -> None:
    """Searching by first name alone should match multi-word aliases (first-word fallback)."""
    result = connector.call("find_persona", {"name": "ana"})
    assert result.ok
    assert result.data["id"] == "ana"


def test_find_persona_first_word_ambiguous(connector: ContactsConnector) -> None:
    """First-word fallback is still ambiguous when multiple personas share the same first name."""
    # Both joao_pt and joao_contador have "João" as the first word of their aliases
    result = connector.call("find_persona", {"name": "João"})
    assert not result.ok
    assert "ambiguous" in result.error


def test_find_persona_first_word_no_false_positive(connector: ContactsConnector) -> None:
    """A word that only appears mid-alias does NOT trigger the first-word fallback."""
    # "PT" is the second word of "João PT" — should NOT match
    result = connector.call("find_persona", {"name": "PT"})
    assert not result.ok
    assert "not_found" in result.error


# ---------------------------------------------------------------------------
# get_contact
# ---------------------------------------------------------------------------


def test_get_contact_preferred(connector: ContactsConnector) -> None:
    result = connector.call("get_contact", {"persona_id": "fred"})
    assert result.ok
    assert result.data["channel"] == "email"
    assert result.data["connector_id"] == "gmail_fred_personal"


def test_get_contact_by_channel(connector: ContactsConnector) -> None:
    result = connector.call("get_contact", {"persona_id": "ana", "channel": "whatsapp"})
    assert result.ok
    assert result.data["address"] == "+55999"


def test_get_contact_missing_channel(connector: ContactsConnector) -> None:
    result = connector.call("get_contact", {"persona_id": "fred", "channel": "slack"})
    assert not result.ok
    assert "no_channel" in result.error


def test_get_contact_unknown_persona(connector: ContactsConnector) -> None:
    result = connector.call("get_contact", {"persona_id": "ghost"})
    assert not result.ok
    assert "not_found" in result.error


# ---------------------------------------------------------------------------
# get_named_channel
# ---------------------------------------------------------------------------


def test_get_named_channel_found(connector: ContactsConnector) -> None:
    result = connector.call("get_named_channel", {"name": "#geral-vtex"})
    assert result.ok
    assert result.data["connector_id"] == "slack_vtex"
    assert result.data["channel"] == "slack"


def test_get_named_channel_not_found(connector: ContactsConnector) -> None:
    result = connector.call("get_named_channel", {"name": "nonexistent"})
    assert not result.ok
    assert "not_found" in result.error


# ---------------------------------------------------------------------------
# upsert_persona
# ---------------------------------------------------------------------------


def test_upsert_persona_adds_new(connector: ContactsConnector) -> None:
    result = connector.call(
        "upsert_persona",
        {
            "id": "contador",
            "name": "Dr. Ribeiro",
            "type": "person",
            "aliases": ["contador", "Dr. Ribeiro"],
            "context": "contador do Fred",
        },
    )
    assert result.ok

    # Now resolvable
    result2 = connector.call("find_persona", {"name": "contador"})
    assert result2.ok
    assert result2.data["id"] == "contador"


# ---------------------------------------------------------------------------
# upsert_named_channel
# ---------------------------------------------------------------------------


def test_upsert_named_channel_adds_new(connector: ContactsConnector) -> None:
    result = connector.call(
        "upsert_named_channel",
        {
            "id": "familia_whatsapp",
            "name": "grupo família",
            "channel": "whatsapp",
            "address": "+55group123",
            "connector_id": "whatsapp",
            "aliases": ["família", "grupo da família"],
        },
    )
    assert result.ok

    result2 = connector.call("get_named_channel", {"name": "grupo família"})
    assert result2.ok
    assert result2.data["id"] == "familia_whatsapp"


def test_upsert_named_channel_replaces_existing(connector: ContactsConnector) -> None:
    connector.call(
        "upsert_named_channel",
        {
            "id": "vtex_general",
            "name": "canal geral VTEX",
            "channel": "slack",
            "address": "C999",  # updated address
            "connector_id": "slack_vtex",
        },
    )
    result = connector.call("get_named_channel", {"name": "canal geral VTEX"})
    assert result.ok
    assert result.data["address"] == "C999"


# ---------------------------------------------------------------------------
# Persistence — upserts survive a reload
# ---------------------------------------------------------------------------


def test_upsert_persona_persists(tmp_path: Path) -> None:
    """upsert_persona writes to YAML — a new connector loaded from the same files sees it."""
    personas_path = tmp_path / "personas.yaml"
    contacts_path = tmp_path / "contacts.yaml"
    personas_path.write_text(yaml.dump({"personas": []}))
    contacts_path.write_text(yaml.dump({"contacts": [], "named_channels": []}))

    c1 = ContactsConnector(
        personas_file=str(personas_path), contacts_file=str(contacts_path)
    )
    c1.call(
        "upsert_persona",
        {"id": "novo", "name": "Novo", "aliases": ["novo"]},
    )

    c2 = ContactsConnector(
        personas_file=str(personas_path), contacts_file=str(contacts_path)
    )
    result = c2.call("find_persona", {"name": "novo"})
    assert result.ok
    assert result.data["id"] == "novo"


def test_upsert_named_channel_persists(tmp_path: Path) -> None:
    """upsert_named_channel writes to YAML — a new connector loaded from the same files sees it."""
    personas_path = tmp_path / "personas.yaml"
    contacts_path = tmp_path / "contacts.yaml"
    personas_path.write_text(yaml.dump({"personas": []}))
    contacts_path.write_text(yaml.dump({"contacts": [], "named_channels": []}))

    c1 = ContactsConnector(
        personas_file=str(personas_path), contacts_file=str(contacts_path)
    )
    c1.call(
        "upsert_named_channel",
        {
            "id": "familia_wpp",
            "name": "família whatsapp",
            "channel": "whatsapp",
            "address": "+55group1",
            "connector_id": "whatsapp",
        },
    )

    c2 = ContactsConnector(
        personas_file=str(personas_path), contacts_file=str(contacts_path)
    )
    result = c2.call("get_named_channel", {"name": "família whatsapp"})
    assert result.ok
    assert result.data["id"] == "familia_wpp"


# ---------------------------------------------------------------------------
# Contract — operations exposed
# ---------------------------------------------------------------------------


def test_connector_operations_declared() -> None:
    ops = set(ContactsConnector._operations.keys())
    assert ops == {
        "list_personas",
        "find_persona",
        "get_contact",
        "get_named_channel",
        "upsert_persona",
        "upsert_named_channel",
        "delete_persona",
        "set_preferred_contact",
    }


# ---------------------------------------------------------------------------
# list_personas
# ---------------------------------------------------------------------------


def test_list_personas_no_filter_returns_all(connector: ContactsConnector) -> None:
    result = connector.call("list_personas", {})
    assert result.ok
    ids = {p["id"] for p in result.data}
    assert {"fred", "ana", "joao_pt", "joao_contador"} == ids


def test_list_personas_filter_by_name_fragment(connector: ContactsConnector) -> None:
    result = connector.call("list_personas", {"filter": "joão"})
    assert result.ok
    ids = {p["id"] for p in result.data}
    assert ids == {"joao_pt", "joao_contador"}


def test_list_personas_filter_no_match_returns_empty(connector: ContactsConnector) -> None:
    result = connector.call("list_personas", {"filter": "xyz_naoexiste"})
    assert result.ok
    assert result.data == []


def test_list_personas_includes_sources(connector: ContactsConnector) -> None:
    result = connector.call("list_personas", {"filter": "fred"})
    assert result.ok
    assert "sources" in result.data[0]


# ---------------------------------------------------------------------------
# delete_persona
# ---------------------------------------------------------------------------


def test_delete_persona_removes_persona_and_contacts(connector: ContactsConnector) -> None:
    result = connector.call("delete_persona", {"persona_id": "ana"})
    assert result.ok

    result2 = connector.call("find_persona", {"name": "ana"})
    assert not result2.ok
    assert "not_found" in result2.error

    # Her contact should also be gone
    result3 = connector.call("get_contact", {"persona_id": "ana"})
    assert not result3.ok
    assert "not_found" in result3.error


def test_delete_persona_not_found(connector: ContactsConnector) -> None:
    result = connector.call("delete_persona", {"persona_id": "nao_existe"})
    assert not result.ok
    assert "not_found" in result.error


def test_delete_persona_persists(tmp_path: Path) -> None:
    personas_path = tmp_path / "personas.yaml"
    contacts_path = tmp_path / "contacts.yaml"
    personas_path.write_text(yaml.dump({"personas": [{"id": "fantasma", "name": "Fantasma",
        "type": "person", "owner": "fred", "aliases": ["Fantasma"], "context": ""}]}))
    contacts_path.write_text(yaml.dump({"contacts": [], "named_channels": []}))

    c1 = ContactsConnector(personas_file=str(personas_path), contacts_file=str(contacts_path))
    c1.call("delete_persona", {"persona_id": "fantasma"})

    c2 = ContactsConnector(personas_file=str(personas_path), contacts_file=str(contacts_path))
    result = c2.call("find_persona", {"name": "Fantasma"})
    assert not result.ok
    assert "not_found" in result.error
