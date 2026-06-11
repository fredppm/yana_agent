"""Tests for the event mechanism (subscribe / activate_events / polling_candidates)."""

from __future__ import annotations

import sys
import tempfile
import os
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from connectors import (
    Connector,
    ConnectorRegistry,
    command,
    event,
    query,
)


# ---------------------------------------------------------------------------
# Test connectors
# ---------------------------------------------------------------------------

class PushConnector(Connector):
    """Has events — push-capable."""

    _callbacks: dict[str, Any] = {}  # event_name → callback

    @query(description="Get value", returns={"type": "number"})
    def get_value(self) -> int:
        return 1

    @event(description="Fires when value changes", schema={"type": "object"})
    def on_value_changed(self, callback) -> None:
        PushConnector._callbacks["on_value_changed"] = callback

    @event(description="Fires on alert", schema={"type": "string"})
    def on_alert(self, callback) -> None:
        PushConnector._callbacks["on_alert"] = callback


class PollConnector(Connector):
    """No events — poll-only."""

    @query(description="Get temperature", returns={"type": "number", "unit": "celsius"})
    def get_temperature(self) -> float:
        return 22.5

    @query(description="Get humidity", returns={"type": "number", "unit": "percent"})
    def get_humidity(self) -> float:
        return 60.0


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def make_registry(*connector_types) -> ConnectorRegistry:
    r = ConnectorRegistry()
    for cls in connector_types:
        r.register_type(cls)
    return r


def load_yaml_manifest(registry: ConnectorRegistry, yaml_str: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_str)
        tmp = f.name
    try:
        registry.load_manifest(Path(tmp))
    finally:
        os.unlink(tmp)


# ---------------------------------------------------------------------------
# subscribe
# ---------------------------------------------------------------------------

def test_subscribe_registers_handler():
    registry = make_registry(PushConnector)
    load_yaml_manifest(registry, """
connectors:
  - type: PushConnector
    id: push_1
    name: Push 1
    description: test
""")
    received = []
    registry.subscribe("push_1", "on_value_changed", received.append)
    assert len(registry._handlers[("push_1", "on_value_changed")]) == 1


def test_subscribe_multiple_handlers_same_event():
    registry = make_registry(PushConnector)
    load_yaml_manifest(registry, """
connectors:
  - type: PushConnector
    id: push_1
    name: Push 1
    description: test
""")
    a, b = [], []
    registry.subscribe("push_1", "on_value_changed", a.append)
    registry.subscribe("push_1", "on_value_changed", b.append)
    assert len(registry._handlers[("push_1", "on_value_changed")]) == 2


# ---------------------------------------------------------------------------
# activate_events
# ---------------------------------------------------------------------------

def test_activate_events_returns_event_names():
    registry = make_registry(PushConnector)
    load_yaml_manifest(registry, """
connectors:
  - type: PushConnector
    id: push_1
    name: Push 1
    description: test
""")
    activated = registry.activate_events("push_1")
    assert "on_value_changed" in activated
    assert "on_alert" in activated


def test_activate_events_only_events_not_queries():
    registry = make_registry(PushConnector)
    load_yaml_manifest(registry, """
connectors:
  - type: PushConnector
    id: push_1
    name: Push 1
    description: test
""")
    activated = registry.activate_events("push_1")
    assert "get_value" not in activated


def test_dispatch_calls_handler_when_event_fires():
    PushConnector._callbacks = {}
    registry = make_registry(PushConnector)
    load_yaml_manifest(registry, """
connectors:
  - type: PushConnector
    id: push_1
    name: Push 1
    description: test
""")
    received = []
    registry.subscribe("push_1", "on_value_changed", received.append)
    registry.activate_events("push_1")

    PushConnector._callbacks["on_value_changed"]({"value": 42})
    assert received == [{"value": 42}]


def test_dispatch_calls_all_handlers():
    PushConnector._callbacks = {}
    registry = make_registry(PushConnector)
    load_yaml_manifest(registry, """
connectors:
  - type: PushConnector
    id: push_1
    name: Push 1
    description: test
""")
    a, b = [], []
    registry.subscribe("push_1", "on_value_changed", a.append)
    registry.subscribe("push_1", "on_value_changed", b.append)
    registry.activate_events("push_1")

    PushConnector._callbacks["on_value_changed"]("ping")
    assert a == ["ping"]
    assert b == ["ping"]


def test_dispatch_no_handlers_does_not_raise():
    PushConnector._callbacks = {}
    registry = make_registry(PushConnector)
    load_yaml_manifest(registry, """
connectors:
  - type: PushConnector
    id: push_1
    name: Push 1
    description: test
""")
    registry.activate_events("push_1")
    # no subscribers — should not raise
    PushConnector._callbacks["on_value_changed"]({"value": 99})


def test_activate_poll_connector_returns_empty():
    registry = make_registry(PollConnector)
    load_yaml_manifest(registry, """
connectors:
  - type: PollConnector
    id: poll_1
    name: Poll 1
    description: test
""")
    activated = registry.activate_events("poll_1")
    assert activated == []


# ---------------------------------------------------------------------------
# polling_candidates
# ---------------------------------------------------------------------------

def test_polling_candidates_includes_poll_only_instances():
    registry = make_registry(PushConnector, PollConnector)
    load_yaml_manifest(registry, """
connectors:
  - type: PushConnector
    id: push_1
    name: Push 1
    description: test
  - type: PollConnector
    id: poll_1
    name: Poll 1
    description: test
""")
    candidates = registry.polling_candidates()
    instance_ids = {c["instance_id"] for c in candidates}
    assert "poll_1" in instance_ids
    assert "push_1" not in instance_ids


def test_polling_candidates_lists_queries():
    registry = make_registry(PollConnector)
    load_yaml_manifest(registry, """
connectors:
  - type: PollConnector
    id: poll_1
    name: Poll 1
    description: test
""")
    candidates = registry.polling_candidates()
    queries = {c["query"] for c in candidates if c["instance_id"] == "poll_1"}
    assert "get_temperature" in queries
    assert "get_humidity" in queries


def test_polling_candidates_empty_when_all_push():
    registry = make_registry(PushConnector)
    load_yaml_manifest(registry, """
connectors:
  - type: PushConnector
    id: push_1
    name: Push 1
    description: test
""")
    assert registry.polling_candidates() == []
