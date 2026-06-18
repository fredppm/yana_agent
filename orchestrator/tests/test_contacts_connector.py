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
                        "via_connector": "gmail_fred_personal",
                        "preferred": True,
                    },
                    {
                        "id": "ana_whatsapp",
                        "persona_id": "ana",
                        "channel": "whatsapp",
                        "address": "+55999",
                        "via_connector": "whatsapp",
                        "preferred": True,
                    },
                ],
                "named_channels": [
                    {
                        "id": "vtex_general",
                        "name": "canal geral VTEX",
                        "channel": "slack",
                        "address": "C123",
                        "via_connector": "slack_vtex",
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
    assert result.data["address"] == "fred@example.com"


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
    assert result.data["via_connector"] == "slack_vtex"
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
            "via_connector": "whatsapp",
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
            "via_connector": "slack_vtex",
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
            "via_connector": "whatsapp",
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
        "list_contacts",
        "get_named_channel",
        "upsert_persona",
        "upsert_contact",
        "upsert_named_channel",
        "delete_persona",
        "set_preferred_contact",
        "merge_personas",
        "set_vip",
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


# ---------------------------------------------------------------------------
# list_contacts
# ---------------------------------------------------------------------------


def test_list_contacts_returns_all_channels(connector: ContactsConnector) -> None:
    result = connector.call("list_contacts", {"persona_id": "ana"})
    assert result.ok
    assert len(result.data) == 1
    assert result.data[0]["channel"] == "whatsapp"
    assert result.data[0]["address"] == "+55999"
    assert result.data[0]["preferred"] is True


def test_list_contacts_empty_for_no_contacts(connector: ContactsConnector) -> None:
    result = connector.call("list_contacts", {"persona_id": "joao_pt"})
    assert result.ok
    assert result.data == []


# ---------------------------------------------------------------------------
# upsert_contact
# ---------------------------------------------------------------------------


def test_upsert_contact_adds_new_channel(connector: ContactsConnector) -> None:
    result = connector.call(
        "upsert_contact",
        {
            "persona_id": "fred",
            "channel": "whatsapp",
            "address": "+55999111",
            "preferred": False,
        },
    )
    assert result.ok

    contacts = connector.call("list_contacts", {"persona_id": "fred"})
    assert contacts.ok
    channels = {c["channel"] for c in contacts.data}
    assert "email" in channels
    assert "whatsapp" in channels


def test_upsert_contact_sets_preferred_clears_others(connector: ContactsConnector) -> None:
    # fred has email preferred=True; add whatsapp as preferred
    connector.call(
        "upsert_contact",
        {
            "persona_id": "fred",
            "channel": "whatsapp",
            "address": "+55999111",
            "preferred": True,
        },
    )
    contacts = connector.call("list_contacts", {"persona_id": "fred"})
    assert contacts.ok
    preferred = [c for c in contacts.data if c["preferred"]]
    assert len(preferred) == 1
    assert preferred[0]["channel"] == "whatsapp"


def test_upsert_contact_persona_not_found(connector: ContactsConnector) -> None:
    result = connector.call(
        "upsert_contact",
        {
            "persona_id": "nao_existe",
            "channel": "whatsapp",
            "address": "+55000",
        },
    )
    assert not result.ok
    assert "not_found" in result.error


# ---------------------------------------------------------------------------
# merge_personas
# ---------------------------------------------------------------------------


def test_merge_personas_absorbs_duplicate(connector: ContactsConnector) -> None:
    """Base persona absorbs all contacts and aliases from the duplicate."""
    # joao_pt has no contacts; give joao_contador a contact to merge
    connector.call("upsert_contact", {"persona_id": "joao_contador", "channel": "email", "address": "contador@example.com"})

    result = connector.call("merge_personas", {"base_id": "joao_pt", "duplicate_id": "joao_contador"})
    assert result.ok

    # joao_contador persona ID is gone from the registry
    all_p = connector.call("list_personas", {})
    assert all_p.ok
    ids = {p["id"] for p in all_p.data}
    assert "joao_contador" not in ids
    assert "joao_pt" in ids

    # Contact moved to joao_pt
    contacts = connector.call("list_contacts", {"persona_id": "joao_pt"})
    assert contacts.ok
    assert any(c["address"] == "contador@example.com" for c in contacts.data)


def test_merge_personas_merges_aliases(connector: ContactsConnector) -> None:
    result = connector.call("merge_personas", {"base_id": "joao_pt", "duplicate_id": "joao_contador"})
    assert result.ok

    r = connector.call("find_persona", {"name": "João Contador"})
    # After merge, "João Contador" should resolve to joao_pt (alias absorbed)
    assert r.ok
    assert r.data["id"] == "joao_pt"


def test_merge_personas_base_not_found(connector: ContactsConnector) -> None:
    result = connector.call("merge_personas", {"base_id": "nao_existe", "duplicate_id": "ana"})
    assert not result.ok
    assert "not_found" in result.error


def test_merge_personas_duplicate_not_found(connector: ContactsConnector) -> None:
    result = connector.call("merge_personas", {"base_id": "ana", "duplicate_id": "nao_existe"})
    assert not result.ok
    assert "not_found" in result.error


# ---------------------------------------------------------------------------
# set_vip
# ---------------------------------------------------------------------------


def test_set_vip_marks_persona(connector: ContactsConnector) -> None:
    result = connector.call("set_vip", {"persona_id": "ana", "vip": True})
    assert result.ok

    r = connector.call("find_persona", {"name": "ana"})
    assert r.ok
    assert r.data["vip"] is True


def test_set_vip_clears_flag(connector: ContactsConnector) -> None:
    connector.call("set_vip", {"persona_id": "ana", "vip": True})
    connector.call("set_vip", {"persona_id": "ana", "vip": False})

    r = connector.call("find_persona", {"name": "ana"})
    assert r.ok
    assert r.data["vip"] is False


def test_set_vip_not_found(connector: ContactsConnector) -> None:
    result = connector.call("set_vip", {"persona_id": "nao_existe", "vip": True})
    assert not result.ok
    assert "not_found" in result.error


def test_set_vip_persists(tmp_path: Path) -> None:
    """VIP flag survives a reload."""
    personas_path = tmp_path / "personas.yaml"
    contacts_path = tmp_path / "contacts.yaml"
    personas_path.write_text(yaml.dump({"personas": [
        {"id": "viptest", "name": "VIP Test", "type": "person", "owner": "fred",
         "aliases": ["VIP Test"], "context": "", "vip": False}
    ]}))
    contacts_path.write_text(yaml.dump({"contacts": [], "named_channels": []}))

    c1 = ContactsConnector(personas_file=str(personas_path), contacts_file=str(contacts_path))
    c1.call("set_vip", {"persona_id": "viptest", "vip": True})

    c2 = ContactsConnector(personas_file=str(personas_path), contacts_file=str(contacts_path))
    r = c2.call("find_persona", {"name": "VIP Test"})
    assert r.ok
    assert r.data["vip"] is True
