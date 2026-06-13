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

from datetime import UTC

import connectors_setup


@pytest.fixture(scope="module")
def registry():
    return connectors_setup.build_registry()


@pytest.mark.integration
def test_list_events_no_params_returns_list(registry):
    result = registry.call("calendar_fred", "list_events")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)


@pytest.mark.integration
def test_list_events_explicit_range(registry):
    from datetime import datetime, timedelta

    now = datetime.now(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    end = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    result = registry.call("calendar_fred", "list_events", {"start_iso": start, "end_iso": end})
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)


@pytest.mark.integration
def test_list_events_fields_present(registry):
    result = registry.call("calendar_fred", "list_events")
    assert result.ok is True
    for event in result.data:
        assert "id" in event
        assert "title" in event
        assert "start" in event
        assert "end" in event


@pytest.mark.integration
def test_is_available_returns_bool(registry):
    from datetime import datetime, timedelta

    far_future = datetime.now(UTC) + timedelta(days=365)
    start = far_future.replace(hour=3, minute=0, second=0, microsecond=0).isoformat()
    end = far_future.replace(hour=4, minute=0, second=0, microsecond=0).isoformat()
    result = registry.call("calendar_fred", "is_available", {"start_iso": start, "end_iso": end})
    assert result.ok is True
    assert isinstance(result.data, bool)


@pytest.mark.integration
def test_get_connector_contract_has_list_events(registry):
    contract = registry.load_contract("calendar_fred")
    assert "queries" in contract
    query_names = {q["name"] for q in contract["queries"]}
    assert "list_events" in query_names
    assert "is_available" in query_names
