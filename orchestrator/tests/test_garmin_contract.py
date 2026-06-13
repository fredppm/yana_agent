"""
Contract tests for GarminActivityConnector.

These tests define the interface contract that any backend (current Python
implementation or future MCP server) must satisfy. They do NOT test Garmin
API integration — only the operation signatures and output shapes.

Run with: python -m pytest tests/test_garmin_contract.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# orchestrator/ must be on sys.path so that garmin.py can resolve
# its own `from connectors import ...` against the framework package.
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load garmin.py directly — standalone module with no __init__.py package.
_CONNECTOR_FILE = Path(__file__).parent.parent.parent / "connectors" / "garmin.py"
_spec = importlib.util.spec_from_file_location("garmin", _CONNECTOR_FILE)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
GarminActivityConnector = _mod.GarminActivityConnector

# ---------------------------------------------------------------------------
# Shared raw API responses used in mocks
# ---------------------------------------------------------------------------

_RAW_STATS = {
    "totalSteps": 8423,
    "totalKilocalories": 2100,
    "activeKilocalories": 450,
}

_RAW_STRESS = {"avgStressLevel": 42}

_RAW_SLEEP_DTO = {
    "sleepTimeSeconds": 27000,  # 7.5 h
    "deepSleepSeconds": 5400,  # 1.5 h
    "lightSleepSeconds": 14400,  # 4.0 h
    "remSleepSeconds": 7200,  # 2.0 h
    "awakeSleepSeconds": 600,  # 0.17 h
    "sleepScores": {"overall": {"value": 78}},
    "sleepStartTimestampGMT": 1718319600000,
    "sleepEndTimestampGMT": 1718348400000,
}

_RAW_ACTIVITY = {
    "activityId": 12345678,
    "activityName": "Morning Run",
    "activityType": {"typeKey": "running"},
    "startTimeLocal": "2026-06-13 07:30:00",
    "duration": 3000.0,  # 50 min in seconds
    "distance": 8500.0,  # 8.5 km in metres
    "calories": 620,
    "averageHR": 155,
    "maxHR": 178,
    "averageSpeed": 5.88,  # raw unit — AI converts
}

_EXPECTED_SLEEP_KEYS = {
    "total_sleep_h",
    "deep_h",
    "light_h",
    "rem_h",
    "awake_h",
    "score",
    "start_gmt",
    "end_gmt",
}

_EXPECTED_ACTIVITY_KEYS = {
    "id",
    "name",
    "type",
    "start",
    "duration_min",
    "distance_km",
    "calories",
    "avg_hr",
    "max_hr",
    "avg_pace_min_km",
}

_EXPECTED_HR_ENTRY_KEYS = {"timestamp_ms", "bpm"}


def _make_connector() -> tuple[Any, MagicMock]:
    """Return a connector with the Garmin client layer mocked out."""
    connector = GarminActivityConnector(
        credentials_file="/dev/null",
        token_dir="/dev/null",
    )
    mock_client = MagicMock()
    connector._client = mock_client
    return connector, mock_client


# ---------------------------------------------------------------------------
# CAP-1: Operation discovery
# ---------------------------------------------------------------------------


def test_steps_today_is_query():
    assert "steps_today" in GarminActivityConnector._operations
    assert GarminActivityConnector._operations["steps_today"].kind == "query"


def test_calories_today_is_query():
    assert "calories_today" in GarminActivityConnector._operations
    assert GarminActivityConnector._operations["calories_today"].kind == "query"


def test_stress_level_is_query():
    assert "stress_level" in GarminActivityConnector._operations
    assert GarminActivityConnector._operations["stress_level"].kind == "query"


def test_last_sleep_is_query():
    assert "last_sleep" in GarminActivityConnector._operations
    assert GarminActivityConnector._operations["last_sleep"].kind == "query"


def test_last_activity_is_query():
    assert "last_activity" in GarminActivityConnector._operations
    assert GarminActivityConnector._operations["last_activity"].kind == "query"


def test_heart_rate_history_is_query():
    assert "heart_rate_history" in GarminActivityConnector._operations
    assert GarminActivityConnector._operations["heart_rate_history"].kind == "query"


# ---------------------------------------------------------------------------
# CAP-1: Descriptions are present (AI-readable)
# ---------------------------------------------------------------------------


def test_all_operations_have_descriptions():
    for name, op in GarminActivityConnector._operations.items():
        assert op.description, f"Operation '{name}' has no description"


# ---------------------------------------------------------------------------
# CAP-5: Return schemas
# ---------------------------------------------------------------------------


def test_steps_today_returns_number():
    assert GarminActivityConnector._operations["steps_today"].returns.type == "number"
    assert GarminActivityConnector._operations["steps_today"].returns.unit == "steps/day"


def test_calories_today_returns_number_kcal():
    op = GarminActivityConnector._operations["calories_today"]
    assert op.returns.type == "number"
    assert op.returns.unit == "kcal"


def test_stress_level_returns_number():
    assert GarminActivityConnector._operations["stress_level"].returns.type == "number"


def test_last_sleep_returns_object():
    assert GarminActivityConnector._operations["last_sleep"].returns.type == "object"


def test_last_activity_returns_object():
    assert GarminActivityConnector._operations["last_activity"].returns.type == "object"


def test_heart_rate_history_returns_list():
    assert GarminActivityConnector._operations["heart_rate_history"].returns.type == "list"


# ---------------------------------------------------------------------------
# Output shape — steps_today
# ---------------------------------------------------------------------------


def test_steps_today_returns_integer():
    connector, mock_client = _make_connector()
    mock_client.get_stats.return_value = _RAW_STATS

    result = connector.call("steps_today")

    assert result.ok is True
    assert result.data == 8423
    assert isinstance(result.data, int)


def test_steps_today_zero_when_no_data():
    connector, mock_client = _make_connector()
    mock_client.get_stats.return_value = {}

    result = connector.call("steps_today")

    assert result.ok is True
    assert result.data == 0


# ---------------------------------------------------------------------------
# Output shape — calories_today
# ---------------------------------------------------------------------------


def test_calories_today_returns_integer():
    connector, mock_client = _make_connector()
    mock_client.get_stats.return_value = _RAW_STATS

    result = connector.call("calories_today")

    assert result.ok is True
    assert isinstance(result.data, int)
    assert result.data > 0


def test_calories_today_zero_when_no_data():
    connector, mock_client = _make_connector()
    mock_client.get_stats.return_value = {}

    result = connector.call("calories_today")

    assert result.ok is True
    assert result.data == 0


# ---------------------------------------------------------------------------
# Output shape — stress_level
# ---------------------------------------------------------------------------


def test_stress_level_returns_integer_in_range():
    connector, mock_client = _make_connector()
    mock_client.get_stress_data.return_value = _RAW_STRESS

    result = connector.call("stress_level")

    assert result.ok is True
    assert isinstance(result.data, int)
    assert -1 <= result.data <= 100


def test_stress_level_minus_one_when_no_data():
    """Contract: -1 means no stress data available yet today."""
    connector, mock_client = _make_connector()
    mock_client.get_stress_data.return_value = {}

    result = connector.call("stress_level")

    assert result.ok is True
    assert result.data == -1


# ---------------------------------------------------------------------------
# Output shape — last_sleep
# ---------------------------------------------------------------------------


def test_last_sleep_output_keys():
    connector, mock_client = _make_connector()
    mock_client.get_sleep_data.return_value = {"dailySleepDTO": _RAW_SLEEP_DTO}

    result = connector.call("last_sleep")

    assert result.ok is True
    assert isinstance(result.data, dict)
    assert set(result.data.keys()) == _EXPECTED_SLEEP_KEYS


def test_last_sleep_values_are_hours():
    connector, mock_client = _make_connector()
    mock_client.get_sleep_data.return_value = {"dailySleepDTO": _RAW_SLEEP_DTO}

    result = connector.call("last_sleep")
    sleep = result.data

    assert sleep["total_sleep_h"] == pytest.approx(7.5, abs=0.01)
    assert sleep["deep_h"] == pytest.approx(1.5, abs=0.01)
    assert sleep["light_h"] == pytest.approx(4.0, abs=0.01)
    assert sleep["rem_h"] == pytest.approx(2.0, abs=0.01)
    assert sleep["score"] == 78


def test_last_sleep_none_when_no_sleep_seconds():
    connector, mock_client = _make_connector()
    mock_client.get_sleep_data.return_value = {"dailySleepDTO": {}}

    result = connector.call("last_sleep")

    assert result.ok is True
    assert result.data["total_sleep_h"] is None
    assert result.data["score"] is None


# ---------------------------------------------------------------------------
# Output shape — last_activity
# ---------------------------------------------------------------------------


def test_last_activity_output_keys():
    connector, mock_client = _make_connector()
    mock_client.get_activities.return_value = [_RAW_ACTIVITY]

    result = connector.call("last_activity")

    assert result.ok is True
    assert isinstance(result.data, dict)
    assert set(result.data.keys()) == _EXPECTED_ACTIVITY_KEYS


def test_last_activity_duration_is_minutes():
    connector, mock_client = _make_connector()
    mock_client.get_activities.return_value = [_RAW_ACTIVITY]

    result = connector.call("last_activity")

    assert result.data["duration_min"] == pytest.approx(50.0, abs=0.1)


def test_last_activity_distance_is_km():
    connector, mock_client = _make_connector()
    mock_client.get_activities.return_value = [_RAW_ACTIVITY]

    result = connector.call("last_activity")

    assert result.data["distance_km"] == pytest.approx(8.5, abs=0.01)


def test_last_activity_empty_dict_when_no_activities():
    connector, mock_client = _make_connector()
    mock_client.get_activities.return_value = []

    result = connector.call("last_activity")

    assert result.ok is True
    assert result.data == {}


# ---------------------------------------------------------------------------
# Output shape — heart_rate_history
# ---------------------------------------------------------------------------


def test_heart_rate_history_entry_shape():
    connector, mock_client = _make_connector()
    mock_client.get_heart_rates.return_value = {
        "heartRateValues": [
            [1718350000000, 72],
            [1718350060000, 75],
        ]
    }

    result = connector.call("heart_rate_history")

    assert result.ok is True
    assert isinstance(result.data, list)
    assert len(result.data) == 2
    for entry in result.data:
        assert set(entry.keys()) == _EXPECTED_HR_ENTRY_KEYS
        assert isinstance(entry["timestamp_ms"], int)
        assert isinstance(entry["bpm"], int)


def test_heart_rate_history_filters_null_bpm():
    connector, mock_client = _make_connector()
    mock_client.get_heart_rates.return_value = {
        "heartRateValues": [
            [1718350000000, 72],
            [1718350060000, None],  # null bpm — must be excluded
        ]
    }

    result = connector.call("heart_rate_history")

    assert result.ok is True
    assert len(result.data) == 1
    assert result.data[0]["bpm"] == 72


def test_heart_rate_history_empty_when_no_data():
    connector, mock_client = _make_connector()
    mock_client.get_heart_rates.return_value = {}

    result = connector.call("heart_rate_history")

    assert result.ok is True
    assert result.data == []


# ---------------------------------------------------------------------------
# CAP-5: Validation — params
# ---------------------------------------------------------------------------


def test_heart_rate_history_hours_is_optional():
    connector, mock_client = _make_connector()
    mock_client.get_heart_rates.return_value = {"heartRateValues": []}

    result = connector.call("heart_rate_history")  # no params
    assert result.ok is True


# ---------------------------------------------------------------------------
# CAP-5: Error envelope
# ---------------------------------------------------------------------------


def test_steps_today_auth_error():
    connector, mock_client = _make_connector()
    mock_client.get_stats.side_effect = PermissionError

    result = connector.call("steps_today")

    assert result.ok is False
    assert result.error == "auth"


def test_steps_today_timeout_error():
    connector, mock_client = _make_connector()
    mock_client.get_stats.side_effect = TimeoutError

    result = connector.call("steps_today")

    assert result.ok is False
    assert result.error == "timeout"


def test_stress_level_auth_error():
    connector, mock_client = _make_connector()
    mock_client.get_stress_data.side_effect = PermissionError

    result = connector.call("stress_level")

    assert result.ok is False
    assert result.error == "auth"


def test_last_sleep_timeout_error():
    connector, mock_client = _make_connector()
    mock_client.get_sleep_data.side_effect = TimeoutError

    result = connector.call("last_sleep")

    assert result.ok is False
    assert result.error == "timeout"
