"""
Contract tests for GarminMCPConnector.

Same contract assertions as test_garmin_contract.py — the MCP backend must
satisfy the identical interface. The MCP session is mocked at _call_tool()
so no real server process is needed.

Run with: python -m pytest tests/test_garmin_mcp_contract.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load garmin_mcp.py directly (no __init__.py in root connectors/)
_CONNECTOR_FILE = Path(__file__).parent.parent.parent / "connectors" / "garmin_mcp.py"
_spec = importlib.util.spec_from_file_location("garmin_mcp", _CONNECTOR_FILE)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]

# Patch MCP session startup so the import doesn't launch a subprocess
with patch("asyncio.new_event_loop"), patch("threading.Thread"):
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]

GarminMCPConnector = _mod.GarminMCPConnector

# ---------------------------------------------------------------------------
# Shared MCP response payloads (after "data" unwrapping)
# ---------------------------------------------------------------------------

_METRICS_STEPS = {
    "steps": {
        "totalSteps": 8423,
        "totalKilocalories": 2100,
        "activeKilocalories": 450,
    }
}

_METRICS_STRESS = {
    "stress": {"avgStressLevel": 42}
}

_SLEEP_DATA = {
    "dailySleepDTO": {
        "sleepTimeSeconds": 27000,
        "deepSleepSeconds": 5400,
        "lightSleepSeconds": 14400,
        "remSleepSeconds": 7200,
        "awakeSleepSeconds": 600,
        "sleepScores": {"overall": {"value": 78}},
        "sleepStartTimestampGMT": 1718319600000,
        "sleepEndTimestampGMT": 1718348400000,
    }
}

_ACTIVITIES = [
    {
        "activityId": 12345678,
        "activityName": "Morning Run",
        "activityType": {"typeKey": "running"},
        "startTimeLocal": "2026-06-13 07:30:00",
        "duration": 3000.0,
        "distance": 8500.0,
        "calories": 620,
        "averageHR": 155,
        "maxHR": 178,
        "averageSpeed": 5.88,
    }
]

_HR_DATA = {
    "heartRateValues": [
        [1718350000000, 72],
        [1718350060000, 75],
    ]
}

_EXPECTED_SLEEP_KEYS = {
    "total_sleep_h", "deep_h", "light_h", "rem_h", "awake_h",
    "score", "start_gmt", "end_gmt",
}

_EXPECTED_ACTIVITY_KEYS = {
    "id", "name", "type", "start", "duration_min", "distance_km",
    "calories", "avg_hr", "max_hr", "avg_pace_min_km",
}


def _make_connector() -> GarminMCPConnector:
    """Return a GarminMCPConnector with MCP session startup fully bypassed."""
    with (
        patch("asyncio.new_event_loop") as mock_loop,
        patch("threading.Thread"),
    ):
        mock_loop.return_value = MagicMock()
        connector = GarminMCPConnector.__new__(GarminMCPConnector)
        connector._loop = MagicMock()
        connector._thread = MagicMock()
        connector._session = MagicMock()
        connector._exit_stack = MagicMock()
    return connector


def _with_tool(connector: GarminMCPConnector, responses: dict[str, object]):
    """Patch _call_tool to return canned responses per tool name."""
    def _fake_call_tool(tool: str, args: dict) -> object:
        return responses.get(tool)
    connector._call_tool = _fake_call_tool  # type: ignore[method-assign]
    return connector


# ---------------------------------------------------------------------------
# CAP-1: Operation discovery
# ---------------------------------------------------------------------------


def test_steps_today_is_query():
    assert "steps_today" in GarminMCPConnector._operations
    assert GarminMCPConnector._operations["steps_today"].kind == "query"


def test_calories_today_is_query():
    assert "calories_today" in GarminMCPConnector._operations


def test_stress_level_is_query():
    assert "stress_level" in GarminMCPConnector._operations


def test_last_sleep_is_query():
    assert "last_sleep" in GarminMCPConnector._operations


def test_last_activity_is_query():
    assert "last_activity" in GarminMCPConnector._operations


def test_heart_rate_history_is_query():
    assert "heart_rate_history" in GarminMCPConnector._operations


def test_no_events_declared():
    """MCP backend is polling-only — no @event operations."""
    event_ops = [
        name for name, op in GarminMCPConnector._operations.items()
        if op.kind == "event"
    ]
    assert event_ops == []


# ---------------------------------------------------------------------------
# CAP-1: Descriptions
# ---------------------------------------------------------------------------


def test_all_operations_have_descriptions():
    for name, op in GarminMCPConnector._operations.items():
        assert op.description, f"Operation '{name}' has no description"


# ---------------------------------------------------------------------------
# CAP-5: Return schemas
# ---------------------------------------------------------------------------


def test_steps_today_schema():
    op = GarminMCPConnector._operations["steps_today"]
    assert op.returns.type == "number"
    assert op.returns.unit == "steps/day"


def test_calories_today_schema():
    op = GarminMCPConnector._operations["calories_today"]
    assert op.returns.type == "number"
    assert op.returns.unit == "kcal"


def test_stress_level_schema():
    assert GarminMCPConnector._operations["stress_level"].returns.type == "number"


def test_last_sleep_schema():
    assert GarminMCPConnector._operations["last_sleep"].returns.type == "object"


def test_last_activity_schema():
    assert GarminMCPConnector._operations["last_activity"].returns.type == "object"


def test_heart_rate_history_schema():
    assert GarminMCPConnector._operations["heart_rate_history"].returns.type == "list"


# ---------------------------------------------------------------------------
# Output shape — same contract as Python backend
# ---------------------------------------------------------------------------


def test_steps_today_value():
    c = _with_tool(_make_connector(), {"query_activity_metrics": _METRICS_STEPS})
    result = c.call("steps_today")
    assert result.ok is True
    assert result.data == 8423


def test_steps_today_zero_when_empty():
    c = _with_tool(_make_connector(), {"query_activity_metrics": {}})
    result = c.call("steps_today")
    assert result.ok is True
    assert result.data == 0


def test_calories_today_value():
    c = _with_tool(_make_connector(), {"query_activity_metrics": _METRICS_STEPS})
    result = c.call("calories_today")
    assert result.ok is True
    assert isinstance(result.data, int)
    assert result.data > 0


def test_stress_level_value():
    c = _with_tool(_make_connector(), {"query_activity_metrics": _METRICS_STRESS})
    result = c.call("stress_level")
    assert result.ok is True
    assert result.data == 42
    assert -1 <= result.data <= 100


def test_stress_level_minus_one_when_no_data():
    c = _with_tool(_make_connector(), {"query_activity_metrics": {"stress": {}}})
    result = c.call("stress_level")
    assert result.ok is True
    assert result.data == -1


def test_last_sleep_output_keys():
    c = _with_tool(_make_connector(), {"query_sleep_data": _SLEEP_DATA})
    result = c.call("last_sleep")
    assert result.ok is True
    assert set(result.data.keys()) == _EXPECTED_SLEEP_KEYS


def test_last_sleep_values_in_hours():
    c = _with_tool(_make_connector(), {"query_sleep_data": _SLEEP_DATA})
    result = c.call("last_sleep")
    assert result.data["total_sleep_h"] == pytest.approx(7.5, abs=0.01)
    assert result.data["deep_h"] == pytest.approx(1.5, abs=0.01)
    assert result.data["score"] == 78


def test_last_activity_output_keys():
    c = _with_tool(_make_connector(), {"query_activities": _ACTIVITIES})
    result = c.call("last_activity")
    assert result.ok is True
    assert set(result.data.keys()) == _EXPECTED_ACTIVITY_KEYS


def test_last_activity_duration_minutes():
    c = _with_tool(_make_connector(), {"query_activities": _ACTIVITIES})
    result = c.call("last_activity")
    assert result.data["duration_min"] == pytest.approx(50.0, abs=0.1)


def test_last_activity_distance_km():
    c = _with_tool(_make_connector(), {"query_activities": _ACTIVITIES})
    result = c.call("last_activity")
    assert result.data["distance_km"] == pytest.approx(8.5, abs=0.01)


def test_last_activity_empty_when_no_activities():
    c = _with_tool(_make_connector(), {"query_activities": []})
    result = c.call("last_activity")
    assert result.ok is True
    assert result.data == {}


def test_heart_rate_history_shape():
    c = _with_tool(_make_connector(), {"query_heart_rate_data": _HR_DATA})
    result = c.call("heart_rate_history")
    assert result.ok is True
    assert len(result.data) == 2
    for entry in result.data:
        assert set(entry.keys()) == {"timestamp_ms", "bpm"}


def test_heart_rate_history_filters_null_bpm():
    c = _with_tool(_make_connector(), {
        "query_heart_rate_data": {"heartRateValues": [[1718350000000, 72], [1718350060000, None]]}
    })
    result = c.call("heart_rate_history")
    assert len(result.data) == 1


def test_heart_rate_history_empty_when_no_data():
    c = _with_tool(_make_connector(), {"query_heart_rate_data": {}})
    result = c.call("heart_rate_history")
    assert result.ok is True
    assert result.data == []


# ---------------------------------------------------------------------------
# CAP-5: Error envelope
# ---------------------------------------------------------------------------


def test_auth_error_propagates():
    c = _make_connector()
    def _fail(tool, args): raise PermissionError
    c._call_tool = _fail  # type: ignore[method-assign]
    result = c.call("steps_today")
    assert result.ok is False
    assert result.error == "auth"


def test_timeout_error_propagates():
    c = _make_connector()
    def _fail(tool, args): raise TimeoutError
    c._call_tool = _fail  # type: ignore[method-assign]
    result = c.call("steps_today")
    assert result.ok is False
    assert result.error == "timeout"
