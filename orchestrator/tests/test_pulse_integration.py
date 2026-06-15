"""
Integration test for the Pulse pipeline.

Spins up a real PulseAPI HTTP server (on a random port), creates a task via
POST /tasks, then triggers immediate execution via POST /tasks/{name}/run.
Asserts that a session file is written to the (temp) sanctum.

No Gmail, no LLM — connector and LLM are replaced with lightweight fakes.
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Path setup — mirrors other test files in this suite
# ---------------------------------------------------------------------------
import sys
import threading
import time
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.request import Request, urlopen

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pulse.api import PulseAPI
from pulse.config_loader import load_tasks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(url: str, body: dict, expect_status: int = 200) -> dict:
    data = json.dumps(body).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=5) as resp:
        assert resp.status == expect_status, f"expected {expect_status}, got {resp.status}"
        return json.loads(resp.read())


def _get(url: str) -> dict:
    with urlopen(url, timeout=5) as resp:
        return json.loads(resp.read())


def _task_payload(name: str = "test-newsletter") -> dict:
    return {
        "name": name,
        "observe": {
            "source": "gmail_fred_personal",
            "operation": "search",
            "params": {"query": "category:promotions is:unread"},
        },
        "schedule": {"mode": "fixed", "time": "10:00", "days": "daily"},
        "deliver": {"action": "notify", "prompt": ""},
    }


# ---------------------------------------------------------------------------
# Fixture — live PulseAPI server
# ---------------------------------------------------------------------------


@pytest.fixture()
def pulse_server(tmp_path):
    """
    Starts a real PulseAPI on a random port with:
      - a temp tasks file
      - a mock scheduler (no APScheduler needed)
      - a mock connector registry that returns fake data
    Yields (base_url, tasks_file, sanctum_dir).
    """
    tasks_file = tmp_path / "pulse-tasks.yaml"
    sanctum_dir = tmp_path / "sanctum"
    sanctum_dir.mkdir()

    # Mock scheduler — only needs get_jobs() for /health
    scheduler = MagicMock()
    scheduler.get_jobs.return_value = []

    # Mock registry — returns a successful result with fake content
    registry = MagicMock()
    result = MagicMock(ok=True, data="Fake email content for testing", error=None, detail=None)
    registry.call.return_value = result

    port = _free_port()
    api = PulseAPI(
        tasks_file=tasks_file,
        scheduler=scheduler,
        registry=registry,
        host="127.0.0.1",
        port=port,
    )
    t = threading.Thread(target=api.serve_forever, daemon=True)
    t.start()

    # Poll until the server is accepting connections (handles slow CI runners)
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            urlopen(f"{base}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError(f"Pulse API did not start on port {port}")
    yield base, tasks_file, sanctum_dir, registry

    api.shutdown()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health(pulse_server):
    base, *_ = pulse_server
    resp = _get(f"{base}/health")
    assert resp["status"] == "ok"


def test_create_and_list_task(pulse_server):
    base, tasks_file, *_ = pulse_server
    resp = _post(f"{base}/tasks", _task_payload(), expect_status=201)
    assert resp["ok"] is True
    assert resp["name"] == "test-newsletter"

    tasks = load_tasks(tasks_file)
    assert len(tasks) == 1
    assert tasks[0].name == "test-newsletter"

    listed = _get(f"{base}/tasks")
    assert len(listed["tasks"]) == 1


def test_run_endpoint_calls_connector_and_writes_session(pulse_server, tmp_path):
    base, _tasks_file, sanctum_dir, registry = pulse_server

    # Create the task first
    _post(f"{base}/tasks", _task_payload("newsletters"), expect_status=201)

    sessions_dir = sanctum_dir / "sessions"

    with patch("core._sanctum_root", return_value=sanctum_dir):
        resp = _post(f"{base}/tasks/newsletters/run", {})

    assert resp["ok"] is True

    # Connector was called with the right args
    registry.call.assert_called_once_with(
        "gmail_fred_personal", "search", {"query": "category:promotions is:unread"}
    )

    # Session file was written
    session_files = list(sessions_dir.glob("session-pulse-newsletters-*.md"))
    assert len(session_files) == 1
    content = session_files[0].read_text()
    assert "PULSE: newsletters" in content
    assert "Fake email content for testing" in content


def test_run_endpoint_unknown_task_returns_404(pulse_server):
    base, *_ = pulse_server
    with pytest.raises(urllib.error.HTTPError):  # urlopen raises on 4xx
        _post(f"{base}/tasks/nonexistent/run", {})


def test_delete_task(pulse_server):
    base, tasks_file, *_ = pulse_server
    _post(f"{base}/tasks", _task_payload(), expect_status=201)

    req = Request(f"{base}/tasks/test-newsletter", method="DELETE")
    with urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read())
    assert body["ok"] is True

    assert load_tasks(tasks_file) == []
