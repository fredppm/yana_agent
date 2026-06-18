"""
tests/test_google_contacts_sync.py — Story-driven tests for the Google Contacts sync.

Each test tells a scenario in plain language so the behaviour can be validated
by reading the test names and structure — no Google API calls, no network.

Scenarios covered:

  1. First sync — new persona and contacts are created with source tracking
  2. Second sync — YANA name is NOT overwritten (YANA is source of truth)
  3. Second sync — new email added in Google is picked up
  4. YANA enrichment (alias, context) survives sync untouched
  5. Person renamed in Google — YANA keeps original name
  6. New person added in Google after first sync — appears on next sync
  7. Contact with accented/special characters (UTF-8)
  8. Two people with same first name — both created with distinct IDs
  9. find_by_source correctly locates persona by Google resource name
 10. Running sync twice is idempotent — no duplicates
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Make connectors/ importable
_CONNECTORS_DIR = Path(__file__).parent.parent.parent / "connectors"
if str(_CONNECTORS_DIR) not in sys.path:
    sys.path.insert(0, str(_CONNECTORS_DIR))

from google_contacts import GoogleContactsConnector  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connector(tmp_path: Path) -> GoogleContactsConnector:
    """Return a GoogleContactsConnector wired to empty tmp YAML files."""
    personas_path = tmp_path / "personas.yaml"
    contacts_path = tmp_path / "contacts.yaml"
    personas_path.write_text(yaml.dump({"personas": []}), encoding="utf-8")
    contacts_path.write_text(
        yaml.dump({"contacts": [], "named_channels": []}), encoding="utf-8"
    )
    return GoogleContactsConnector(
        app_credential=str(tmp_path / "fake_cred.json"),
        persona_token=str(tmp_path / "fake_token.json"),
        personas_file=str(personas_path),
        contacts_file=str(contacts_path),
    )


def _google_person(
    name: str,
    resource: str,
    emails: list[str] | None = None,
    phones: list[str] | None = None,
) -> dict:
    """Build a raw entry as returned by list_contacts()."""
    return {
        "name": name,
        "source_id": resource,
        "emails": emails or [],
        "phones": phones or [],
    }


def _sync(connector: GoogleContactsConnector, people: list[dict]) -> dict:
    """Run sync_contacts with a mocked _fetch_contacts (no network, no parse errors)."""
    with patch.object(connector, "_fetch_contacts", return_value=(people, [])):
        return connector.sync_contacts(owner="fred")


# ---------------------------------------------------------------------------
# Scenario 1 — First sync creates persona and contacts with source tracking
# ---------------------------------------------------------------------------


def test_first_sync_creates_persona(tmp_path: Path) -> None:
    """
    Fred runs sync for the first time.
    Ana is in Google Contacts with an email and a phone.
    After sync, YANA has Ana as a Persona.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [
        _google_person("Ana", "people/c001", emails=["ana@example.com"], phones=["+55999"])
    ])

    p = connector._registry.find_persona("Ana")
    assert p is not None
    assert p.name == "Ana"


def test_first_sync_stores_google_source_id(tmp_path: Path) -> None:
    """
    After first sync, the persona has a source entry pointing back to Google.
    This allows future syncs to find the same person reliably.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [
        _google_person("Ana", "people/c001", emails=["ana@example.com"])
    ])

    p = connector._registry.find_by_source("google", "people/c001")
    assert p is not None
    assert p.id == "ana"


def test_first_sync_creates_email_contact(tmp_path: Path) -> None:
    """
    Ana's email from Google becomes a Contact entry in YANA with google source tracking.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [
        _google_person("Ana", "people/c001", emails=["ana@example.com"])
    ])

    c = connector._registry.get_contact("ana", channel="email")
    assert c is not None
    assert c.address == "ana@example.com"
    assert any(s.get("provider") == "google" for s in c.sources)


def test_first_sync_creates_phone_contact(tmp_path: Path) -> None:
    """
    Ana's phone from Google is stored as channel='phone' (raw, delivery unknown).
    Google doesn't tell us if it's WhatsApp or SMS — that must be confirmed separately.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [
        _google_person("Ana", "people/c001", phones=["+55999111222"])
    ])

    c = connector._registry.get_contact("ana", channel="phone")
    assert c is not None
    assert c.address == "+55999111222"
    assert c.channel == "phone"  # not routable until promoted via upsert_contact
    assert any(s.get("provider") == "google" for s in c.sources)


def test_first_sync_returns_counts(tmp_path: Path) -> None:
    """
    sync_contacts reports how many personas and contacts were added.
    """
    connector = _make_connector(tmp_path)
    result = _sync(connector, [
        _google_person("Ana", "people/c001", emails=["ana@example.com"], phones=["+55999"]),
        _google_person("João", "people/c002", emails=["joao@example.com"]),
    ])

    assert result["added_personas"] == 2
    assert result["added_contacts"] == 3  # ana email + ana phone + joao email
    assert result["updated_personas"] == 0


# ---------------------------------------------------------------------------
# Scenario 2 — Second sync does NOT overwrite YANA's name
# ---------------------------------------------------------------------------


def test_second_sync_does_not_overwrite_yana_name(tmp_path: Path) -> None:
    """
    Fred taught YANA to call Ana "esposa" internally.
    Fred then renames Ana to "Ana Beatriz" in Google Contacts.
    On the next sync, YANA keeps "Ana" — YANA is the source of truth for names.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [_google_person("Ana", "people/c001", emails=["ana@example.com"])])

    # Fred later renames in Google — but YANA must not follow
    _sync(connector, [_google_person("Ana Beatriz", "people/c001", emails=["ana@example.com"])])

    p = connector._registry.find_by_source("google", "people/c001")
    assert p is not None
    assert p.name == "Ana"  # unchanged


# ---------------------------------------------------------------------------
# Scenario 3 — Second sync adds new email added in Google
# ---------------------------------------------------------------------------


def test_second_sync_adds_new_email(tmp_path: Path) -> None:
    """
    Ana had only a phone in the first sync.
    Fred later adds her work email in Google.
    On the next sync, YANA adds the new email contact — without duplicating the phone.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [_google_person("Ana", "people/c001", phones=["+55999"])])
    _sync(connector, [_google_person("Ana", "people/c001", phones=["+55999"], emails=["ana@work.com"])])

    contacts = [c for c in connector._registry._contacts if c.persona_id == "ana"]
    channels = {c.channel for c in contacts}
    assert "phone" in channels  # raw phone — channel unknown from Google
    assert "email" in channels
    assert len(contacts) == 2  # no duplicates


# ---------------------------------------------------------------------------
# Scenario 4 — YANA enrichment survives sync
# ---------------------------------------------------------------------------


def test_yana_aliases_survive_sync(tmp_path: Path) -> None:
    """
    After the first sync, YANA learns that Ana is also known as "esposa".
    On the next sync from Google, that alias is untouched.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [_google_person("Ana", "people/c001", emails=["ana@example.com"])])

    # YANA learns an alias via conversation
    connector._registry._personas["ana"].aliases.append("esposa")
    connector._registry.save()

    # Next sync
    _sync(connector, [_google_person("Ana", "people/c001", emails=["ana@example.com"])])

    p = connector._registry.find_persona("esposa")
    assert p is not None
    assert p.id == "ana"


def test_yana_context_survives_sync(tmp_path: Path) -> None:
    """
    YANA records that Ana is "esposa do Fred".
    Sync must not erase that context.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [_google_person("Ana", "people/c001", emails=["ana@example.com"])])

    connector._registry._personas["ana"].context = "esposa do Fred"
    connector._registry.save()

    _sync(connector, [_google_person("Ana", "people/c001", emails=["ana@example.com"])])

    p = connector._registry._personas["ana"]
    assert p.context == "esposa do Fred"


# ---------------------------------------------------------------------------
# Scenario 5 — New person added in Google appears on next sync
# ---------------------------------------------------------------------------


def test_new_person_in_google_appears_after_sync(tmp_path: Path) -> None:
    """
    Fred adds his accountant to Google Contacts after the first sync.
    On the next sync, the accountant appears in YANA.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [_google_person("Ana", "people/c001", emails=["ana@example.com"])])

    assert connector._registry.find_persona("contador") is None

    _sync(connector, [
        _google_person("Ana", "people/c001", emails=["ana@example.com"]),
        _google_person("Dr. Ribeiro", "people/c099", emails=["ribeiro@contabil.com"]),
    ])

    p = connector._registry.find_persona("Dr. Ribeiro")
    assert p is not None


# ---------------------------------------------------------------------------
# Scenario 6 — UTF-8 / accented characters
# ---------------------------------------------------------------------------


def test_accented_names_are_handled(tmp_path: Path) -> None:
    """
    João has an accent. YANA must handle this without crashing or corrupting the YAML.
    After sync, João is findable and the YAML is valid UTF-8.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [_google_person("João Silva", "people/c003", emails=["joao@example.com"])])

    p = connector._registry.find_persona("João Silva")
    assert p is not None

    # Re-load from disk — round-trip must be clean
    personas_path = connector._registry._personas_path
    content = personas_path.read_text(encoding="utf-8")
    reloaded = yaml.safe_load(content)
    names = [e["name"] for e in reloaded["personas"]]
    assert "João Silva" in names


# ---------------------------------------------------------------------------
# Scenario 7 — Two people with the same first name get distinct IDs
# ---------------------------------------------------------------------------


def test_two_joaos_get_distinct_ids(tmp_path: Path) -> None:
    """
    Fred has two contacts named João — his PT and his accountant.
    Both should be created with distinct persona IDs so neither shadows the other.
    """
    connector = _make_connector(tmp_path)
    result = _sync(connector, [
        _google_person("João Personal Trainer", "people/c010", phones=["+55911"]),
        _google_person("João Contador", "people/c011", emails=["joao.cont@example.com"]),
    ])

    assert result["added_personas"] == 2
    ids = list(connector._registry._personas.keys())
    assert len(ids) == 2
    assert ids[0] != ids[1]


# ---------------------------------------------------------------------------
# Scenario 8 — find_by_source
# ---------------------------------------------------------------------------


def test_find_by_source_returns_correct_persona(tmp_path: Path) -> None:
    """
    After sync, YANA can reverse-lookup a persona by its Google resource name.
    This is how future syncs find the right persona even if the name changed.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [
        _google_person("Ana", "people/c001"),
        _google_person("João", "people/c002"),
    ])

    p = connector._registry.find_by_source("google", "people/c002")
    assert p is not None
    assert p.name == "João"


def test_find_by_source_returns_none_for_unknown(tmp_path: Path) -> None:
    connector = _make_connector(tmp_path)
    _sync(connector, [_google_person("Ana", "people/c001")])

    assert connector._registry.find_by_source("google", "people/c999") is None
    assert connector._registry.find_by_source("apple", "people/c001") is None


# ---------------------------------------------------------------------------
# Scenario 9 — Idempotency: running sync twice produces no duplicates
# ---------------------------------------------------------------------------


def test_sync_twice_produces_no_duplicate_personas(tmp_path: Path) -> None:
    """
    Running sync_contacts twice with the same Google data must not create duplicates.
    """
    connector = _make_connector(tmp_path)
    people = [_google_person("Ana", "people/c001", emails=["ana@example.com"])]
    _sync(connector, people)
    _sync(connector, people)

    personas = list(connector._registry._personas.values())
    assert len(personas) == 1


def test_sync_twice_produces_no_duplicate_contacts(tmp_path: Path) -> None:
    """
    Running sync_contacts twice must not duplicate Contact entries.
    """
    connector = _make_connector(tmp_path)
    people = [_google_person("Ana", "people/c001", emails=["ana@example.com"], phones=["+55999"])]
    _sync(connector, people)
    _sync(connector, people)

    contacts = [c for c in connector._registry._contacts if c.persona_id == "ana"]
    assert len(contacts) == 2  # one email, one phone (raw) — not 4


def test_second_sync_reports_updated_not_added(tmp_path: Path) -> None:
    """
    On the second sync with unchanged data, added_personas is 0
    and updated_personas reflects the existing ones seen.
    """
    connector = _make_connector(tmp_path)
    people = [_google_person("Ana", "people/c001", emails=["ana@example.com"])]
    _sync(connector, people)
    result = _sync(connector, people)

    assert result["added_personas"] == 0
    assert result["updated_personas"] == 1


# ---------------------------------------------------------------------------
# Scenario 10 — Sending a message to João: only email synced
# ---------------------------------------------------------------------------


def test_joao_with_only_email_get_contact_returns_email(tmp_path: Path) -> None:
    """
    João was synced with only an email address.
    When YANA tries to reach João without specifying a channel,
    it returns the email — the only option available.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [_google_person("João", "people/c010", emails=["joao@example.com"])])

    c = connector._registry.get_contact("jo_o", channel=None)
    assert c is not None
    assert c.channel == "email"


def test_joao_with_only_phone_get_contact_returns_phone(tmp_path: Path) -> None:
    """
    João was synced with only a phone number.
    Google doesn't tell us the channel — stored as channel='phone' (raw).
    YANA must then ask Fred: "WhatsApp or SMS?" before routing a message.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [_google_person("João", "people/c010", phones=["+55911222333"])])

    persona_id = list(connector._registry._personas.keys())[0]
    c = connector._registry.get_contact(persona_id, channel=None)
    assert c is not None
    assert c.channel == "phone"  # not routable yet — delivery method unknown


# ---------------------------------------------------------------------------
# Scenario 11 — João has both email and WhatsApp — no preferred set yet
# ---------------------------------------------------------------------------


def test_joao_with_email_and_phone_no_preferred_returns_first(tmp_path: Path) -> None:
    """
    João has email and WhatsApp from Google sync, but no preferred channel set.
    get_contact without a channel returns the first one (email, added first).
    YANA should then ask Fred which he prefers.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [
        _google_person("João", "people/c010",
                       emails=["joao@example.com"], phones=["+55911222333"])
    ])

    persona_id = list(connector._registry._personas.keys())[0]
    contacts = [c for c in connector._registry._contacts if c.persona_id == persona_id]

    # None are preferred yet
    assert not any(c.preferred for c in contacts)

    # get_contact falls back to first
    c = connector._registry.get_contact(persona_id)
    assert c is not None


# ---------------------------------------------------------------------------
# Scenario 12 — Configuring the preferred contact method via ContactsConnector
# ---------------------------------------------------------------------------


def test_set_preferred_contact_makes_whatsapp_default(tmp_path: Path) -> None:
    """
    João synced with email and phone (raw). Fred tells YANA: "João usa WhatsApp".
    YANA calls upsert_contact to promote the phone to a whatsapp entry, then
    set_preferred_contact makes it the default.
    """
    from contacts_connector import ContactsConnector

    personas_path = tmp_path / "personas.yaml"
    contacts_path = tmp_path / "contacts.yaml"
    personas_path.write_text(yaml.dump({"personas": []}), encoding="utf-8")
    contacts_path.write_text(yaml.dump({"contacts": [], "named_channels": []}), encoding="utf-8")

    gc = GoogleContactsConnector(
        app_credential=str(tmp_path / "fake_cred.json"),
        persona_token=str(tmp_path / "fake_token.json"),
        personas_file=str(personas_path),
        contacts_file=str(contacts_path),
    )
    _sync(gc, [
        _google_person("João", "people/c010",
                       emails=["joao@example.com"], phones=["+55911222333"])
    ])

    persona_id = list(gc._registry._personas.keys())[0]

    # YANA learns João is on WhatsApp: upsert_contact promotes the raw phone to whatsapp
    cc = ContactsConnector(personas_file=str(personas_path), contacts_file=str(contacts_path))
    r = cc.call("upsert_contact", {
        "persona_id": persona_id,
        "channel": "whatsapp",
        "address": "+55911222333",
        "preferred": False,
    })
    assert r.ok

    # Now set whatsapp as preferred
    result = cc.call("set_preferred_contact", {"persona_id": persona_id, "channel": "whatsapp"})
    assert result.ok

    # Reload and verify
    cc2 = ContactsConnector(personas_file=str(personas_path), contacts_file=str(contacts_path))
    c = cc2._registry.get_contact(persona_id)
    assert c is not None
    assert c.channel == "whatsapp"


def test_set_preferred_contact_unknown_channel_returns_error(tmp_path: Path) -> None:
    """
    Fred asks to set Telegram as João's preferred channel, but João has no Telegram.
    The operation must return an error — not silently fail.
    """
    from contacts_connector import ContactsConnector

    personas_path = tmp_path / "personas.yaml"
    contacts_path = tmp_path / "contacts.yaml"
    personas_path.write_text(yaml.dump({"personas": []}), encoding="utf-8")
    contacts_path.write_text(yaml.dump({"contacts": [], "named_channels": []}), encoding="utf-8")

    gc = GoogleContactsConnector(
        app_credential=str(tmp_path / "fake_cred.json"),
        persona_token=str(tmp_path / "fake_token.json"),
        personas_file=str(personas_path),
        contacts_file=str(contacts_path),
    )
    _sync(gc, [_google_person("João", "people/c010", emails=["joao@example.com"])])
    persona_id = list(gc._registry._personas.keys())[0]

    cc = ContactsConnector(
        personas_file=str(personas_path),
        contacts_file=str(contacts_path),
    )
    result = cc.call("set_preferred_contact", {"persona_id": persona_id, "channel": "telegram"})
    assert not result.ok
    assert "no_channel" in result.error


def test_set_preferred_contact_persists_to_yaml(tmp_path: Path) -> None:
    """
    After set_preferred_contact, a fresh connector loaded from the same files
    returns the correct preferred channel — preference was persisted.
    """
    from contacts_connector import ContactsConnector

    personas_path = tmp_path / "personas.yaml"
    contacts_path = tmp_path / "contacts.yaml"
    personas_path.write_text(yaml.dump({"personas": []}), encoding="utf-8")
    contacts_path.write_text(yaml.dump({"contacts": [], "named_channels": []}), encoding="utf-8")

    gc = GoogleContactsConnector(
        app_credential=str(tmp_path / "fake_cred.json"),
        persona_token=str(tmp_path / "fake_token.json"),
        personas_file=str(personas_path),
        contacts_file=str(contacts_path),
    )
    _sync(gc, [
        _google_person("João", "people/c010",
                       emails=["joao@example.com"], phones=["+55911222333"])
    ])
    persona_id = list(gc._registry._personas.keys())[0]

    # Promote raw phone to whatsapp first
    cc = ContactsConnector(personas_file=str(personas_path), contacts_file=str(contacts_path))
    cc.call("upsert_contact", {
        "persona_id": persona_id,
        "channel": "whatsapp",
        "address": "+55911222333",
        "preferred": False,
    })
    cc.call("set_preferred_contact", {"persona_id": persona_id, "channel": "whatsapp"})

    # Fresh load
    cc2 = ContactsConnector(personas_file=str(personas_path), contacts_file=str(contacts_path))
    c = cc2._registry.get_contact(persona_id)
    assert c.channel == "whatsapp"


# ---------------------------------------------------------------------------
# Scenario 13 — purge_removed removes phantoms whose source_id left Google
# ---------------------------------------------------------------------------


def _sync_purge(connector: GoogleContactsConnector, people: list[dict]) -> dict:
    """Run sync_contacts with purge_removed=True and force_update_names=True."""
    with patch.object(connector, "_fetch_contacts", return_value=(people, [])):
        return connector.sync_contacts(
            owner="fred",
            force_update_names=True,
            purge_removed=True,
        )


def test_purge_removed_deletes_orphaned_google_persona(tmp_path: Path) -> None:
    """
    A phantom persona was created in a bad sync with a source_id that no longer
    exists in Google. Running sync with purge_removed=True removes it.
    """
    connector = _make_connector(tmp_path)
    # First sync: Ana created with source_id people/c001
    _sync(connector, [_google_person("Ana", "people/c001", emails=["ana@example.com"])])
    assert connector._registry.find_persona("Ana") is not None

    # Second sync: Ana is gone from Google — purge_removed should remove her
    result = _sync_purge(connector, [])
    assert result["purged_personas"] == 1
    assert "purged_names" in result
    assert connector._registry.find_persona("Ana") is None


def test_purge_removed_also_removes_contacts(tmp_path: Path) -> None:
    """
    Purging an orphaned persona also removes its contacts.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [
        _google_person("Ana", "people/c001", emails=["ana@example.com"], phones=["+55999"])
    ])
    contacts_before = len(connector._registry._contacts)
    assert contacts_before == 2  # email + phone (raw)

    _sync_purge(connector, [])

    assert len(connector._registry._contacts) == 0


def test_purge_removed_keeps_personas_with_non_google_sources(tmp_path: Path) -> None:
    """
    A persona that has a Google source AND another source (e.g. manually added)
    is NOT purged even if its Google source_id is no longer in the fetch.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [_google_person("Ana", "people/c001", emails=["ana@example.com"])])

    # Manually add a non-Google source to Ana
    ana = connector._registry.find_persona("Ana")
    assert ana is not None
    ana.sources.append({"provider": "manual", "source_id": "local"})
    connector._registry.save()

    # Sync with Ana removed from Google — she should NOT be purged
    result = _sync_purge(connector, [])
    assert result["purged_personas"] == 0
    assert connector._registry.find_persona("Ana") is not None


def test_purge_removed_false_keeps_orphans(tmp_path: Path) -> None:
    """
    By default (purge_removed=False), orphaned Google personas are left alone.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [_google_person("Ana", "people/c001", emails=["ana@example.com"])])

    # Sync with Ana gone from Google — but purge_removed defaults to False
    result = _sync(connector, [])
    assert result.get("purged_personas", 0) == 0
    assert connector._registry.find_persona("Ana") is not None


def test_purge_removed_result_includes_purged_count(tmp_path: Path) -> None:
    """
    purge_removed always adds purged_personas to the result dict, even if 0.
    """
    connector = _make_connector(tmp_path)
    _sync(connector, [_google_person("Ana", "people/c001", emails=["ana@example.com"])])

    # Re-sync with Ana still present — nothing purged
    result = _sync_purge(connector, [
        _google_person("Ana", "people/c001", emails=["ana@example.com"])
    ])
    assert result["purged_personas"] == 0
    assert "purged_names" not in result
