"""Tests for P5 DX: class-level description, add_instance(), YAML fallback."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from connectors import Connector, ConnectorRegistry, command, query

# ---------------------------------------------------------------------------
# Test connectors
# ---------------------------------------------------------------------------

class SensorConnector(Connector):
    connector_description = "Generic sensor — reads temperature and humidity"

    @query(description="Current temperature", returns={"type": "number", "unit": "celsius"})
    def temperature(self) -> float:
        return 21.0

    @command(description="Reset sensor", returns={"type": "boolean"})
    def reset(self) -> bool:
        return True


class NoDescriptionConnector(Connector):
    # no connector_description set

    @query(description="Ping", returns={"type": "boolean"})
    def ping(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# connector_description class attribute
# ---------------------------------------------------------------------------

def test_class_description_accessible():
    assert SensorConnector.connector_description == "Generic sensor — reads temperature and humidity"


def test_default_connector_description_is_empty_string():
    assert NoDescriptionConnector.connector_description == ""


def test_base_connector_description_is_empty():
    assert Connector.connector_description == ""


# ---------------------------------------------------------------------------
# add_instance() — programmatic registration
# ---------------------------------------------------------------------------

def test_add_instance_registers_type_and_instance():
    registry = ConnectorRegistry()
    inst = registry.add_instance(SensorConnector, "sensor_1", "Sensor da Sala")
    assert inst.id == "sensor_1"
    assert inst.name == "Sensor da Sala"
    assert "SensorConnector" in registry._types
    assert "sensor_1" in registry._instances


def test_add_instance_uses_class_description_as_default():
    registry = ConnectorRegistry()
    inst = registry.add_instance(SensorConnector, "sensor_1", "Sensor da Sala")
    assert inst.description == SensorConnector.connector_description


def test_add_instance_explicit_description_overrides_class():
    registry = ConnectorRegistry()
    inst = registry.add_instance(
        SensorConnector, "sensor_1", "Sensor da Sala",
        description="Custom description for this instance"
    )
    assert inst.description == "Custom description for this instance"


def test_add_instance_with_owner():
    registry = ConnectorRegistry()
    inst = registry.add_instance(SensorConnector, "sensor_fred", "Sensor do Fred", owner="fred")
    assert inst.owner == "fred"


def test_add_instance_without_owner():
    registry = ConnectorRegistry()
    inst = registry.add_instance(SensorConnector, "sensor_1", "Sensor da Sala")
    assert inst.owner is None


def test_add_instance_callable_immediately():
    registry = ConnectorRegistry()
    registry.add_instance(SensorConnector, "sensor_1", "Sensor da Sala")
    result = registry.call("sensor_1", "temperature")
    assert result.ok is True
    assert result.data == 21.0


def test_add_instance_appears_in_lightweight_manifest():
    registry = ConnectorRegistry()
    registry.add_instance(SensorConnector, "sensor_1", "Sensor da Sala")
    registry.add_instance(SensorConnector, "sensor_2", "Sensor do Quarto", owner="ana")
    manifest = registry.lightweight_manifest()
    ids = {e["id"] for e in manifest}
    assert {"sensor_1", "sensor_2"} == ids


def test_add_instance_no_description_falls_back_to_empty():
    registry = ConnectorRegistry()
    inst = registry.add_instance(NoDescriptionConnector, "no_desc", "No Desc")
    assert inst.description == ""


# ---------------------------------------------------------------------------
# YAML load_manifest — description fallback from class
# ---------------------------------------------------------------------------

def _write_manifest(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    f.write(content)
    f.close()
    return Path(f.name)


def test_yaml_without_description_falls_back_to_class(tmp_path):
    registry = ConnectorRegistry()
    registry.register_type(SensorConnector)

    manifest_path = _write_manifest("""
connectors:
  - type: SensorConnector
    id: sensor_1
    name: "Sensor da Sala"
""")
    try:
        registry.load_manifest(manifest_path)
    finally:
        os.unlink(manifest_path)

    inst = registry.get_instance("sensor_1")
    assert inst.description == SensorConnector.connector_description


def test_yaml_explicit_description_overrides_class(tmp_path):
    registry = ConnectorRegistry()
    registry.register_type(SensorConnector)

    manifest_path = _write_manifest("""
connectors:
  - type: SensorConnector
    id: sensor_1
    name: "Sensor da Sala"
    description: "Overridden in YAML"
""")
    try:
        registry.load_manifest(manifest_path)
    finally:
        os.unlink(manifest_path)

    inst = registry.get_instance("sensor_1")
    assert inst.description == "Overridden in YAML"


def test_yaml_unregistered_type_has_empty_fallback():
    registry = ConnectorRegistry()
    # type not registered before load_manifest

    manifest_path = _write_manifest("""
connectors:
  - type: SensorConnector
    id: sensor_1
    name: "Sensor da Sala"
""")
    try:
        registry.load_manifest(manifest_path)
    finally:
        os.unlink(manifest_path)

    inst = registry.get_instance("sensor_1")
    assert inst.description == ""


# ---------------------------------------------------------------------------
# Full no-YAML flow: scan folder + add_instance
# ---------------------------------------------------------------------------

def test_full_no_yaml_flow():
    """Developer writes connector class, registers instance — zero YAML."""
    registry = ConnectorRegistry()
    registry.add_instance(SensorConnector, "sensor_office", "Sensor do Escritório")

    manifest = registry.lightweight_manifest()
    assert len(manifest) == 1
    assert manifest[0]["id"] == "sensor_office"
    assert manifest[0]["description"] == SensorConnector.connector_description

    contract = registry.load_contract("sensor_office")
    assert any(q["name"] == "temperature" for q in contract["queries"])

    result = registry.call("sensor_office", "temperature")
    assert result.ok is True
