"""
core.py — system prompt assembly and session persistence.

Reads SKILL.md + sanctum files to build YANA's context.
Saves and loads session logs for continuity.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import errors

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """Resolve project root: two levels up from this file (orchestrator/)."""
    return Path(__file__).parent.parent


def _skill_root() -> Path:
    return _project_root() / "skills" / "agent-yana"


def _sanctum_root() -> Path:
    return _project_root() / "data" / "agent-yana"


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
    """Build the system prompt: SKILL.md + sanctum files (skips missing)."""
    skill_md = _skill_root() / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found at {skill_md}")

    def _section(path: Path) -> str:
        return f"---\n## {path.name}\n\n{path.read_text(encoding='utf-8')}"

    sanctum = _sanctum_root()
    parts = [_section(skill_md)]

    if sanctum.exists():
        parts += [_section(sanctum / f) for f in _SANCTUM_FILES if (sanctum / f).exists()]
        pulse_cfg = sanctum / "pulse-config.yaml"
        if pulse_cfg.exists():
            parts.append(
                f"---\n## pulse-config.yaml\n\n```yaml\n{pulse_cfg.read_text(encoding='utf-8')}\n```"
            )
    else:
        parts.append(f"---\n[{errors.e('SYS-001')}]")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


def save_session_log(messages: list[dict], session_id: str) -> None:
    """Persist the conversation to data/agent-yana/sessions/session-{id}.md."""
    path = _sessions_dir() / f"session-{session_id}.md"
    lines = [f"# Session {session_id}\n"]
    lines += [f"## {m['role'].upper()}\n\n{m['content']}\n" for m in messages]
    path.write_text("\n".join(lines), encoding="utf-8")


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
    """Load pulse-config.yaml from the sanctum. Returns empty dict if missing or invalid."""
    import yaml

    cfg_path = _sanctum_root() / "pulse-config.yaml"
    if not cfg_path.exists():
        return {}
    try:
        return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def is_quiet_hours() -> bool:
    """Return True if current local time falls in the configured quiet window."""
    quiet = load_pulse_config().get("quiet_hours", "23:00-07:00")
    try:
        start_str, end_str = quiet.split("-", 1)
        now = datetime.now().time()
        start = datetime.strptime(start_str.strip(), "%H:%M").time()
        end = datetime.strptime(end_str.strip(), "%H:%M").time()
        if start <= end:
            return start <= now <= end
        return now >= start or now <= end  # overnight window e.g. 23:00-07:00
    except (ValueError, AttributeError):
        return False
