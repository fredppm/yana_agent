"""
pulse/session_writer.py — write Pulse task results to YANA sessions.

Writes directly to data/agent-yana/sessions/ by calling save_session_log()
from core.py. Also writes to pulse-inbox.json so the running YANA TUI can
display notifications in real-time (polled every 2 s by the TUI timer).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from core import sanctum_path, save_session_log


def write_result(task_name: str, content: str, error: bool = False) -> Path:
    """
    Persist a Pulse task result as a YANA session file and queue a live
    TUI notification via pulse-inbox.json.

    Returns the path of the written session file.
    The session enters the normal history and feeds the sanctum on next YANA run.
    """
    session_id = f"pulse-{task_name}-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    role = "assistant" if not error else "system"
    messages: list[dict] = [
        {
            "role": role,
            "content": f"[PULSE: {task_name}]\n\n{content}",
        }
    ]
    session_path = save_session_log(messages, session_id=session_id)
    _write_inbox(task_name, content)
    return session_path


def _write_inbox(task_name: str, content: str) -> None:
    """Append a notification entry to pulse-inbox.json (atomic write)."""
    inbox_path = sanctum_path() / "pulse-inbox.json"
    entries: list[dict] = []
    if inbox_path.exists():
        try:
            raw = json.loads(inbox_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                entries = raw
        except (json.JSONDecodeError, OSError):
            pass
    entries.append({
        "task": task_name,
        "content": content,
        "ts": datetime.now().isoformat(timespec="seconds"),
    })
    tmp = inbox_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries), encoding="utf-8")
    os.replace(tmp, inbox_path)
