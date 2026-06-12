"""
Integration tests for GarminActivityConnector.

These tests hit the real Garmin Connect API. They require a garth token
directory at ~/.yana/tokens/garmin_fred (created on first login).

First-time setup:
    GARMIN_EMAIL=you@example.com GARMIN_PASSWORD=secret \
        python -c "
    import sys; sys.path.insert(0, 'orchestrator')
    from connectors.garmin import GarminActivityConnector
    c = GarminActivityConnector(token_dir='~/.yana/tokens/garmin_fred')
    c._svc()  # triggers login + token save
    print('tokens saved')
    "

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
def test_steps_today_returns_int(registry):
    result = registry.call("garmin_fred", "steps_today")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, int)
    assert result.data >= 0


@pytest.mark.integration
def test_calories_today_returns_int(registry):
    result = registry.call("garmin_fred", "calories_today")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, int)
    assert result.data >= 0


@pytest.mark.integration
def test_stress_level_returns_int(registry):
    result = registry.call("garmin_fred", "stress_level")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, int)
    assert result.data >= -1  # -1 means no data yet


@pytest.mark.integration
def test_last_sleep_returns_dict_with_known_keys(registry):
    result = registry.call("garmin_fred", "last_sleep")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, dict)
    # keys present even when None
    for key in ("total_sleep_h", "deep_h", "light_h", "rem_h"):
        assert key in result.data


@pytest.mark.integration
def test_last_activity_returns_dict(registry):
    result = registry.call("garmin_fred", "last_activity")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, dict)
    if result.data:  # may be empty if no activity recorded
        assert "id" in result.data
        assert "type" in result.data


@pytest.mark.integration
def test_heart_rate_history_returns_list(registry):
    result = registry.call("garmin_fred", "heart_rate_history")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)
    for entry in result.data:
        assert "timestamp_ms" in entry
        assert "bpm" in entry


@pytest.mark.integration
def test_get_connector_contract_has_all_queries(registry):
    contract = registry.load_contract("garmin_fred")
    assert "queries" in contract
    query_names = {q["name"] for q in contract["queries"]}
    assert "steps_today" in query_names
    assert "calories_today" in query_names
    assert "stress_level" in query_names
    assert "last_sleep" in query_names
    assert "last_activity" in query_names
    assert "heart_rate_history" in query_names
