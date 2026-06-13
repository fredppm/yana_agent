"""
Contract tests for GoogleCalendarConnector.

These tests define the interface contract that any backend (current Python
implementation or future MCP server) must satisfy. They do NOT test Google
API integration — only the operation signatures and output shapes.

Run with: python -m pytest tests/test_calendar_contract.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# orchestrator/ must be on sys.path so that google_calendar.py can resolve
# its own `from connectors import ...` against the framework package.
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load google_calendar.py directly — it lives in the project root connectors/
# directory which has no __init__.py (standalone module, not a package).
_CONNECTOR_FILE = Path(__file__).parent.parent.parent / "connectors" / "google_calendar.py"
_spec = importlib.util.spec_from_file_location("google_calendar", _CONNECTOR_FILE)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
GoogleCalendarConnector = _mod.GoogleCalendarConnector

# ---------------------------------------------------------------------------
# Shared event shape used in mocks
# ---------------------------------------------------------------------------

_RAW_EVENT = {
    "id": "abc123",
    "summary": "Team meeting",
    "start": {"dateTime": "2026-06-14T10:00:00+00:00"},
    "end": {"dateTime": "2026-06-14T11:00:00+00:00"},
    "location": "Room 1",
    "description": "Weekly sync",
    "htmlLink": "https://calendar.google.com/event?eid=abc123",
}

_EXPECTED_EVENT_KEYS = {"id", "title", "start", "end", "location", "notes", "link"}


def _make_connector() -> tuple[Any, MagicMock]:
    """Return a connector instance with the Google service layer mocked out."""
    connector = GoogleCalendarConnector(
        credentials_file="/dev/null",
        token_file="/dev/null",
    )
    mock_svc = MagicMock()
    connector._service = mock_svc
    return connector, mock_svc


# ---------------------------------------------------------------------------
# CAP-1: Operation discovery — operations and their kinds
# ---------------------------------------------------------------------------


def test_list_events_is_query():
    assert "list_events" in GoogleCalendarConnector._operations
    assert GoogleCalendarConnector._operations["list_events"].kind == "query"


def test_is_available_is_query():
    assert "is_available" in GoogleCalendarConnector._operations
    assert GoogleCalendarConnector._operations["is_available"].kind == "query"


def test_create_event_is_command():
    assert "create_event" in GoogleCalendarConnector._operations
    assert GoogleCalendarConnector._operations["create_event"].kind == "command"


def test_cancel_event_is_command():
    assert "cancel_event" in GoogleCalendarConnector._operations
    assert GoogleCalendarConnector._operations["cancel_event"].kind == "command"


# ---------------------------------------------------------------------------
# CAP-1: Descriptions are present (AI-readable)
# ---------------------------------------------------------------------------


def test_all_operations_have_descriptions():
    for name, op in GoogleCalendarConnector._operations.items():
        assert op.description, f"Operation '{name}' has no description"


# ---------------------------------------------------------------------------
# CAP-5: Param schemas
# ---------------------------------------------------------------------------


def test_list_events_params_are_optional():
    params = GoogleCalendarConnector._operations["list_events"].params
    for param_name in ("start_iso", "end_iso", "max_results"):
        assert param_name in params, f"Missing param '{param_name}'"
        assert params[param_name].required is False, f"'{param_name}' should be optional"


def test_is_available_requires_start_and_end():
    params = GoogleCalendarConnector._operations["is_available"].params
    assert params["start_iso"].required is True
    assert params["end_iso"].required is True


def test_create_event_required_params():
    params = GoogleCalendarConnector._operations["create_event"].params
    assert params["title"].required is True
    assert params["start_iso"].required is True
    assert params["end_iso"].required is True
    assert params["notes"].required is False


def test_cancel_event_requires_event_id():
    params = GoogleCalendarConnector._operations["cancel_event"].params
    assert params["event_id"].required is True


# ---------------------------------------------------------------------------
# CAP-5: Return schemas
# ---------------------------------------------------------------------------


def test_list_events_returns_list():
    op = GoogleCalendarConnector._operations["list_events"]
    assert op.returns.type == "list"


def test_is_available_returns_boolean():
    op = GoogleCalendarConnector._operations["is_available"]
    assert op.returns.type == "boolean"


def test_create_event_returns_object():
    op = GoogleCalendarConnector._operations["create_event"]
    assert op.returns.type == "object"


def test_cancel_event_returns_boolean():
    op = GoogleCalendarConnector._operations["cancel_event"]
    assert op.returns.type == "boolean"


# ---------------------------------------------------------------------------
# Output shape contract — the event dict
# This is the critical contract: any MCP backend must return events
# with exactly these keys. Missing or renamed keys break YANA.
# ---------------------------------------------------------------------------


def test_list_events_output_shape():
    connector, mock_svc = _make_connector()
    mock_svc.events.return_value.list.return_value.execute.return_value = {"items": [_RAW_EVENT]}

    result = connector.call("list_events")

    assert result.ok is True
    assert isinstance(result.data, list)
    assert len(result.data) == 1
    event = result.data[0]
    assert set(event.keys()) == _EXPECTED_EVENT_KEYS


def test_list_events_event_values():
    connector, mock_svc = _make_connector()
    mock_svc.events.return_value.list.return_value.execute.return_value = {"items": [_RAW_EVENT]}

    result = connector.call("list_events")
    event = result.data[0]

    assert event["id"] == "abc123"
    assert event["title"] == "Team meeting"
    assert event["start"] == "2026-06-14T10:00:00+00:00"
    assert event["end"] == "2026-06-14T11:00:00+00:00"
    assert event["location"] == "Room 1"
    assert event["notes"] == "Weekly sync"
    assert event["link"] == "https://calendar.google.com/event?eid=abc123"


def test_list_events_empty_returns_empty_list():
    connector, mock_svc = _make_connector()
    mock_svc.events.return_value.list.return_value.execute.return_value = {"items": []}

    result = connector.call("list_events")

    assert result.ok is True
    assert result.data == []


def test_list_events_optional_fields_are_none_when_absent():
    connector, mock_svc = _make_connector()
    raw = {
        "id": "x1",
        "summary": "No frills",
        "start": {"dateTime": "2026-06-14T09:00:00+00:00"},
        "end": {"dateTime": "2026-06-14T10:00:00+00:00"},
    }
    mock_svc.events.return_value.list.return_value.execute.return_value = {"items": [raw]}

    result = connector.call("list_events")
    event = result.data[0]

    assert event["location"] is None
    assert event["notes"] is None
    assert event["link"] is None


def test_list_events_all_day_event_uses_date_not_datetime():
    """All-day events use 'date' key instead of 'dateTime' — contract must handle both."""
    connector, mock_svc = _make_connector()
    raw = {
        "id": "allday1",
        "summary": "Holiday",
        "start": {"date": "2026-06-20"},
        "end": {"date": "2026-06-21"},
    }
    mock_svc.events.return_value.list.return_value.execute.return_value = {"items": [raw]}

    result = connector.call("list_events")
    event = result.data[0]

    assert event["start"] == "2026-06-20"
    assert event["end"] == "2026-06-21"


def test_create_event_output_shape():
    connector, mock_svc = _make_connector()
    mock_svc.events.return_value.insert.return_value.execute.return_value = _RAW_EVENT

    result = connector.call(
        "create_event",
        {
            "title": "Team meeting",
            "start_iso": "2026-06-14T10:00:00+00:00",
            "end_iso": "2026-06-14T11:00:00+00:00",
        },
    )

    assert result.ok is True
    assert isinstance(result.data, dict)
    assert set(result.data.keys()) == _EXPECTED_EVENT_KEYS
    assert result.data["id"] == "abc123"
    assert result.data["title"] == "Team meeting"


def test_create_event_with_notes():
    connector, mock_svc = _make_connector()
    mock_svc.events.return_value.insert.return_value.execute.return_value = {
        **_RAW_EVENT,
        "description": "Bring slides",
    }

    result = connector.call(
        "create_event",
        {
            "title": "Presentation",
            "start_iso": "2026-06-14T10:00:00+00:00",
            "end_iso": "2026-06-14T11:00:00+00:00",
            "notes": "Bring slides",
        },
    )

    assert result.ok is True
    assert result.data["notes"] == "Bring slides"


def test_is_available_true_when_no_events():
    connector, mock_svc = _make_connector()
    mock_svc.events.return_value.list.return_value.execute.return_value = {"items": []}

    result = connector.call(
        "is_available",
        {
            "start_iso": "2026-06-14T10:00:00+00:00",
            "end_iso": "2026-06-14T11:00:00+00:00",
        },
    )

    assert result.ok is True
    assert result.data is True


def test_is_available_false_when_events_exist():
    connector, mock_svc = _make_connector()
    mock_svc.events.return_value.list.return_value.execute.return_value = {"items": [_RAW_EVENT]}

    result = connector.call(
        "is_available",
        {
            "start_iso": "2026-06-14T10:00:00+00:00",
            "end_iso": "2026-06-14T11:00:00+00:00",
        },
    )

    assert result.ok is True
    assert result.data is False


def test_cancel_event_returns_true():
    connector, mock_svc = _make_connector()
    mock_svc.events.return_value.delete.return_value.execute.return_value = None

    result = connector.call("cancel_event", {"event_id": "abc123"})

    assert result.ok is True
    assert result.data is True


# ---------------------------------------------------------------------------
# CAP-5: Validation errors — wrong params rejected before backend
# ---------------------------------------------------------------------------


def test_list_events_no_params_succeeds():
    """All params optional — zero params must be valid."""
    connector, mock_svc = _make_connector()
    mock_svc.events.return_value.list.return_value.execute.return_value = {"items": []}

    result = connector.call("list_events")
    assert result.ok is True


def test_create_event_missing_title_rejected():
    connector, _ = _make_connector()
    result = connector.call(
        "create_event",
        {
            "start_iso": "2026-06-14T10:00:00+00:00",
            "end_iso": "2026-06-14T11:00:00+00:00",
        },
    )
    assert result.ok is False
    assert result.error == "validation_error"


def test_cancel_event_missing_id_rejected():
    connector, _ = _make_connector()
    result = connector.call("cancel_event", {})
    assert result.ok is False
    assert result.error == "validation_error"


# ---------------------------------------------------------------------------
# CAP-5: Error envelope
# ---------------------------------------------------------------------------


def test_list_events_auth_failure_maps_to_auth_error():
    connector, mock_svc = _make_connector()
    mock_svc.events.return_value.list.return_value.execute.side_effect = PermissionError

    result = connector.call("list_events")

    assert result.ok is False
    assert result.error == "auth"


def test_list_events_timeout_maps_to_timeout_error():
    connector, mock_svc = _make_connector()
    mock_svc.events.return_value.list.return_value.execute.side_effect = TimeoutError

    result = connector.call("list_events")

    assert result.ok is False
    assert result.error == "timeout"
