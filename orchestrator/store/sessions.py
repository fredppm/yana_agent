from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engine import _get_engine
from .models import SessionRecord

log = logging.getLogger(__name__)


def create_session_sync(
    session_id: str,
    profile_id: str,
    started_at: str,
    preview: str,
    messages_json: str,
) -> None:
    try:
        with Session(_get_engine()) as db:
            record = db.get(SessionRecord, session_id)
            if record is None:
                record = SessionRecord(
                    id=session_id, profile_id=profile_id, started_at=started_at
                )
                db.add(record)
            record.preview = preview
            record.messages_json = messages_json
            db.commit()
    except Exception as e:
        log.debug("store: create_session failed: %s", e)


def update_session_preview_sync(session_id: str, preview: str) -> None:
    """Update the preview/title of an existing session."""
    try:
        with Session(_get_engine()) as db:
            record = db.get(SessionRecord, session_id)
            if record:
                record.preview = preview[:80]
                db.commit()
    except Exception as e:
        log.debug("store: update_session_preview failed: %s", e)


def list_sessions_sync(profile_id: str, limit: int = 20) -> list[tuple[str, datetime, str]]:
    try:
        with Session(_get_engine()) as db:
            records = db.scalars(
                select(SessionRecord)
                .where(SessionRecord.profile_id == profile_id)
                .order_by(SessionRecord.started_at.desc())
                .limit(limit)
            ).all()
        result = []
        for r in records:
            preview = r.preview or ""
            try:
                dt = datetime.fromisoformat(r.started_at)
            except Exception:
                try:
                    dt = datetime.strptime(r.id, "%Y-%m-%d_%H-%M-%S")
                except Exception:
                    dt = datetime.now(UTC)
            result.append((r.id, dt, preview))
        return result
    except Exception as e:
        log.debug("store: list_sessions failed: %s", e)
        return []


def load_session_messages_sync(session_id: str) -> list[dict]:
    """Load messages for a session. Returns [] if not found. Raises on DB failure."""
    with Session(_get_engine()) as db:
        record = db.get(SessionRecord, session_id)
    if not record or not record.messages_json:
        return []
    return json.loads(record.messages_json)
