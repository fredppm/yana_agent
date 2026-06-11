"""
core.py — system prompt assembly and session persistence.

Reads SKILL.md + sanctum files to build YANA's context.
Saves and loads session logs for continuity.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Resolve project root: two levels up from this file (orchestrator/)."""
    return Path(__file__).parent.parent


def _skill_root() -> Path:
    return _project_root() / "skills" / "agent-yana"


def _sanctum_root() -> Path:
    return _project_root() / "_bmad" / "memory" / "agent-yana"


def _sessions_dir() -> Path:
    sessions = _sanctum_root() / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    return sessions


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------

_SANCTUM_FILES = [
    "PERSONA.md",
    "CREED.md",
    "BOND.md",
    "MEMORY.md",
    "CAPABILITIES.md",
    "PULSE.md",
]


def load_system_prompt() -> str:
    """
    Build the system prompt by concatenating SKILL.md + sanctum files.

    If sanctum doesn't exist yet, returns only SKILL.md so the orchestrator
    can still start and trigger First Breath.
    """
    parts: list[str] = []

    # 1. SKILL.md — identity seed
    skill_md = _skill_root() / "SKILL.md"
    if skill_md.exists():
        parts.append(_read_file(skill_md, "SKILL.md"))
    else:
        raise FileNotFoundError(f"SKILL.md not found at {skill_md}")

    # 2. Sanctum files — in order, skip missing
    sanctum = _sanctum_root()
    if sanctum.exists():
        for fname in _SANCTUM_FILES:
            fpath = sanctum / fname
            if fpath.exists():
                parts.append(_read_file(fpath, fname))
    else:
        # No sanctum yet — First Breath hasn't happened
        parts.append(
            "\n\n---\n[SANCTUM NOT FOUND — First Breath required before proceeding.]\n"
        )

    # 3. pulse-config.yaml as raw text (YANA reads it for PULSE tasks)
    pulse_cfg = sanctum / "pulse-config.yaml"
    if pulse_cfg.exists():
        parts.append(f"\n\n---\n## pulse-config.yaml\n\n```yaml\n{pulse_cfg.read_text(encoding='utf-8')}\n```\n")

    return "\n\n".join(parts)


def _read_file(path: Path, label: str) -> str:
    content = path.read_text(encoding="utf-8")
    return f"---\n## {label}\n\n{content}"


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def load_recent_sessions(n: int = 3) -> str:
    """Return the last n session logs concatenated, or empty string."""
    sessions_dir = _sessions_dir()
    logs = sorted(sessions_dir.glob("session-*.md"), reverse=True)[:n]
    if not logs:
        return ""
    parts = ["---\n## Recent Session Logs\n"]
    for log in reversed(logs):  # oldest first
        parts.append(f"### {log.name}\n\n{log.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def save_session_log(messages: list[dict], session_id: Optional[str] = None) -> Path:
    """
    Persist the conversation to a session log file.

    messages: list of {role, content} dicts
    Returns the path written.
    """
    if session_id is None:
        session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    filename = f"session-{session_id}.md"
    path = _sessions_dir() / filename

    lines = [f"# Session {session_id}\n"]
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        lines.append(f"## {role}\n\n{content}\n")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Sanctum state check
# ---------------------------------------------------------------------------

def sanctum_exists() -> bool:
    """True if the sanctum has been initialised (PERSONA.md present)."""
    return (_sanctum_root() / "PERSONA.md").exists()


def sanctum_path() -> Path:
    return _sanctum_root()


# ---------------------------------------------------------------------------
# Pulse-config helpers
# ---------------------------------------------------------------------------

def load_pulse_config() -> dict:
    """Load pulse-config.yaml from the sanctum. Returns empty dict if missing."""
    try:
        import yaml
    except ImportError:
        return {}

    cfg_path = _sanctum_root() / "pulse-config.yaml"
    if not cfg_path.exists():
        return {}
    with cfg_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def is_quiet_hours(pulse_config: Optional[dict] = None) -> bool:
    """Return True if current local time falls in the configured quiet window."""
    if pulse_config is None:
        pulse_config = load_pulse_config()

    quiet = pulse_config.get("quiet_hours", "23:00-07:00")
    try:
        start_str, end_str = quiet.split("-")
        now = datetime.now().time()
        start = datetime.strptime(start_str.strip(), "%H:%M").time()
        end = datetime.strptime(end_str.strip(), "%H:%M").time()
        if start <= end:
            return start <= now <= end
        # Overnight window (e.g. 23:00–07:00)
        return now >= start or now <= end
    except (ValueError, AttributeError):
        return False
