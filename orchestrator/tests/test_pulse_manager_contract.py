"""
Tests for connectors/pulse_manager.py — connector contract and HTTP behaviour.
All network calls are mocked; no real Pulse daemon required.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_CONNECTOR_FILE = Path(__file__).parent.parent.parent / "connectors" / "pulse_manager.py"
_spec = importlib.util.spec_from_file_location("pulse_manager", _CONNECTOR_FILE)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
sys.modules["pulse_manager"] = _mod  # required for patch("pulse_manager.urlopen") to resolve

PulseManagerConnector = _mod.PulseManagerConnector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(body: dict, status: int = 200):
    raw = json.dumps(body).encode()
    resp = MagicMock()
    resp.read.return_value = raw
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_connector_description():
    c = PulseManagerConnector()
    assert "Pulse" in c.connector_description


def test_connector_has_expected_operations():
    c = PulseManagerConnector()
    ops = set(c._operations.keys())
    assert ops >= {"list_tasks", "health", "create_task", "remove_task"}


def test_list_tasks_is_query():
    c = PulseManagerConnector()
    assert c._operations["list_tasks"].kind == "query"


def test_create_task_is_command():
    c = PulseManagerConnector()
    assert c._operations["create_task"].kind == "command"


def test_remove_task_is_command():
    c = PulseManagerConnector()
    assert c._operations["remove_task"].kind == "command"


# ---------------------------------------------------------------------------
# list_tasks
# ---------------------------------------------------------------------------


def test_list_tasks_returns_list(tmp_path):
    tasks = [{"name": "newsletters", "observe": {}, "schedule": {}, "deliver": {}}]
    with patch("pulse_manager.urlopen", return_value=_mock_response({"tasks": tasks})):
        c = PulseManagerConnector()
        result = c.call("list_tasks", {})
    assert result.ok is True
    assert result.data == tasks


def test_list_tasks_empty(tmp_path):
    with patch("pulse_manager.urlopen", return_value=_mock_response({"tasks": []})):
        c = PulseManagerConnector()
        result = c.call("list_tasks", {})
    assert result.ok is True
    assert result.data == []


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


def test_health_ok():
    with patch("pulse_manager.urlopen", return_value=_mock_response({"status": "ok", "jobs": 2})):
        c = PulseManagerConnector()
        result = c.call("health", {})
    assert result.ok is True
    assert result.data["status"] == "ok"


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------


def test_create_task_posts_correct_payload():
    with patch("pulse_manager.urlopen", return_value=_mock_response({"ok": True, "name": "newsletters"}, 201)) as mock_open:
        c = PulseManagerConnector()
        result = c.call("create_task", {
            "name": "newsletters",
            "source": "gmail_fred_personal",
            "operation": "search",
            "params": {"query": "category:promotions is:unread"},
            "time": "10:00",
            "days": "daily",
            "action": "summarize",
            "prompt": "Summarize in PT-BR",
        })

    assert result.ok is True
    # Verify the request body
    req = mock_open.call_args[0][0]
    body = json.loads(req.data)
    assert body["name"] == "newsletters"
    assert body["observe"]["source"] == "gmail_fred_personal"
    assert body["observe"]["operation"] == "search"
    assert body["schedule"]["time"] == "10:00"
    assert body["deliver"]["action"] == "summarize"


def test_create_task_defaults_days_and_prompt():
    with patch("pulse_manager.urlopen", return_value=_mock_response({"ok": True, "name": "x"}, 201)) as mock_open:
        c = PulseManagerConnector()
        c.call("create_task", {
            "name": "x",
            "source": "garmin_fred",
            "operation": "activities",
            "time": "08:00",
            "action": "notify",
        })
    body = json.loads(mock_open.call_args[0][0].data)
    assert body["schedule"]["days"] == "daily"
    assert body["deliver"]["prompt"] == ""


# ---------------------------------------------------------------------------
# remove_task
# ---------------------------------------------------------------------------


def test_remove_task_sends_delete():
    with patch("pulse_manager.urlopen", return_value=_mock_response({"ok": True, "name": "newsletters"})) as mock_open:
        c = PulseManagerConnector()
        result = c.call("remove_task", {"name": "newsletters"})

    assert result.ok is True
    req = mock_open.call_args[0][0]
    assert req.method == "DELETE"
    assert "/tasks/newsletters" in req.full_url


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_connection_error_propagates():
    from urllib.error import URLError

    with patch("pulse_manager.urlopen", side_effect=URLError("connection refused")):
        c = PulseManagerConnector()
        result = c.call("list_tasks", {})
    assert result.ok is False
    assert "not reachable" in (result.error or "")
