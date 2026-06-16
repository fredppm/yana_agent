"""
core.py — system prompt assembly and session persistence.

Reads SKILL.md + sanctum fields to build YANA's context.
Saves and loads session logs for continuity.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import errors

# ---------------------------------------------------------------------------
# Runtime state — set once at startup via set_runtime_profile()
# ---------------------------------------------------------------------------

_active_profile: str = ""

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


def sanctum_path() -> Path:
    """Return the runtime data directory (used by Pulse for tasks, store, inbox)."""
    p = _sanctum_root()
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_session_log(messages: list[dict], session_id: str) -> Path:
    """Save session messages — writes to PostgreSQL if a profile is active, always writes to file for Pulse."""
    import json as _json

    import store

    profile_id = get_active_profile()
    if profile_id:
        now = datetime.now().isoformat()
        preview = next((m["content"][:80] for m in messages if m.get("role") == "assistant"), "")
        store.create_session_sync(
            session_id, profile_id, now, preview, _json.dumps(messages, ensure_ascii=False)
        )

    sessions_dir = sanctum_path() / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"session-{session_id}.md"
    lines = [f"# Session {session_id}\n"]
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        lines.append(f"## {role}\n{content}\n")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_connector_manifest(registry) -> str:
    """Return lightweight connector manifest formatted as a system-prompt section."""
    try:
        entries = registry.lightweight_manifest()
    except Exception:
        return ""
    if not entries:
        return ""
    lines = [
        "---",
        "## Available Connectors",
        "",
        "> **CONNECTOR RULES — follow without exception:**",
        "> 1. To read data or take action in the real world, call the connector. Never simulate or assume the result.",
        "> 2. Never confirm that an operation succeeded without receiving `ok=True` from the connector call.",
        "> 3. For any scheduling, reminder, or autonomous task → call `pulse.create_task`. No exceptions.",
        "> 4. For one-time reminders use `mode=once` with `at=<ISO datetime>` (compute as now + delay). For recurring use `mode=fixed`.",
        "> 5. If a connector call fails, report the failure honestly. Do not pretend it worked.",
        "",
    ]
    for e in entries:
        owner_tag = f" [{e['owner']}]" if e.get("owner") else ""
        lines.append(f"- **{e['id']}**{owner_tag}: {e['description']}")
        if e.get("operations"):
            lines.append(f"  operations: {', '.join(e['operations'])}")
    return "\n".join(lines)


def load_system_prompt(
    voice_mode: bool = False,
    registry=None,
    _sanctum_fields: dict[str, str] | None = None,
) -> str:
    """
    Build the system prompt by concatenating SKILL.md + sanctum fields from PostgreSQL.

    _sanctum_fields: pre-loaded sanctum fields (avoids a second DB query when the
    caller already has them). If None, loads from PostgreSQL.
    """
    skill_md = _skill_root() / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found at {skill_md}")

    now = datetime.now()
    date_str = now.strftime("%A, %d %B %Y")
    time_str = now.strftime("%H:%M")
    parts: list[str] = [
        f"---\n## Context\n\nDate: {date_str}\nTime: {time_str}",
        f"---\n## SKILL\n\n{skill_md.read_text(encoding='utf-8')}",
    ]

    # Sanctum fields from PostgreSQL — in order, skip missing
    active = get_active_profile()
    if active:
        import store

        if _sanctum_fields is None:
            owner_id = owner_id_from_profile(active)
            fields = store.load_sanctum_fields_sync(owner_id, active)
        else:
            fields = _sanctum_fields
        field_order = [
            ("persona", "PERSONA"),
            ("creed", "CREED"),
            ("bond", "BOND"),
            ("capabilities", "CAPABILITIES"),
            ("pulse", "PULSE"),
        ]
        for prop, header in field_order:
            content = fields.get(prop)
            if content:
                parts.append(f"---\n## {header}\n\n{content}")
        pulse_config = fields.get("pulse_config")
        if pulse_config:
            parts.append(f"---\n## PULSE CONFIG\n\n```yaml\n{pulse_config}\n```")
    else:
        # No active profile — First Breath: inject the birth protocol
        first_breath_path = _skill_root() / "references" / "first-breath.md"
        if first_breath_path.exists():
            parts.append(f"---\n## FIRST BREATH\n\n{first_breath_path.read_text(encoding='utf-8')}")
        else:
            parts.append(f"---\n[{errors.e('SYS-001')}]")

    parts.append(
        f"---\n## Current datetime\n\n"
        f"{now.strftime('%Y-%m-%dT%H:%M:%S')} (local time, use this to compute `at` for Pulse once tasks)"
    )

    # Connector manifest — lightweight, always injected when registry is present
    if registry is not None:
        manifest_section = build_connector_manifest(registry)
        if manifest_section:
            parts.append(manifest_section)

    result = "\n\n".join(parts)

    if voice_mode:
        result += "\n\n---\n[VOICE MODE: Respond in plain spoken language only. No markdown, no bullet points, no headers.]"

    return result


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


def list_sessions(limit: int = 20) -> list[tuple[str, datetime, str]]:
    """List recent sessions as (session_id, datetime, preview), newest first."""
    import store

    active = get_active_profile()
    if not active:
        return []
    return store.list_sessions_sync(active, limit=limit)


def load_session_messages(session_id: str) -> list[dict]:
    """Load messages for a session from PostgreSQL."""
    import store

    return store.load_session_messages_sync(session_id)


# ---------------------------------------------------------------------------
# Profile identity helpers
# ---------------------------------------------------------------------------


def owner_id_from_profile(profile_id: str) -> str:
    """Return the owner UUID for a given profile UUID."""
    import store

    return store.get_owner_id_for_profile_sync(profile_id) or ""


# ---------------------------------------------------------------------------
# Pulse-config helpers
# ---------------------------------------------------------------------------


def load_pulse_config() -> dict:
    """Load pulse config from PostgreSQL profile context."""
    import store
    import yaml

    active = get_active_profile()
    if not active:
        return {}
    owner_id = owner_id_from_profile(active)
    fields = store.load_sanctum_fields_sync(owner_id, active)
    raw = fields.get("pulse_config", "")
    if not raw:
        return {}
    try:
        return yaml.safe_load(raw) or {}
    except Exception:
        return {}


def list_profiles() -> list[dict]:
    """Return configured profiles [{id, label}, ...] from PostgreSQL."""
    import store

    return store.list_profiles_sync()


def get_active_profile() -> str:
    """Return the runtime-selected profile id (set at startup via set_runtime_profile)."""
    return _active_profile


def set_runtime_profile(profile_id: str) -> None:
    """Set the active profile for this process. Called once at startup after profile selection."""
    global _active_profile
    _active_profile = profile_id


def create_first_owner_and_profile(written: dict[str, str]) -> tuple[str, str]:
    """First Breath: create Owner + Profile from sanctum output.

    Returns (owner_id, profile_id).
    """
    import store

    name = (written.get("OWNER_NAME") or "").strip() or "User"
    owner_id = store.add_owner_sync(name)
    profile_id = store.add_profile_sync(owner_id, f"{name} — Default")
    return owner_id, profile_id


_PROFILE_LIMIT = 5


def add_profile(label: str) -> str:
    """Create a new profile under the active owner. Returns new profile UUID.
    Raises ValueError if the owner already has _PROFILE_LIMIT profiles.
    """
    import store

    existing = store.list_profiles_sync()
    if len(existing) >= _PROFILE_LIMIT:
        raise ValueError(f"Profile limit reached ({_PROFILE_LIMIT} max)")

    active = get_active_profile()
    owner_id = owner_id_from_profile(active) if active else ""
    profile_id = store.add_profile_sync(owner_id, label)
    set_runtime_profile(profile_id)
    return profile_id


def delete_profile(profile_id: str) -> None:
    """Remove a profile from PostgreSQL. Clears runtime profile if it was the active one."""
    import store

    store.delete_profile_sync(profile_id)
    if get_active_profile() == profile_id:
        remaining = list_profiles()
        set_runtime_profile(remaining[0]["id"] if remaining else "")


def rename_profile_label(profile_id: str, new_label: str) -> None:
    """Update the display label for a profile in PostgreSQL."""
    import store

    store.update_profile_label_sync(profile_id, new_label)


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
