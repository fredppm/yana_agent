"""
store.py — PostgreSQL-backed operational storage for YANA.

Models defined with SQLAlchemy ORM — schema created automatically via
Base.metadata.create_all() on startup. No hand-written DDL.

Connection URL: providers.yaml → postgres.url
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Integer, PrimaryKeyConstraint, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, MappedColumn, Session, mapped_column

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config" / "providers.yaml"
_DEFAULT_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/yana"

# Maps LLM write-protocol names → ORM attribute names
_OWNER_FIELDS: dict[str, str] = {
    "PERSONA": "persona",
    "CREED": "creed",
    "BOND": "bond",
}
_PROFILE_FIELDS: dict[str, str] = {
    "CAPABILITIES": "capabilities",
    "PULSE": "pulse",
    "PULSE_CONFIG": "pulse_config",
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = "owners"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)           # UUID
    username: MappedColumn[str] = mapped_column(String, nullable=False)        # "fred" — immutable, unique
    name: MappedColumn[str | None] = mapped_column(String, nullable=True)      # apelido — mutable free text
    persona: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    creed: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    bond: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    updated_at: MappedColumn[str | None] = mapped_column(String, nullable=True)


class Profile(Base):
    __tablename__ = "profiles"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    owner_id: MappedColumn[str] = mapped_column(String, nullable=False)
    label: MappedColumn[str] = mapped_column(String, nullable=False)
    capabilities: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    pulse: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    pulse_config: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    created_at: MappedColumn[str] = mapped_column(String, nullable=False)


class Connector(Base):
    __tablename__ = "connectors"
    __table_args__ = (PrimaryKeyConstraint("profile_id", "instance_id"),)

    profile_id: MappedColumn[str] = mapped_column(String, nullable=False)
    instance_id: MappedColumn[str] = mapped_column(String, nullable=False)
    config_json: MappedColumn[str] = mapped_column(Text, nullable=False, default="{}")
    enabled: MappedColumn[int] = mapped_column(Integer, nullable=False, default=1)


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    profile_id: MappedColumn[str] = mapped_column(String, nullable=False)
    started_at: MappedColumn[str] = mapped_column(String, nullable=False)
    preview: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    messages_json: MappedColumn[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Engine (module-level, one connection pool per process)
# ---------------------------------------------------------------------------

_engine_cache: Any = None


def _load_url() -> str:
    try:
        import yaml

        raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        url = raw.get("postgres", {}).get("url", _DEFAULT_URL)
        # Ensure the psycopg2 driver prefix is present
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url
    except Exception:
        return _DEFAULT_URL


def _get_engine():
    global _engine_cache
    if _engine_cache is None:
        _engine_cache = create_engine(_load_url(), pool_pre_ping=True)
    return _engine_cache


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


_MIGRATION_STAMP = Path(__file__).parent / "config" / ".db-revision"


def _code_head() -> str:
    """Return the HEAD revision from the migration scripts (no DB needed)."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(Path(__file__).parent / "alembic.ini")
        return ScriptDirectory.from_config(cfg).get_current_head() or ""
    except Exception:
        return ""


def init_schema_sync() -> None:
    """Apply all pending Alembic migrations. Safe to run on every startup.

    Skips the Alembic DB round-trip when the local stamp file matches the
    code HEAD — saving ~2s on every startup when no migrations are pending.
    On any mismatch (new migration deployed, fresh install, stamp missing),
    runs the full upgrade and writes the new stamp.
    """
    head = _code_head()
    if head and _MIGRATION_STAMP.exists() and _MIGRATION_STAMP.read_text().strip() == head:
        log.debug("store: schema up to date (%s) — skipping alembic", head)
        return

    try:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config(Path(__file__).parent / "alembic.ini")
        command.upgrade(alembic_cfg, "head")
        if head:
            _MIGRATION_STAMP.write_text(head)
    except Exception as e:
        log.error("store: migration failed — check PostgreSQL connection: %s", e)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def add_owner_sync(username: str, name: str = "") -> str:
    """Create a new owner. Returns owner UUID."""
    owner_id = str(uuid.uuid4())
    try:
        with Session(_get_engine()) as session:
            existing = session.scalars(select(Owner).where(Owner.username == username)).first()
            if existing:
                return existing.id
            session.add(Owner(id=owner_id, username=username, name=name or None))
            session.commit()
    except Exception as e:
        log.debug("store: add_owner failed: %s", e)
    return owner_id


def add_profile_sync(owner_id: str, label: str) -> str:
    """Create a new profile under owner_id. Returns new profile UUID."""
    profile_id = str(uuid.uuid4())
    try:
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
    except Exception as e:
        log.debug("store: add_profile failed: %s", e)
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
    try:
        with Session(_get_engine()) as session:
            profiles = session.scalars(select(Profile).order_by(Profile.created_at)).all()
            return [{"id": p.id, "label": p.label} for p in profiles]
    except Exception as e:
        log.error("store: list_profiles failed — check PostgreSQL connection: %s", e)
        return []


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


# ---------------------------------------------------------------------------
# Sanctum fields
# ---------------------------------------------------------------------------


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
    try:
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
    except Exception as e:
        log.debug("store: load_sanctum_fields failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


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
    try:
        with Session(_get_engine()) as db:
            record = db.get(SessionRecord, session_id)
        if not record or not record.messages_json:
            return []
        return json.loads(record.messages_json)
    except Exception as e:
        log.debug("store: load_session_messages failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Connectors
# ---------------------------------------------------------------------------


def save_connector_sync(profile_id: str, instance_id: str, config_json_str: str) -> None:
    try:
        with Session(_get_engine()) as db:
            connector = db.get(Connector, (profile_id, instance_id))
            if connector is None:
                connector = Connector(profile_id=profile_id, instance_id=instance_id)
                db.add(connector)
            connector.config_json = config_json_str
            db.commit()
    except Exception as e:
        log.debug("store: save_connector failed: %s", e)


def list_connectors_sync(profile_id: str) -> list[dict]:
    try:
        with Session(_get_engine()) as db:
            connectors = db.scalars(
                select(Connector).where(Connector.profile_id == profile_id)
            ).all()
            return [
                {"instance_id": c.instance_id, "config_json": c.config_json}
                for c in connectors
            ]
    except Exception as e:
        log.debug("store: list_connectors failed: %s", e)
        return []
