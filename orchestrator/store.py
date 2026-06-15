"""
store.py — PostgreSQL-backed operational storage for YANA.

Stores profiles, owner identity (sanctum fields), sessions, and connectors.
Neo4j (via memory.py) is reserved exclusively for Graphiti episodic memory.

Tables are created automatically on first call to init_schema_sync().
Connection URL is read from providers.yaml under postgres.url.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config" / "providers.yaml"
_DEFAULT_URL = "postgresql://postgres:postgres@localhost:5432/yana"

# Maps LLM write-protocol names → DB column names
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
# Config + connection
# ---------------------------------------------------------------------------


def _load_url() -> str:
    try:
        import yaml

        raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        return raw.get("postgres", {}).get("url", _DEFAULT_URL)
    except Exception:
        return _DEFAULT_URL


def _conn():
    """Return a new psycopg2 connection."""
    import psycopg2  # type: ignore[import]

    return psycopg2.connect(_load_url())


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def init_schema_sync() -> None:
    """Create all YANA tables if they do not exist. Safe to run on every startup."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS owners (
                        id           TEXT PRIMARY KEY,
                        name         TEXT NOT NULL DEFAULT '',
                        persona      TEXT,
                        creed        TEXT,
                        bond         TEXT,
                        updated_at   TEXT
                    );
                    CREATE TABLE IF NOT EXISTS profiles (
                        id           TEXT PRIMARY KEY,
                        owner_id     TEXT NOT NULL,
                        label        TEXT NOT NULL,
                        capabilities TEXT,
                        pulse        TEXT,
                        pulse_config TEXT,
                        created_at   TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS connectors (
                        profile_id   TEXT NOT NULL,
                        instance_id  TEXT NOT NULL,
                        config_json  TEXT NOT NULL DEFAULT '{}',
                        enabled      INTEGER NOT NULL DEFAULT 1,
                        PRIMARY KEY (profile_id, instance_id)
                    );
                    CREATE TABLE IF NOT EXISTS sessions (
                        id            TEXT PRIMARY KEY,
                        profile_id    TEXT NOT NULL,
                        started_at    TEXT NOT NULL,
                        preview       TEXT,
                        messages_json TEXT
                    );
                """)
            conn.commit()
    except Exception as e:
        log.debug("store: init_schema failed: %s", e)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def add_profile_sync(profile_id: str, label: str) -> None:
    owner_id = profile_id.split("::")[0]
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO owners (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
                    (owner_id,),
                )
                cur.execute(
                    """INSERT INTO profiles (id, owner_id, label, created_at)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (id) DO UPDATE SET label = EXCLUDED.label""",
                    (profile_id, owner_id, label, datetime.now(UTC).isoformat()),
                )
            conn.commit()
    except Exception as e:
        log.debug("store: add_profile failed: %s", e)


def list_profiles_sync() -> list[dict]:
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, label FROM profiles ORDER BY id")
                return [{"id": row[0], "label": row[1]} for row in cur.fetchall()]
    except Exception as e:
        log.debug("store: list_profiles failed: %s", e)
        return []


def delete_profile_sync(profile_id: str) -> None:
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM connectors WHERE profile_id = %s", (profile_id,))
                cur.execute("DELETE FROM sessions WHERE profile_id = %s", (profile_id,))
                cur.execute("DELETE FROM profiles WHERE id = %s", (profile_id,))
            conn.commit()
    except Exception as e:
        log.debug("store: delete_profile failed: %s", e)


# ---------------------------------------------------------------------------
# Sanctum fields
# ---------------------------------------------------------------------------


def save_sanctum_fields_sync(owner_id: str, profile_id: str, fields: dict[str, str]) -> None:
    owner_props = {_OWNER_FIELDS[k]: v for k, v in fields.items() if k in _OWNER_FIELDS}
    profile_props = {_PROFILE_FIELDS[k]: v for k, v in fields.items() if k in _PROFILE_FIELDS}
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                if owner_props:
                    cols = list(owner_props.keys())
                    vals = list(owner_props.values())
                    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
                    cur.execute(
                        f"INSERT INTO owners (id, {', '.join(cols)})"
                        f" VALUES (%s, {', '.join(['%s'] * len(cols))})"
                        f" ON CONFLICT (id) DO UPDATE SET {updates}, updated_at = %s",
                        (owner_id, *vals, datetime.now(UTC).isoformat()),
                    )
                if profile_props:
                    cols = list(profile_props.keys())
                    vals = list(profile_props.values())
                    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
                    # Upsert — creates a placeholder row if profile doesn't exist yet
                    # (First Breath writes sanctum before add_profile_sync registers the profile)
                    cur.execute(
                        f"INSERT INTO profiles (id, owner_id, label, {', '.join(cols)}, created_at)"
                        f" VALUES (%s, %s, %s, {', '.join(['%s'] * len(cols))}, %s)"
                        f" ON CONFLICT (id) DO UPDATE SET {updates}",
                        (
                            profile_id,
                            owner_id,
                            profile_id,  # placeholder label; overwritten by add_profile_sync
                            *vals,
                            datetime.now(UTC).isoformat(),
                        ),
                    )
            conn.commit()
    except Exception as e:
        log.debug("store: save_sanctum_fields failed: %s", e)


def load_sanctum_fields_sync(owner_id: str, profile_id: str) -> dict[str, str]:
    all_owner = list(_OWNER_FIELDS.values())
    all_profile = list(_PROFILE_FIELDS.values())
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(all_owner)} FROM owners WHERE id = %s",
                    (owner_id,),
                )
                owner_row = cur.fetchone() or ()
                cur.execute(
                    f"SELECT {', '.join(all_profile)} FROM profiles WHERE id = %s",
                    (profile_id,),
                )
                profile_row = cur.fetchone() or ()
        result: dict[str, str] = {}
        for prop, val in zip(all_owner, owner_row):
            if val:
                result[prop] = val
        for prop, val in zip(all_profile, profile_row):
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
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO sessions (id, profile_id, started_at, preview, messages_json)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (id) DO UPDATE
                       SET preview = EXCLUDED.preview,
                           messages_json = EXCLUDED.messages_json""",
                    (session_id, profile_id, started_at, preview, messages_json),
                )
            conn.commit()
    except Exception as e:
        log.debug("store: create_session failed: %s", e)


def list_sessions_sync(profile_id: str, limit: int = 20) -> list[tuple[str, datetime, str]]:
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, started_at, preview FROM sessions
                       WHERE profile_id = %s
                       ORDER BY started_at DESC
                       LIMIT %s""",
                    (profile_id, limit),
                )
                rows = cur.fetchall()
        result = []
        for sid, raw_dt, preview in rows:
            preview = preview or ""
            try:
                dt = datetime.fromisoformat(raw_dt)
            except Exception:
                try:
                    dt = datetime.strptime(sid, "%Y-%m-%d_%H-%M-%S")
                except Exception:
                    dt = datetime.now(UTC)
            result.append((sid, dt, preview))
        return result
    except Exception as e:
        log.debug("store: list_sessions failed: %s", e)
        return []


def load_session_messages_sync(session_id: str) -> list[dict]:
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT messages_json FROM sessions WHERE id = %s",
                    (session_id,),
                )
                row = cur.fetchone()
        if not row or not row[0]:
            return []
        return json.loads(row[0])
    except Exception as e:
        log.debug("store: load_session_messages failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Connectors
# ---------------------------------------------------------------------------


def save_connector_sync(profile_id: str, instance_id: str, config_json_str: str) -> None:
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO connectors (profile_id, instance_id, config_json)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (profile_id, instance_id)
                       DO UPDATE SET config_json = EXCLUDED.config_json""",
                    (profile_id, instance_id, config_json_str),
                )
            conn.commit()
    except Exception as e:
        log.debug("store: save_connector failed: %s", e)


def list_connectors_sync(profile_id: str) -> list[dict]:
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT instance_id, config_json FROM connectors WHERE profile_id = %s",
                    (profile_id,),
                )
                return [
                    {"instance_id": row[0], "config_json": row[1]}
                    for row in cur.fetchall()
                ]
    except Exception as e:
        log.debug("store: list_connectors failed: %s", e)
        return []
