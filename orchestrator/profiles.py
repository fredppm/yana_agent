"""
profiles.py — profile identity and runtime state.

Manages the active profile for this process, profile CRUD in PostgreSQL,
and owner/profile creation at First Breath.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Runtime state — set once at startup via set_runtime_profile()
# ---------------------------------------------------------------------------

_active_profile: str = ""
_PROFILE_LIMIT = 5


def get_active_profile() -> str:
    """Return the runtime-selected profile id (set at startup via set_runtime_profile)."""
    return _active_profile


def set_runtime_profile(profile_id: str) -> None:
    """Set the active profile for this process. Called once at startup after profile selection."""
    global _active_profile
    _active_profile = profile_id


def owner_id_from_profile(profile_id: str) -> str:
    """Return the owner UUID for a given profile UUID."""
    import store

    return store.get_owner_id_for_profile_sync(profile_id) or ""


def list_profiles() -> list[dict]:
    """Return configured profiles [{id, label}, ...] from PostgreSQL."""
    import store

    return store.list_profiles_sync()


def create_first_owner_and_profile(written: dict[str, str]) -> tuple[str, str]:
    """First Breath: create Owner + Profile from sanctum output.

    Returns (owner_id, profile_id).
    """
    import store

    name = (written.get("OWNER_NAME") or "").strip() or "User"
    owner_id = store.add_owner_sync(name)
    profile_id = store.add_profile_sync(owner_id, f"{name} — Default")
    return owner_id, profile_id


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
