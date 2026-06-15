"""
core.py — system prompt assembly and session persistence.

Reads SKILL.md + sanctum files to build YANA's context.
Saves and loads session logs for continuity.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import errors

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """
    Resolve project root: two levels up from this file (orchestrator/).

    In a git worktree the working tree is isolated but data/ is gitignored and
    lives only in the main worktree. Detect this case by reading the .git file
    and following commondir to the main repo root.
    """
    here = Path(__file__).parent.parent
    git_entry = here / ".git"
    if git_entry.is_file():
        # Worktree: .git is a file with "gitdir: <path>"
        line = git_entry.read_text(encoding="utf-8").strip()
        if line.startswith("gitdir:"):
            gitdir = Path(line[7:].strip())
            common_file = gitdir / "commondir"
            if common_file.exists():
                common_rel = common_file.read_text(encoding="utf-8").strip()
                common_git = (gitdir / common_rel).resolve()
                return common_git.parent  # main repo root
    return here


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

    # Episodic memory from Graphiti — injected when available
    try:
        import memory as mem

        graphiti_ctx = mem.load_context_sync()
        if graphiti_ctx:
            parts.append(graphiti_ctx)
    except Exception:
        pass  # graceful fallback — never block session start

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


def _session_preview(path: Path, max_chars: int = 48) -> str:
    """Return first user message snippet from a session file."""
    import re

    try:
        text = path.read_text(encoding="utf-8")
        m = re.search(r"\n## USER\n\n(.+)", text)
        if m:
            snippet = m.group(1).strip()[:max_chars].replace("\n", " ")
            return snippet
    except OSError:
        pass
    return ""


def list_sessions(limit: int = 20) -> list[tuple[str, datetime, str]]:
    """List recent sessions as (session_id, datetime, preview), newest first."""
    import memory as mem

    active = get_active_profile()
    if active:
        result = mem.list_sessions_sync(active, limit=limit)
        if result:
            return result
    # fallback: .md files (migration path for pre-Neo4j sessions)
    sessions_dir = _sessions_dir()
    result = []
    for f in sorted(sessions_dir.glob("session-*.md"), reverse=True)[:limit]:
        sid = f.stem[8:]  # strip "session-"
        try:
            dt = datetime.strptime(sid, "%Y-%m-%d_%H-%M-%S")
        except ValueError:
            dt = datetime.fromtimestamp(f.stat().st_mtime)
        result.append((sid, dt, _session_preview(f)))
    return result


def load_session_messages(session_id: str) -> list[dict]:
    """Load messages from a saved session file into a list of role/content dicts."""
    import re

    import memory as mem

    msgs = mem.load_session_messages_sync(session_id)
    if msgs:
        return msgs
    # fallback: .md parsing (migration path for pre-Neo4j sessions)
    path = _sessions_dir() / f"session-{session_id}.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    messages = []
    parts = re.split(r"\n## (USER|ASSISTANT)\n\n", text)
    i = 1
    while i + 1 < len(parts):
        role = "user" if parts[i] == "USER" else "assistant"
        content = parts[i + 1].strip()
        if content:
            messages.append({"role": role, "content": content})
        i += 2
    return messages


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
    Sessions are stored in Neo4j by store_session_background().
    This function returns the canonical path (no file is written).
    """
    if session_id is None:
        session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return _sessions_dir() / f"session-{session_id}.md"


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


_PROVIDERS_CFG_PATH = Path(__file__).parent / "config" / "providers.yaml"


def _profiles_path() -> Path:
    """Machine-local profiles registry — lives in sanctum dir (gitignored)."""
    return _sanctum_root() / "profiles.yaml"


def list_profiles() -> list[dict]:
    """Return configured profiles [{id, label}, ...] from Neo4j, falling back to profiles.yaml."""
    import memory as mem

    result = mem.list_profiles_sync()
    if result:
        return result
    # fallback: profiles.yaml (migration path)
    p = _profiles_path()
    if not p.exists():
        return []
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return data.get("profiles", [])
    except Exception:
        return []


def profiles_exist() -> bool:
    """True if at least one profile is configured."""
    return bool(list_profiles())


def get_active_profile() -> str:
    """Return the active profile id from providers.yaml (active_profile or group_id fallback)."""
    try:
        import yaml

        raw = yaml.safe_load(_PROVIDERS_CFG_PATH.read_text(encoding="utf-8")) or {}
        g = raw.get("graphiti", {})
        return g.get("active_profile") or g.get("group_id", "")
    except Exception:
        return ""


def set_active_profile(profile_id: str) -> None:
    """Update active_profile in providers.yaml in-place (preserves comments and structure)."""
    text = _PROVIDERS_CFG_PATH.read_text(encoding="utf-8")
    if "  active_profile:" in text:
        text = re.sub(r"  active_profile:.*", f'  active_profile: "{profile_id}"', text)
    elif "  group_id:" in text:
        text = re.sub(
            r"  group_id:.*",
            f'  active_profile: "{profile_id}"  # owner::context format',
            text,
        )
    _PROVIDERS_CFG_PATH.write_text(text, encoding="utf-8")


def add_profile(profile_id: str, label: str) -> None:
    """Add or update a profile in the registry and set it as active."""
    import yaml

    p = _profiles_path()
    data: dict = {}
    if p.exists():
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    profiles: list[dict] = data.get("profiles", [])
    if not any(pr["id"] == profile_id for pr in profiles):
        profiles.append({"id": profile_id, "label": label})
    data["profiles"] = profiles
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    set_active_profile(profile_id)
    try:
        import memory as mem

        mem.add_profile_sync(profile_id, label)
    except Exception:
        pass


def delete_profile(profile_id: str) -> None:
    """Remove a profile from the registry and update active_profile if needed."""
    import yaml

    p = _profiles_path()
    if not p.exists():
        return
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return
    data["profiles"] = [pr for pr in data.get("profiles", []) if pr["id"] != profile_id]
    p.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    if get_active_profile() == profile_id:
        remaining = data["profiles"]
        if remaining:
            set_active_profile(remaining[0]["id"])
    try:
        import memory as mem

        mem.delete_profile_sync(profile_id)
    except Exception:
        pass


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
