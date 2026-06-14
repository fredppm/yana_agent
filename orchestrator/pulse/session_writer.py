"""
pulse/session_writer.py — write Pulse task results to YANA sessions.

Writes directly to data/agent-yana/sessions/ by calling save_session_log()
from core.py. The only import from the YANA codebase is core — no voice,
no providers, no main runtime.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core import save_session_log


def write_result(task_name: str, content: str, error: bool = False) -> Path:
    """
    Persist a Pulse task result as a YANA session file.

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
    return save_session_log(messages, session_id=session_id)
