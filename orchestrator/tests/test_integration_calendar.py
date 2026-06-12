"""
Integration tests for GoogleCalendarConnector.

These tests hit the real Google Calendar API. On first run with no token,
the connector opens a browser for OAuth consent automatically — no separate
setup step required.

Run:
    pytest -m integration -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import connectors_setup


@pytest.fixture(scope="module")
def registry():
    return connectors_setup.build_registry()


@pytest.mark.integration
def test_events_today_returns_list(registry):
    result = registry.call("calendar_fred", "events_today")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)


@pytest.mark.integration
def test_next_event_returns_dict_or_none(registry):
    result = registry.call("calendar_fred", "next_event")
    assert result.ok is True, f"call failed: {result.error}"
    assert result.data is None or isinstance(result.data, dict)


@pytest.mark.integration
def test_event_fields_present(registry):
    result = registry.call("calendar_fred", "events_today")
    assert result.ok is True
    for event in result.data:
        assert "id" in event
        assert "title" in event
        assert "start" in event
        assert "end" in event


@pytest.mark.integration
def test_upcoming_events_default_7_days(registry):
    result = registry.call("calendar_fred", "upcoming_events")
    assert result.ok is True
    assert isinstance(result.data, list)


@pytest.mark.integration
def test_get_connector_contract_has_queries(registry):
    contract = registry.load_contract("calendar_fred")
    assert "queries" in contract
    query_names = {q["name"] for q in contract["queries"]}
    assert "events_today" in query_names
    assert "next_event" in query_names
