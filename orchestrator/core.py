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


def build_connector_manifest(registry) -> str:
    """Return lightweight connector manifest formatted as a system-prompt section."""
    try:
        entries = registry.lightweight_manifest()
    except Exception:
        return ""
    if not entries:
        return ""
    lines = ["---", "## Available Connectors", ""]
    for e in entries:
        owner_tag = f" [{e['owner']}]" if e.get("owner") else ""
        lines.append(f"- **{e['id']}**{owner_tag}: {e['description']}")
        if e.get("operations"):
            lines.append(f"  operations: {', '.join(e['operations'])}")
    return "\n".join(lines)


def _read_file(path: Path, name: str) -> str:
    return f"---\n## {name}\n\n{path.read_text(encoding='utf-8')}"


def load_system_prompt(voice_mode: bool = False, registry=None) -> str:
    """
    Build the system prompt by concatenating SKILL.md + sanctum files.

    If sanctum doesn't exist yet, returns only SKILL.md so the orchestrator
    can still start and trigger First Breath.

    voice_mode=True appends a no-markdown instruction.
    registry: if provided, injects the lightweight connector manifest.
    """
    skill_md = _skill_root() / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found at {skill_md}")

    parts: list[str] = [_read_file(skill_md, "SKILL.md")]

    # Sanctum files — in order, skip missing
    sanctum = _sanctum_root()
    if sanctum.exists():
        for fname in _SANCTUM_FILES:
            fpath = sanctum / fname
            if fpath.exists():
                parts.append(_read_file(fpath, fname))
        # pulse-config.yaml as raw text (YANA reads it for PULSE tasks)
        pulse_cfg = sanctum / "pulse-config.yaml"
        if pulse_cfg.exists():
            parts.append(
                f"---\n## pulse-config.yaml\n\n```yaml\n{pulse_cfg.read_text(encoding='utf-8')}\n```"
            )
    else:
        # No sanctum yet — First Breath hasn't happened
        parts.append(f"---\n[{errors.e('SYS-001')}]")

    # Connector manifest — lightweight, always injected when registry is present
    if registry is not None:
        manifest_section = build_connector_manifest(registry)
        if manifest_section:
            parts.append(manifest_section)
            parts.append(
                "---\n"
                "## Connector Auth Flow\n\n"
                "When a connector call returns `{\"ok\": false, \"error\": \"auth\"}` or `\"error\": \"unavailable\"`:\n"
                "1. Check if the connector entry in the manifest has a `credential_hint` — it tells you exactly what credentials are needed and how to get them.\n"
                "2. Explain conversationally to Fred what's needed, why, and how to get it (keep it friendly, concise).\n"
                "3. Ask Fred to provide the credentials (or run the setup command if needed).\n"
                "4. Once Fred provides them, call `save_credentials` with `instance_id` and the credentials as a JSON object.\n"
                "5. Immediately retry the original connector call — the connector reloads credentials automatically.\n"
                "Do NOT ask Fred to manually edit files or run complex scripts unless the credential_hint explicitly says so."
            )

    result = "\n\n".join(parts)

    if voice_mode:
        result += "\n\n---\n[VOICE MODE: Respond in plain spoken language only. No markdown, no bullet points, no headers.]"

    return result


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


def save_session_log(messages: list[dict], session_id: str | None = None) -> Path:
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
    lines += [f"## {m['role'].upper()}\n\n{m['content']}\n" for m in messages]
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
    """Load pulse-config.yaml from the sanctum. Returns empty dict if missing or invalid."""
    import yaml

    cfg_path = _sanctum_root() / "pulse-config.yaml"
    if not cfg_path.exists():
        return {}
    try:
        return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def is_quiet_hours(pulse_config: dict | None = None) -> bool:
    """Return True if current local time falls in the configured quiet window."""
    if pulse_config is None:
        pulse_config = load_pulse_config()

    quiet = pulse_config.get("quiet_hours", "23:00-07:00")
    try:
        start_str, end_str = quiet.split("-", 1)
        now = datetime.now().time()
        start = datetime.strptime(start_str.strip(), "%H:%M").time()
        end = datetime.strptime(end_str.strip(), "%H:%M").time()
        if start <= end:
            return start <= now <= end
        # Overnight window (e.g. 23:00-07:00)
        return now >= start or now <= end
    except (ValueError, AttributeError):
        return False
