from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engine import _get_engine
from .models import Connector, Profile, SessionRecord

log = logging.getLogger(__name__)


def add_profile_sync(owner_id: str, label: str) -> str:
    """Create a new profile under owner_id. Returns new profile UUID. Raises on DB failure."""
    profile_id = str(uuid.uuid4())
    with Session(_get_engine()) as session:
        session.add(
            Profile(
                id=profile_id,
                owner_id=owner_id,
                label=label,
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        session.commit()
    return profile_id


def get_owner_id_for_profile_sync(profile_id: str) -> str | None:
    """Return the owner UUID for a given profile UUID."""
    try:
        with Session(_get_engine()) as session:
            profile = session.get(Profile, profile_id)
            return profile.owner_id if profile else None
    except Exception as e:
        log.debug("store: get_owner_id_for_profile failed: %s", e)
        return None


def list_profiles_sync() -> list[dict]:
    """Return [{id, label}] ordered by created_at. Raises on DB failure."""
    with Session(_get_engine()) as session:
        profiles = session.scalars(select(Profile).order_by(Profile.created_at)).all()
        return [{"id": p.id, "label": p.label} for p in profiles]


def update_profile_label_sync(profile_id: str, new_label: str) -> None:
    try:
        with Session(_get_engine()) as session:
            profile = session.get(Profile, profile_id)
            if profile:
                profile.label = new_label
                session.commit()
    except Exception as e:
        log.debug("store: update_profile_label failed: %s", e)


def delete_profile_sync(profile_id: str) -> None:
    try:
        with Session(_get_engine()) as session:
            for c in session.scalars(
                select(Connector).where(Connector.profile_id == profile_id)
            ).all():
                session.delete(c)
            for s in session.scalars(
                select(SessionRecord).where(SessionRecord.profile_id == profile_id)
            ).all():
                session.delete(s)
            profile = session.get(Profile, profile_id)
            if profile:
                session.delete(profile)
            session.commit()
    except Exception as e:
        log.debug("store: delete_profile failed: %s", e)
