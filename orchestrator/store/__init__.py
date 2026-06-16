from __future__ import annotations

from sqlalchemy.orm import Session  # re-exported for conftest

from .connectors import list_connectors_sync, save_connector_sync
from .engine import _engine_cache, _get_engine, _load_url
from .models import (
    _OWNER_FIELDS,
    _PROFILE_FIELDS,
    Base,
    Connector,
    Owner,
    Profile,
    SessionRecord,
)
from .owners import add_owner_sync
from .profiles import (
    add_profile_sync,
    delete_profile_sync,
    get_owner_id_for_profile_sync,
    list_profiles_sync,
    update_profile_label_sync,
)
from .sanctum import load_sanctum_fields_sync, save_sanctum_fields_sync
from .sessions import (
    create_session_sync,
    list_sessions_sync,
    load_session_messages_sync,
    update_session_preview_sync,
)

__all__ = [
    "_CONFIG_PATH",
    "_OWNER_FIELDS",
    "_PROFILE_FIELDS",
    "Base",
    "Connector",
    "Owner",
    "Profile",
    "Session",
    "SessionRecord",
    "_engine_cache",
    "_get_engine",
    "_load_url",
    "add_owner_sync",
    "add_profile_sync",
    "create_session_sync",
    "delete_profile_sync",
    "get_owner_id_for_profile_sync",
    "list_connectors_sync",
    "list_profiles_sync",
    "list_sessions_sync",
    "load_sanctum_fields_sync",
    "load_session_messages_sync",
    "save_connector_sync",
    "save_sanctum_fields_sync",
    "update_profile_label_sync",
    "update_session_preview_sync",
]
