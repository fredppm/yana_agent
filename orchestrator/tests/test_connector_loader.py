"""Tests for the connector folder scanner (loader.py)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from connectors import ConnectorRegistry, load_connectors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_connector(folder: Path, filename: str, class_name: str, extra: str = "") -> Path:
    """Write a minimal connector Python file to *folder*."""
    path = folder / filename
    path.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, r"{Path(__file__).parent.parent.parent / 'orchestrator'}")
        from connectors import Connector, query

        class {class_name}(Connector):
            @query(description="test op", returns={{"type": "number"}})
            def do_thing(self) -> int:
                return 42
        {extra}
    """))
    return path


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_load_single_connector(tmp_path):
    write_connector(tmp_path, "fake_garmin.py", "FakeGarmin")
    registry = ConnectorRegistry()
    registered = load_connectors(tmp_path, registry)
    assert "FakeGarmin" in registered


def test_load_multiple_connectors(tmp_path):
    write_connector(tmp_path, "a_connector.py", "ConnectorA")
    write_connector(tmp_path, "b_connector.py", "ConnectorB")
    registry = ConnectorRegistry()
    registered = load_connectors(tmp_path, registry)
    assert "ConnectorA" in registered
    assert "ConnectorB" in registered


def test_connector_callable_after_load(tmp_path):
    write_connector(tmp_path, "fake.py", "FakeCallable")
    registry = ConnectorRegistry()
    load_connectors(tmp_path, registry)
    registry.register_type(registry._types["FakeCallable"])
    inst = registry._types["FakeCallable"]()
    result = inst.call("do_thing")
    assert result.ok is True
    assert result.data == 42


def test_two_connectors_in_one_file(tmp_path):
    path = tmp_path / "multi.py"
    path.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, r"{Path(__file__).parent.parent.parent / 'orchestrator'}")
        from connectors import Connector, query

        class Alpha(Connector):
            @query(description="alpha", returns={{"type": "string"}})
            def alpha(self) -> str:
                return "a"

        class Beta(Connector):
            @query(description="beta", returns={{"type": "string"}})
            def beta(self) -> str:
                return "b"
    """))
    registry = ConnectorRegistry()
    registered = load_connectors(tmp_path, registry)
    assert "Alpha" in registered
    assert "Beta" in registered


def test_returns_sorted_load_order(tmp_path):
    write_connector(tmp_path, "z_last.py", "ZConnector")
    write_connector(tmp_path, "a_first.py", "AConnector")
    registry = ConnectorRegistry()
    registered = load_connectors(tmp_path, registry)
    assert registered.index("AConnector") < registered.index("ZConnector")


# ---------------------------------------------------------------------------
# File filtering
# ---------------------------------------------------------------------------

def test_skips_dunder_files(tmp_path):
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "__pycache__").mkdir()
    write_connector(tmp_path, "real.py", "RealConnector")
    registry = ConnectorRegistry()
    registered = load_connectors(tmp_path, registry)
    assert registered == ["RealConnector"]


def test_skips_underscore_files(tmp_path):
    (tmp_path / "_private.py").write_text("x = 1")
    write_connector(tmp_path, "public.py", "PublicConnector")
    registry = ConnectorRegistry()
    registered = load_connectors(tmp_path, registry)
    assert registered == ["PublicConnector"]


def test_non_connector_classes_not_registered(tmp_path):
    path = tmp_path / "mixed.py"
    path.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, r"{Path(__file__).parent.parent.parent / 'orchestrator'}")
        from connectors import Connector, query

        class NotAConnector:
            pass

        class RealOne(Connector):
            @query(description="x", returns={{"type": "number"}})
            def x(self) -> int:
                return 1
    """))
    registry = ConnectorRegistry()
    registered = load_connectors(tmp_path, registry)
    assert registered == ["RealOne"]
    assert "NotAConnector" not in registry._types


def test_empty_folder_returns_empty(tmp_path):
    registry = ConnectorRegistry()
    registered = load_connectors(tmp_path, registry)
    assert registered == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_missing_folder_raises(tmp_path):
    registry = ConnectorRegistry()
    with pytest.raises(FileNotFoundError):
        load_connectors(tmp_path / "nonexistent", registry)


def test_import_error_raises_runtime_error(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("raise ImportError('intentional failure')")
    registry = ConnectorRegistry()
    with pytest.raises(RuntimeError, match="bad.py"):
        load_connectors(tmp_path, registry)


# ---------------------------------------------------------------------------
# Integration: load_connectors + load_manifest + call
# ---------------------------------------------------------------------------

def test_full_flow_scan_manifest_call(tmp_path):
    """Scan folder → load manifest → call without manual register_type."""
    write_connector(tmp_path, "sensor.py", "SensorConnector")

    import tempfile, os
    manifest_yaml = f"""
connectors:
  - type: SensorConnector
    id: sensor_1
    name: "Sensor 1"
    description: "A test sensor"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(manifest_yaml)
        manifest_path = Path(f.name)

    try:
        registry = ConnectorRegistry()
        load_connectors(tmp_path, registry)
        registry.load_manifest(manifest_path)

        result = registry.call("sensor_1", "do_thing")
        assert result.ok is True
        assert result.data == 42
    finally:
        os.unlink(manifest_path)
