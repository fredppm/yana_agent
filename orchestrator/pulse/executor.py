"""
pulse/executor.py — execute a single Pulse task with retry/backoff.

Flow:
  1. Call connector (observe.source, observe.operation, observe.params)
  2. Process result according to deliver.action
  3. Write output to a YANA session via session_writer

Retry policy: up to 3 attempts with exponential backoff (1 min, 3 min, 9 min).
Final failure is written to the Pulse session as an error notification.
"""

from __future__ import annotations

import time

import errors
import output
from providers import call_llm

from .config_loader import PulseTask
from .session_writer import write_result

_MAX_RETRIES = 3
_BACKOFF_SECONDS = (60, 180, 540)  # 1 min → 3 min → 9 min


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def execute_task(task: PulseTask, registry: object) -> None:
    """
    Execute task with retry/backoff. Writes result or error to a YANA session.

    registry: ConnectorRegistry instance loaded with all connectors.
    """
    last_error: str = ""
    for attempt in range(_MAX_RETRIES):
        try:
            _run_once(task, registry)
            return
        except Exception as exc:
            last_error = str(exc)
            output.status(
                f"[pulse] '{task.name}' attempt {attempt + 1}/{_MAX_RETRIES} failed: {last_error}"
            )
            if attempt < _MAX_RETRIES - 1:
                wait = _BACKOFF_SECONDS[attempt]
                output.status(f"[pulse] retrying '{task.name}' in {wait}s")
                time.sleep(wait)

    msg = errors.e("PUL-001", task=task.name, retries=_MAX_RETRIES, error=last_error)
    output.status(f"[pulse] {msg}")
    write_result(task.name, msg, error=True)


# ---------------------------------------------------------------------------
# Internal execution
# ---------------------------------------------------------------------------


def _run_once(task: PulseTask, registry: object) -> None:
    """Single execution attempt — raises on any failure."""
    result = registry.call(task.observe.source, task.observe.operation, task.observe.params)  # type: ignore[union-attr]

    if not result.ok:
        raise RuntimeError(
            f"connector '{task.observe.source}'.{task.observe.operation} "
            f"error={result.error!r} detail={result.detail!r}"
        )

    action = task.deliver.action
    if action == "summarize":
        summary = _summarize(result.data, task.deliver.prompt, task.name)
        write_result(task.name, summary)
    elif action == "notify":
        write_result(task.name, _to_str(result.data))
    elif action == "store":
        _store(task.name, result.data)
    else:
        raise ValueError(errors.e("PUL-002", action=action))


def _summarize(data: object, prompt: str, task_name: str) -> str:
    data_str = _to_str(data)
    messages = [{"role": "user", "content": f"{prompt}\n\n---\n\n{data_str}"}]
    system = (
        f"You are YANA's Pulse summarization engine. Task: {task_name}. "
        "Be concise and useful. Respond in the same language as the user prompt."
    )
    return call_llm(messages=messages, system=system, task="pulse_scheduled", stream=False)


def _store(task_name: str, data: object) -> None:
    from datetime import datetime

    from core import sanctum_path

    store_dir = sanctum_path() / "pulse-store"
    store_dir.mkdir(exist_ok=True)
    fname = f"{task_name}-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
    (store_dir / fname).write_text(_to_str(data), encoding="utf-8")


def _to_str(data: object) -> str:
    return data if isinstance(data, str) else str(data)
