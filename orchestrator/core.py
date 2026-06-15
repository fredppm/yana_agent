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


def list_sessions(limit: int = 20) -> list[tuple[str, datetime, str]]:
    """List recent sessions as (session_id, datetime, preview), newest first."""
    import memory as mem

    active = get_active_profile()
    if not active:
        return []
    return mem.list_sessions_sync(active, limit=limit)


def load_session_messages(session_id: str) -> list[dict]:
    """Load messages for a session from Neo4j."""
    import memory as mem

    return mem.load_session_messages_sync(session_id)


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


def list_profiles() -> list[dict]:
    """Return configured profiles [{id, label}, ...] from Neo4j."""
    import memory as mem

    return mem.list_profiles_sync()


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
    """Add a profile to Neo4j and set it as active."""
    import memory as mem

    mem.add_profile_sync(profile_id, label)
    set_active_profile(profile_id)


def delete_profile(profile_id: str) -> None:
    """Remove a profile from Neo4j and update active_profile if needed."""
    import memory as mem

    mem.delete_profile_sync(profile_id)
    if get_active_profile() == profile_id:
        remaining = list_profiles()
        if remaining:
            set_active_profile(remaining[0]["id"])


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
