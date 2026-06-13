"""
Contract tests for GoogleCalendarMCPConnector.

Same contract assertions as test_calendar_contract.py — the MCP backend must
satisfy the identical interface. The MCP session is mocked at _call_tool()
so no real server process is needed.

Run with: python -m pytest tests/test_calendar_mcp_contract.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_CONNECTOR_FILE = Path(__file__).parent.parent.parent / "connectors" / "google_calendar_mcp.py"
_spec = importlib.util.spec_from_file_location("google_calendar_mcp", _CONNECTOR_FILE)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]

with patch("asyncio.new_event_loop"), patch("threading.Thread"):
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]

GoogleCalendarMCPConnector = _mod.GoogleCalendarMCPConnector

# ---------------------------------------------------------------------------
# Shared MCP response payloads
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

_GET_EVENTS_ONE = {"items": [_RAW_EVENT]}
_GET_EVENTS_EMPTY = {"items": []}

_FREEBUSY_FREE = {"calendars": {"primary": {"busy": []}}}
_FREEBUSY_BUSY = {"calendars": {"primary": {"busy": [{"start": "2026-06-14T10:00:00Z", "end": "2026-06-14T11:00:00Z"}]}}}

_CREATE_SUCCESS = {
    "success": True,
    "event": _RAW_EVENT,
    "message": "Event created",
    "event_link": "https://calendar.google.com/event?eid=abc123",
    "event_id": "abc123",
}

_DELETE_SUCCESS = {"success": True, "message": "Event abc123 deleted successfully"}

_EXPECTED_EVENT_KEYS = {"id", "title", "start", "end", "location", "notes", "link"}


def _make_connector() -> GoogleCalendarMCPConnector:
    with (
        patch("asyncio.new_event_loop") as mock_loop,
        patch("threading.Thread"),
    ):
        mock_loop.return_value = MagicMock()
        connector = GoogleCalendarMCPConnector.__new__(GoogleCalendarMCPConnector)
        connector._loop = MagicMock()
        connector._thread = MagicMock()
        connector._session = MagicMock()
        connector._exit_stack = MagicMock()
    return connector


def _with_tool(connector: GoogleCalendarMCPConnector, responses: dict[str, object]):
    def _fake(tool: str, args: dict) -> object:
        return responses.get(tool)
    connector._call_tool = _fake  # type: ignore[method-assign]
    return connector


# ---------------------------------------------------------------------------
# CAP-1: Operation discovery
# ---------------------------------------------------------------------------

def test_list_events_is_query():
    assert "list_events" in GoogleCalendarMCPConnector._operations
    assert GoogleCalendarMCPConnector._operations["list_events"].kind == "query"


def test_is_available_is_query():
    assert "is_available" in GoogleCalendarMCPConnector._operations
    assert GoogleCalendarMCPConnector._operations["is_available"].kind == "query"


def test_create_event_is_command():
    assert "create_event" in GoogleCalendarMCPConnector._operations
    assert GoogleCalendarMCPConnector._operations["create_event"].kind == "command"


def test_cancel_event_is_command():
    assert "cancel_event" in GoogleCalendarMCPConnector._operations
    assert GoogleCalendarMCPConnector._operations["cancel_event"].kind == "command"


def test_no_events_declared():
    """MCP backend is polling-only — no @event operations."""
    event_ops = [
        name for name, op in GoogleCalendarMCPConnector._operations.items()
        if op.kind == "event"
    ]
    assert event_ops == []


# ---------------------------------------------------------------------------
# CAP-1: Descriptions
# ---------------------------------------------------------------------------

def test_all_operations_have_descriptions():
    for name, op in GoogleCalendarMCPConnector._operations.items():
        assert op.description, f"Operation '{name}' has no description"


# ---------------------------------------------------------------------------
# CAP-5: Param schemas
# ---------------------------------------------------------------------------

def test_list_events_params_are_optional():
    params = GoogleCalendarMCPConnector._operations["list_events"].params
    for param_name in ("start_iso", "end_iso", "max_results"):
        assert param_name in params
        assert params[param_name].required is False


def test_is_available_requires_start_and_end():
    params = GoogleCalendarMCPConnector._operations["is_available"].params
    assert params["start_iso"].required is True
    assert params["end_iso"].required is True


def test_create_event_required_params():
    params = GoogleCalendarMCPConnector._operations["create_event"].params
    assert params["title"].required is True
    assert params["start_iso"].required is True
    assert params["end_iso"].required is True
    assert params["notes"].required is False


def test_cancel_event_requires_event_id():
    params = GoogleCalendarMCPConnector._operations["cancel_event"].params
    assert params["event_id"].required is True


# ---------------------------------------------------------------------------
# CAP-5: Return schemas
# ---------------------------------------------------------------------------

def test_list_events_returns_list():
    assert GoogleCalendarMCPConnector._operations["list_events"].returns.type == "list"


def test_is_available_returns_boolean():
    assert GoogleCalendarMCPConnector._operations["is_available"].returns.type == "boolean"


def test_create_event_returns_object():
    assert GoogleCalendarMCPConnector._operations["create_event"].returns.type == "object"


def test_cancel_event_returns_boolean():
    assert GoogleCalendarMCPConnector._operations["cancel_event"].returns.type == "boolean"


# ---------------------------------------------------------------------------
# Output shape — list_events
# ---------------------------------------------------------------------------

def test_list_events_output_shape():
    c = _with_tool(_make_connector(), {"get-events": _GET_EVENTS_ONE})
    result = c.call("list_events")
    assert result.ok is True
    assert isinstance(result.data, list)
    assert len(result.data) == 1
    assert set(result.data[0].keys()) == _EXPECTED_EVENT_KEYS


def test_list_events_event_values():
    c = _with_tool(_make_connector(), {"get-events": _GET_EVENTS_ONE})
    result = c.call("list_events")
    event = result.data[0]
    assert event["id"] == "abc123"
    assert event["title"] == "Team meeting"
    assert event["start"] == "2026-06-14T10:00:00+00:00"
    assert event["end"] == "2026-06-14T11:00:00+00:00"
    assert event["location"] == "Room 1"
    assert event["notes"] == "Weekly sync"
    assert event["link"] == "https://calendar.google.com/event?eid=abc123"


def test_list_events_empty_returns_empty_list():
    c = _with_tool(_make_connector(), {"get-events": _GET_EVENTS_EMPTY})
    result = c.call("list_events")
    assert result.ok is True
    assert result.data == []


def test_list_events_optional_fields_are_none_when_absent():
    raw = {
        "id": "x1", "summary": "No frills",
        "start": {"dateTime": "2026-06-14T09:00:00+00:00"},
        "end": {"dateTime": "2026-06-14T10:00:00+00:00"},
    }
    c = _with_tool(_make_connector(), {"get-events": {"items": [raw]}})
    result = c.call("list_events")
    event = result.data[0]
    assert event["location"] is None
    assert event["notes"] is None
    assert event["link"] is None


def test_list_events_all_day_event_uses_date_not_datetime():
    raw = {
        "id": "allday1", "summary": "Holiday",
        "start": {"date": "2026-06-20"},
        "end": {"date": "2026-06-21"},
    }
    c = _with_tool(_make_connector(), {"get-events": {"items": [raw]}})
    result = c.call("list_events")
    assert result.data[0]["start"] == "2026-06-20"
    assert result.data[0]["end"] == "2026-06-21"


def test_list_events_no_params_succeeds():
    c = _with_tool(_make_connector(), {"get-events": _GET_EVENTS_EMPTY})
    result = c.call("list_events")
    assert result.ok is True


# ---------------------------------------------------------------------------
# Output shape — is_available
# ---------------------------------------------------------------------------

def test_is_available_true_when_no_events():
    c = _with_tool(_make_connector(), {"check-availability": _FREEBUSY_FREE})
    result = c.call("is_available", {
        "start_iso": "2026-06-14T10:00:00+00:00",
        "end_iso": "2026-06-14T11:00:00+00:00",
    })
    assert result.ok is True
    assert result.data is True


def test_is_available_false_when_events_exist():
    c = _with_tool(_make_connector(), {"check-availability": _FREEBUSY_BUSY})
    result = c.call("is_available", {
        "start_iso": "2026-06-14T10:00:00+00:00",
        "end_iso": "2026-06-14T11:00:00+00:00",
    })
    assert result.ok is True
    assert result.data is False


# ---------------------------------------------------------------------------
# Output shape — create_event
# ---------------------------------------------------------------------------

def test_create_event_output_shape():
    c = _with_tool(_make_connector(), {"create-event": _CREATE_SUCCESS})
    result = c.call("create_event", {
        "title": "Team meeting",
        "start_iso": "2026-06-14T10:00:00+00:00",
        "end_iso": "2026-06-14T11:00:00+00:00",
    })
    assert result.ok is True
    assert isinstance(result.data, dict)
    assert set(result.data.keys()) == _EXPECTED_EVENT_KEYS
    assert result.data["id"] == "abc123"
    assert result.data["title"] == "Team meeting"


def test_create_event_with_notes():
    raw_with_notes = {**_RAW_EVENT, "description": "Bring slides"}
    c = _with_tool(_make_connector(), {"create-event": {**_CREATE_SUCCESS, "event": raw_with_notes}})
    result = c.call("create_event", {
        "title": "Presentation",
        "start_iso": "2026-06-14T10:00:00+00:00",
        "end_iso": "2026-06-14T11:00:00+00:00",
        "notes": "Bring slides",
    })
    assert result.ok is True
    assert result.data["notes"] == "Bring slides"


# ---------------------------------------------------------------------------
# Output shape — cancel_event
# ---------------------------------------------------------------------------

def test_cancel_event_returns_true():
    c = _with_tool(_make_connector(), {"delete-event": _DELETE_SUCCESS})
    result = c.call("cancel_event", {"event_id": "abc123"})
    assert result.ok is True
    assert result.data is True


# ---------------------------------------------------------------------------
# CAP-5: Validation errors
# ---------------------------------------------------------------------------

def test_create_event_missing_title_rejected():
    c = _make_connector()
    result = c.call("create_event", {
        "start_iso": "2026-06-14T10:00:00+00:00",
        "end_iso": "2026-06-14T11:00:00+00:00",
    })
    assert result.ok is False
    assert result.error == "validation_error"


def test_cancel_event_missing_id_rejected():
    c = _make_connector()
    result = c.call("cancel_event", {})
    assert result.ok is False
    assert result.error == "validation_error"


# ---------------------------------------------------------------------------
# CAP-5: Error envelope
# ---------------------------------------------------------------------------

def test_auth_error_propagates():
    c = _make_connector()
    def _fail(tool, args): raise PermissionError
    c._call_tool = _fail  # type: ignore[method-assign]
    result = c.call("list_events")
    assert result.ok is False
    assert result.error == "auth"


def test_timeout_error_propagates():
    c = _make_connector()
    def _fail(tool, args): raise TimeoutError
    c._call_tool = _fail  # type: ignore[method-assign]
    result = c.call("list_events")
    assert result.ok is False
    assert result.error == "timeout"
