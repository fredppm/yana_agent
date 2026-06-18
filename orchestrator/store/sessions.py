from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engine import _get_engine
from .models import SessionRecord


def create_session_sync(
    session_id: str,
    profile_id: str,
    started_at: str,
    title: str,
    messages_json: str,
) -> None:
    with Session(_get_engine()) as db:
        record = db.get(SessionRecord, session_id)
        if record is None:
            record = SessionRecord(id=session_id, profile_id=profile_id, started_at=started_at)
            db.add(record)
        record.title = title
        record.messages_json = messages_json
        db.commit()


def update_session_title_sync(session_id: str, title: str, summary: str | None = None) -> None:
    """Update the title (and optionally summary) of an existing session."""
    with Session(_get_engine()) as db:
        record = db.get(SessionRecord, session_id)
        if record:
            record.title = title[:200]
            if summary is not None:
                record.summary = summary
            db.commit()


def list_sessions_sync(profile_id: str, limit: int = 20) -> list[tuple[str, datetime, str]]:
    """List sessions for a profile. Raises on DB failure — empty return would hide existing sessions."""
    with Session(_get_engine()) as db:
        records = db.scalars(
            select(SessionRecord)
            .where(SessionRecord.profile_id == profile_id)
            .order_by(SessionRecord.started_at.desc())
            .limit(limit)
        ).all()
    return [(r.id, datetime.fromisoformat(r.started_at), r.title or "") for r in records]


def load_session_messages_sync(session_id: str) -> list[dict]:
    """Load messages for a session. Returns [] if not found. Raises on DB failure."""
    with Session(_get_engine()) as db:
        record = db.get(SessionRecord, session_id)
    if not record or not record.messages_json:
        return []
    return json.loads(record.messages_json)


def load_session_summary_sync(session_id: str) -> str | None:
    """Load the summary for a session. Returns None if not found."""
    with Session(_get_engine()) as db:
        record = db.get(SessionRecord, session_id)
    if not record:
        return None
    return record.summary


def list_untitled_sessions_sync(profile_id: str, limit: int = 50) -> list[tuple[str, str]]:
    """Return (session_id, started_at) for sessions without a generated title.

    A session is considered "untitled" when title is NULL or starts with the
    first 80 chars of the first assistant message (the old preview fallback).
    For simplicity, we check for NULL or empty title only.
    """
    with Session(_get_engine()) as db:
        records = db.scalars(
            select(SessionRecord)
            .where(
                SessionRecord.profile_id == profile_id,
                (SessionRecord.title.is_(None)) | (SessionRecord.title == ""),
            )
            .order_by(SessionRecord.started_at.desc())
            .limit(limit)
        ).all()
    return [(r.id, r.started_at) for r in records]
