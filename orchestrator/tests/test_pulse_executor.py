"""
Tests for pulse/executor.py — all external calls (connector, LLM, sleep) are mocked.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from pulse.config_loader import (
    DeliverConfig,
    ObserveConfig,
    PulseTask,
    ScheduleConfig,
)
from pulse.executor import _MAX_RETRIES, _BACKOFF_SECONDS, execute_task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task(action: str = "summarize", prompt: str = "Summarize") -> PulseTask:
    return PulseTask(
        name="test-task",
        observe=ObserveConfig(source="gmail_fred", operation="search", params={"query": "newsletters"}),
        schedule=ScheduleConfig(mode="fixed", time="10:00", days="daily"),
        deliver=DeliverConfig(action=action, prompt=prompt),
    )


def _registry(ok: bool = True, data: object = "raw data", error: str | None = None):
    reg = MagicMock()
    result = MagicMock()
    result.ok = ok
    result.data = data
    result.error = error
    result.detail = None
    reg.call.return_value = result
    return reg


# ---------------------------------------------------------------------------
# Successful execution paths
# ---------------------------------------------------------------------------


def test_execute_summarize_success(tmp_path):
    reg = _registry(data="email content here")
    with (
        patch("pulse.executor.call_llm", return_value="summary text") as mock_llm,
        patch("pulse.executor.write_result") as mock_write,
    ):
        execute_task(_task("summarize", "Summarize in PT-BR"), reg)

    reg.call.assert_called_once_with("gmail_fred", "search", {"query": "newsletters"})
    mock_llm.assert_called_once()
    _, kwargs = mock_llm.call_args
    assert kwargs["task"] == "pulse_scheduled"
    assert "Summarize in PT-BR" in kwargs["messages"][0]["content"]
    mock_write.assert_called_once_with("test-task", "summary text")


def test_execute_notify_success():
    reg = _registry(data="sensor triggered")
    with patch("pulse.executor.write_result") as mock_write:
        execute_task(_task("notify"), reg)
    mock_write.assert_called_once_with("test-task", "sensor triggered")


def test_execute_store_success(tmp_path):
    reg = _registry(data="raw payload")
    with patch("pulse.executor._store") as mock_store:
        execute_task(_task("store"), reg)
    mock_store.assert_called_once_with("test-task", "raw payload")


# ---------------------------------------------------------------------------
# Connector failure and retry
# ---------------------------------------------------------------------------


def test_connector_error_triggers_retry_then_error_session():
    reg = _registry(ok=False, error="timeout")

    with (
        patch("pulse.executor.write_result") as mock_write,
        patch("pulse.executor.time.sleep") as mock_sleep,
    ):
        execute_task(_task(), reg)

    # Connector called _MAX_RETRIES times
    assert reg.call.call_count == _MAX_RETRIES

    # Slept between retries (one fewer sleep than retries)
    assert mock_sleep.call_count == _MAX_RETRIES - 1
    mock_sleep.assert_has_calls([call(_BACKOFF_SECONDS[0]), call(_BACKOFF_SECONDS[1])])

    # Error session written once after exhausting retries
    mock_write.assert_called_once()
    _, kwargs = mock_write.call_args
    assert kwargs.get("error") is True or mock_write.call_args[0][2] is True


def test_llm_error_triggers_retry():
    reg = _registry(data="content")

    with (
        patch("pulse.executor.call_llm", side_effect=RuntimeError("LLM down")),
        patch("pulse.executor.write_result") as mock_write,
        patch("pulse.executor.time.sleep"),
    ):
        execute_task(_task("summarize"), reg)

    # Error session written
    mock_write.assert_called_once()
    args = mock_write.call_args[0]
    assert "LLM down" in args[1]


def test_success_on_second_attempt():
    reg = MagicMock()
    fail_result = MagicMock(ok=False, error="timeout", detail=None)
    ok_result = MagicMock(ok=True, data="content", detail=None)
    reg.call.side_effect = [fail_result, ok_result]

    with (
        patch("pulse.executor.call_llm", return_value="summary"),
        patch("pulse.executor.write_result") as mock_write,
        patch("pulse.executor.time.sleep"),
    ):
        execute_task(_task("summarize"), reg)

    # Only result (not error) written
    mock_write.assert_called_once_with("test-task", "summary")
