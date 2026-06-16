from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from .engine import _get_engine
from .models import Owner, Profile, _OWNER_FIELDS, _PROFILE_FIELDS

log = logging.getLogger(__name__)


def save_sanctum_fields_sync(owner_id: str, profile_id: str, fields: dict[str, str]) -> None:
    owner_props = {_OWNER_FIELDS[k]: v for k, v in fields.items() if k in _OWNER_FIELDS}
    profile_props = {_PROFILE_FIELDS[k]: v for k, v in fields.items() if k in _PROFILE_FIELDS}
    try:
        with Session(_get_engine()) as session:
            if owner_props:
                owner = session.get(Owner, owner_id)
                if owner:
                    for attr, val in owner_props.items():
                        setattr(owner, attr, val)
                    owner.updated_at = datetime.now(UTC).isoformat()
            if profile_props:
                profile = session.get(Profile, profile_id)
                if profile:
                    for attr, val in profile_props.items():
                        setattr(profile, attr, val)
            session.commit()
    except Exception as e:
        log.debug("store: save_sanctum_fields failed: %s", e)


def load_sanctum_fields_sync(owner_id: str, profile_id: str) -> dict[str, str]:
    """Load sanctum fields from PostgreSQL. Raises on DB failure — empty return would trigger First Breath."""
    with Session(_get_engine()) as session:
        owner = session.get(Owner, owner_id)
        profile = session.get(Profile, profile_id)
    result: dict[str, str] = {}
    if owner:
        for prop in _OWNER_FIELDS.values():
            val = getattr(owner, prop, None)
            if val:
                result[prop] = val
    if profile:
        for prop in _PROFILE_FIELDS.values():
            val = getattr(profile, prop, None)
            if val:
                result[prop] = val
    return result
