"""Tests for ConnectorInstance + ConnectorRegistry."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from connectors import Connector, ConnectorInstance, ConnectorRegistry, command, query

# ---------------------------------------------------------------------------
# Minimal test connector
# ---------------------------------------------------------------------------


class FakeGarmin(Connector):
    @query(description="Steps today", returns={"type": "number", "unit": "steps/day"})
    def steps_today(self) -> int:
        return 9999

    @command(description="Sync device", returns={"type": "boolean"})
    def sync(self) -> bool:
        return True


class FakeCalendar(Connector):
    @query(description="Events today", returns={"type": "list"})
    def events_today(self) -> list:
        return []


# ---------------------------------------------------------------------------
# Fixture: registry loaded from the real connectors.yaml
# ---------------------------------------------------------------------------

MANIFEST = Path(__file__).parent.parent / "config" / "connectors.yaml"


@pytest.fixture
def registry() -> ConnectorRegistry:
    r = ConnectorRegistry()
    r.register_type(FakeGarmin)
    r.register_type(FakeCalendar)
    return r


@pytest.fixture
def loaded_registry(registry: ConnectorRegistry) -> ConnectorRegistry:
    # Patch manifest type names to match test connector class names

    manifest_yaml = """
connectors:
  - type: FakeGarmin
    id: garmin_fred
    name: "Garmin do Fred"
    description: "Dados de saúde do Fred"
    owner: fred
  - type: FakeGarmin
    id: garmin_ana
    name: "Garmin da Ana"
    description: "Dados de saúde da Ana"
    owner: ana
  - type: FakeCalendar
    id: calendar_fred
    name: "Agenda do Fred"
    description: "Calendário pessoal do Fred"
    owner: fred
  - type: FakeCalendar
    id: rgb_sala
    name: "Luz da Sala"
    description: "Luz da sala de estar"
"""
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(manifest_yaml)
        tmp = f.name
    try:
        registry.load_manifest(Path(tmp))
    finally:
        os.unlink(tmp)
    return registry


# ---------------------------------------------------------------------------
# ConnectorInstance
# ---------------------------------------------------------------------------


def test_instance_fields():
    inst = ConnectorInstance(
        id="garmin_fred",
        name="Garmin do Fred",
        description="Dados de saúde do Fred",
        type="FakeGarmin",
        owner="fred",
    )
    assert inst.id == "garmin_fred"
    assert inst.owner == "fred"


def test_instance_owner_optional():
    inst = ConnectorInstance(
        id="rgb_sala",
        name="Luz da Sala",
        description="Luz RGB",
        type="FakeLight",
    )
    assert inst.owner is None


# ---------------------------------------------------------------------------
# Registry — load_manifest
# ---------------------------------------------------------------------------


def test_load_manifest_populates_instances(loaded_registry):
    inst = loaded_registry.get_instance("garmin_fred")
    assert inst.name == "Garmin do Fred"
    assert inst.owner == "fred"
    assert inst.type == "FakeGarmin"


def test_load_manifest_generic_connector_no_owner(loaded_registry):
    inst = loaded_registry.get_instance("rgb_sala")
    assert inst.owner is None


def test_load_manifest_multiple_instances_same_type(loaded_registry):
    fred = loaded_registry.get_instance("garmin_fred")
    ana = loaded_registry.get_instance("garmin_ana")
    assert fred.type == ana.type == "FakeGarmin"
    assert fred.owner == "fred"
    assert ana.owner == "ana"


def test_get_instance_unknown_raises(loaded_registry):
    with pytest.raises(KeyError):
        loaded_registry.get_instance("nonexistent")


# ---------------------------------------------------------------------------
# Registry — lightweight_manifest (Level 1)
# ---------------------------------------------------------------------------


def test_lightweight_manifest_contains_all_instances(loaded_registry):
    manifest = loaded_registry.lightweight_manifest()
    ids = {e["id"] for e in manifest}
    assert {"garmin_fred", "garmin_ana", "calendar_fred", "rgb_sala"} == ids


def test_lightweight_manifest_includes_owner_when_set(loaded_registry):
    manifest = loaded_registry.lightweight_manifest()
    fred = next(e for e in manifest if e["id"] == "garmin_fred")
    assert fred["owner"] == "fred"


def test_lightweight_manifest_no_owner_key_when_absent(loaded_registry):
    manifest = loaded_registry.lightweight_manifest()
    sala = next(e for e in manifest if e["id"] == "rgb_sala")
    assert "owner" not in sala


def test_lightweight_manifest_has_no_contract_details(loaded_registry):
    manifest = loaded_registry.lightweight_manifest()
    for entry in manifest:
        assert "queries" not in entry
        assert "commands" not in entry
        assert "events" not in entry


# ---------------------------------------------------------------------------
# Registry — load_contract (Level 2)
# ---------------------------------------------------------------------------


def test_load_contract_returns_full_schema(loaded_registry):
    contract = loaded_registry.load_contract("garmin_fred")
    assert contract["type"] == "FakeGarmin"
    assert any(q["name"] == "steps_today" for q in contract["queries"])


def test_load_contract_includes_instance_metadata(loaded_registry):
    contract = loaded_registry.load_contract("garmin_fred")
    assert contract["instance_id"] == "garmin_fred"
    assert contract["name"] == "Garmin do Fred"
    assert contract["owner"] == "fred"


def test_load_contract_generic_has_no_owner_key(loaded_registry):
    contract = loaded_registry.load_contract("rgb_sala")
    assert "owner" not in contract


# ---------------------------------------------------------------------------
# Registry — call (routes through instance → connector)
# ---------------------------------------------------------------------------


def test_call_routes_to_correct_instance(loaded_registry):
    result = loaded_registry.call("garmin_fred", "steps_today")
    assert result.ok is True
    assert result.data == 9999


def test_call_unknown_instance(loaded_registry):
    result = loaded_registry.call("nonexistent", "steps_today")
    assert result.ok is False
    assert result.error == "unavailable"


def test_call_two_instances_same_type_are_independent(loaded_registry):
    r1 = loaded_registry.call("garmin_fred", "steps_today")
    r2 = loaded_registry.call("garmin_ana", "steps_today")
    assert r1.ok is True
    assert r2.ok is True


def test_call_missing_implementation_raises(registry):
    import os
    import tempfile

    manifest_yaml = """
connectors:
  - type: UnknownType
    id: ghost
    name: Ghost
    description: Not registered
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(manifest_yaml)
        tmp = f.name
    try:
        registry.load_manifest(Path(tmp))
    finally:
        os.unlink(tmp)

    result = registry.call("ghost", "anything")
    assert result.ok is False
    assert result.error == "auth"
