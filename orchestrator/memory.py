"""
memory.py — Graphiti-based episodic memory for YANA.

Replaces sanctum_writer for regular sessions. Stores conversation episodes
in a Neo4j knowledge graph via Graphiti-core, using LiteLLM as a proxy to
AWS Bedrock (fully self-hosted, zero managed cost).

Architecture:
  YANA session end  → store_session_background()  → background thread
  YANA session start → load_context()              → injected into system prompt

Setup (see orchestrator/spikes/docker-compose.yml):
  - Neo4j:   bolt://localhost:7687
  - LiteLLM: http://localhost:4000  →  AWS Bedrock

Config lives in providers.yaml under the `graphiti:` key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent / "config" / "providers.yaml"

_DEFAULT_CONFIG: dict = {
    "uri": "bolt://localhost:7687",
    "user": "",
    "password": "",
    "litellm_url": "http://localhost:4000",
    "model": "bedrock-claude-haiku",
    "embed_model": "bedrock-embed",
    "active_profile": "",  # owner::context — set by First Breath; falls back to group_id
    "group_id": "yana-fred",  # legacy key — superseded by active_profile
}


def _load_config() -> dict:
    """Read graphiti section from providers.yaml. Returns defaults if missing."""
    try:
        import yaml

        raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        cfg = {**_DEFAULT_CONFIG, **raw.get("graphiti", {})}
        # Normalize: active_profile supersedes legacy group_id key
        if not cfg.get("active_profile") and cfg.get("group_id"):
            cfg["active_profile"] = cfg["group_id"]
        return cfg
    except Exception:
        return dict(_DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def _build_client(cfg: dict):  # returns Graphiti
    from graphiti_core import Graphiti
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.openai_client import OpenAIClient

    llm_cfg = LLMConfig(
        api_key="bedrock",
        base_url=cfg["litellm_url"],
        model=cfg["model"],
        small_model=cfg["model"],
    )
    llm = OpenAIClient(config=llm_cfg)
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key="bedrock",
            base_url=cfg["litellm_url"],
            embedding_model=cfg["embed_model"],
        )
    )
    reranker = OpenAIRerankerClient(config=llm_cfg)
    return Graphiti(
        cfg["uri"],
        cfg["user"],
        cfg["password"],
        llm_client=llm,
        embedder=embedder,
        cross_encoder=reranker,
    )


# ---------------------------------------------------------------------------
# Core operations (async)
# ---------------------------------------------------------------------------


async def store_session(messages: list[dict], session_id: str) -> None:
    """
    Add session to the Graphiti knowledge graph as a single episode,
    and persist session node + messages_json in Neo4j.
    """
    from graphiti_core.nodes import EpisodeType

    cfg = _load_config()

    workspace_id = cfg.get("active_profile") or cfg.get("group_id", "yana-fred")

    # Build conversation text for Graphiti episode
    lines = []
    for m in messages:
        if not isinstance(m.get("content"), str) or not m["content"].strip():
            continue
        role = "Fred" if m["role"] == "user" else "YANA"
        lines.append(f"{role}: {m['content']}")
    conversation_text = "\n".join(lines)

    # Preview: first user message, 60 chars
    preview = ""
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), str) and m["content"].strip():
            preview = m["content"].strip()[:60]
            break

    messages_json_str = json.dumps(messages, ensure_ascii=False)
    created_at = datetime.now(UTC).isoformat()

    # Persist session node in Neo4j
    await create_session(cfg, session_id, workspace_id, created_at, preview, messages_json_str)

    # Add one Graphiti episode for the whole conversation
    if conversation_text:
        client = _build_client(cfg)
        try:
            await client.add_episode(
                name=session_id,
                episode_body=conversation_text,
                source=EpisodeType.text,
                source_description=f"YANA session {session_id}",
                reference_time=datetime.now(UTC),
                group_id=workspace_id,
            )
            log.debug("memory: stored session episode -> %s", session_id)
        finally:
            await client.close()


async def load_context(
    query: str = "quem e Fred, o que esta acontecendo na vida dele agora",
) -> str:
    """
    Retrieve relevant memory from Graphiti to inject into the system prompt.

    Returns a formatted markdown block, or empty string if unavailable.
    """
    cfg = _load_config()
    client = _build_client(cfg)
    workspace_gid = cfg.get("active_profile") or cfg.get("group_id", "yana-fred")
    # Search both owner-level (fred) and workspace-level (fred::pessoal) group_ids
    owner_gid = workspace_gid.split("::")[0] if "::" in workspace_gid else workspace_gid
    search_group_ids = list({owner_gid, workspace_gid})
    try:
        results = await client.search(
            query,
            group_ids=search_group_ids,
            num_results=15,
        )
    except Exception as e:
        log.debug("memory: load_context failed: %s", e)
        return ""
    finally:
        await client.close()

    if not results:
        return ""

    lines = ["---", "## Episodic Memory (Graphiti)", ""]
    for fact in results:
        if hasattr(fact, "fact") and fact.fact:
            lines.append(f"- {fact.fact}")

    return "\n".join(lines) if len(lines) > 3 else ""


# ---------------------------------------------------------------------------
# Sync wrappers
# ---------------------------------------------------------------------------


def store_session_background(messages: list[dict], session_id: str) -> None:
    """
    Fire-and-forget: store session in a background thread.

    The TUI can close immediately. Thread is non-daemon so the process
    stays alive until indexing finishes (typically a few seconds).
    """

    def _run() -> None:
        try:
            asyncio.run(store_session(messages, session_id))
        except Exception as e:
            log.debug("memory: background store failed: %s", e)

    threading.Thread(target=_run, daemon=False, name="graphiti-store").start()


def load_context_sync(
    query: str = "quem e Fred, o que esta acontecendo na vida dele agora",
    timeout: float = 5.0,
) -> str:
    """
    Synchronous wrapper for load_context with a timeout.

    Safe to call from sync code (e.g. core.load_system_prompt).
    Returns empty string on timeout or error — never raises.
    """
    result: list[str] = [""]

    def _run() -> None:
        try:
            result[0] = asyncio.run(load_context(query))
        except Exception as e:
            log.debug("memory: load_context_sync failed: %s", e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result[0]


# ---------------------------------------------------------------------------
# Neo4j graph operations (direct Cypher — sessions, profiles, connectors)
# ---------------------------------------------------------------------------


async def _neo4j_write(cfg: dict, query: str, params: dict) -> None:
    from neo4j import AsyncGraphDatabase

    driver = AsyncGraphDatabase.driver(cfg["uri"], auth=None)
    try:
        async with driver.session() as session:
            await session.run(query, params)
    finally:
        await driver.close()


async def _neo4j_read(cfg: dict, query: str, params: dict) -> list[dict]:
    from neo4j import AsyncGraphDatabase

    driver = AsyncGraphDatabase.driver(cfg["uri"], auth=None)
    try:
        async with driver.session() as session:
            result = await session.run(query, params)
            return [record.data() for record in await result.fetch(1000)]
    finally:
        await driver.close()


async def init_schema(cfg: dict) -> None:
    constraints = [
        "CREATE CONSTRAINT yana_owner_id IF NOT EXISTS FOR (n:YANAOwner) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT yana_workspace_id IF NOT EXISTS FOR (n:YANAWorkspace) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT yana_session_id IF NOT EXISTS FOR (n:YANASession) REQUIRE n.id IS UNIQUE",
    ]
    for c in constraints:
        await _neo4j_write(cfg, c, {})


async def add_profile(cfg: dict, workspace_id: str, label: str) -> None:
    owner_id = workspace_id.split("::")[0] if "::" in workspace_id else workspace_id
    query = (
        "MERGE (o:YANAOwner {id: $owner_id}) "
        "MERGE (w:YANAWorkspace {id: $workspace_id}) "
        "SET w.label = $label, w.owner_id = $owner_id "
        "MERGE (o)-[:HAS_WORKSPACE]->(w)"
    )
    await _neo4j_write(
        cfg, query, {"owner_id": owner_id, "workspace_id": workspace_id, "label": label}
    )


async def list_profiles(cfg: dict) -> list[dict]:
    query = "MATCH (w:YANAWorkspace) RETURN w.id AS id, w.label AS label ORDER BY w.id"
    return await _neo4j_read(cfg, query, {})


async def delete_profile(cfg: dict, workspace_id: str) -> None:
    query = (
        "MATCH (w:YANAWorkspace {id: $workspace_id}) "
        "OPTIONAL MATCH (w)-[:HAS_SESSION]->(s:YANASession) "
        "OPTIONAL MATCH (w)-[:HAS_CONNECTOR]->(c:YANAConnector) "
        "DETACH DELETE w, s, c"
    )
    await _neo4j_write(cfg, query, {"workspace_id": workspace_id})


async def save_connector(
    cfg: dict, workspace_id: str, instance_id: str, config_json_str: str
) -> None:
    query = (
        "MERGE (w:YANAWorkspace {id: $workspace_id}) "
        "MERGE (c:YANAConnector {workspace_id: $workspace_id, instance_id: $instance_id}) "
        "SET c.config_json = $config_json "
        "MERGE (w)-[:HAS_CONNECTOR]->(c)"
    )
    await _neo4j_write(
        cfg,
        query,
        {"workspace_id": workspace_id, "instance_id": instance_id, "config_json": config_json_str},
    )


async def list_connectors(cfg: dict, workspace_id: str) -> list[dict]:
    query = (
        "MATCH (w:YANAWorkspace {id: $workspace_id})-[:HAS_CONNECTOR]->(c:YANAConnector) "
        "RETURN c.instance_id AS instance_id, c.config_json AS config_json"
    )
    return await _neo4j_read(cfg, query, {"workspace_id": workspace_id})


async def create_session(
    cfg: dict,
    session_id: str,
    workspace_id: str,
    created_at_iso: str,
    preview: str,
    messages_json_str: str,
) -> None:
    query = (
        "MERGE (w:YANAWorkspace {id: $workspace_id}) "
        "MERGE (s:YANASession {id: $session_id}) "
        "SET s.workspace_id = $workspace_id, "
        "    s.created_at = $created_at, "
        "    s.preview = $preview, "
        "    s.messages_json = $messages_json "
        "MERGE (w)-[:HAS_SESSION]->(s)"
    )
    await _neo4j_write(
        cfg,
        query,
        {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "created_at": created_at_iso,
            "preview": preview,
            "messages_json": messages_json_str,
        },
    )


async def list_sessions(
    cfg: dict, workspace_id: str, limit: int = 20
) -> list[tuple[str, datetime, str]]:
    query = (
        "MATCH (w:YANAWorkspace {id: $workspace_id})-[:HAS_SESSION]->(s:YANASession) "
        "RETURN s.id AS id, s.created_at AS created_at, s.preview AS preview "
        "ORDER BY s.created_at DESC "
        "LIMIT $limit"
    )
    rows = await _neo4j_read(cfg, query, {"workspace_id": workspace_id, "limit": limit})
    result = []
    for row in rows:
        sid = row.get("id", "")
        preview = row.get("preview", "") or ""
        raw_dt = row.get("created_at", "")
        try:
            dt = datetime.fromisoformat(raw_dt)
        except Exception:
            try:
                dt = datetime.strptime(sid, "%Y-%m-%d_%H-%M-%S")
            except Exception:
                dt = datetime.now(UTC)
        result.append((sid, dt, preview))
    return result


async def load_session_messages(cfg: dict, session_id: str) -> list[dict]:
    query = "MATCH (s:YANASession {id: $session_id}) RETURN s.messages_json AS messages_json"
    rows = await _neo4j_read(cfg, query, {"session_id": session_id})
    if not rows or not rows[0].get("messages_json"):
        return []
    try:
        return json.loads(rows[0]["messages_json"])
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Public sync wrappers for Neo4j operations
# ---------------------------------------------------------------------------


def _run_async(coro: Coroutine[Any, Any, Any], timeout: float = 10.0) -> Any:
    """Run an async coroutine in a daemon thread with timeout. Returns result or None."""
    result: list = [None]
    exc: list = [None]

    def _run() -> None:
        try:
            result[0] = asyncio.run(coro)
        except Exception as e:
            exc[0] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if exc[0] is not None:
        log.debug("memory: async op failed: %s", exc[0])
    return result[0]


def init_schema_sync() -> None:
    _run_async(init_schema(_load_config()))


def list_profiles_sync() -> list[dict]:
    result = _run_async(list_profiles(_load_config()))
    return result if isinstance(result, list) else []


def add_profile_sync(workspace_id: str, label: str) -> None:
    _run_async(add_profile(_load_config(), workspace_id, label))


def delete_profile_sync(workspace_id: str) -> None:
    _run_async(delete_profile(_load_config(), workspace_id))


def list_sessions_sync(workspace_id: str, limit: int = 20) -> list[tuple[str, datetime, str]]:
    result = _run_async(list_sessions(_load_config(), workspace_id, limit=limit))
    return result if isinstance(result, list) else []


def load_session_messages_sync(session_id: str) -> list[dict]:
    result = _run_async(load_session_messages(_load_config(), session_id))
    return result if isinstance(result, list) else []


def list_connectors_sync(workspace_id: str) -> list[dict]:
    result = _run_async(list_connectors(_load_config(), workspace_id))
    return result if isinstance(result, list) else []


def save_connector_sync(workspace_id: str, instance_id: str, config_json_str: str) -> None:
    _run_async(save_connector(_load_config(), workspace_id, instance_id, config_json_str))


# ---------------------------------------------------------------------------
# Sanctum identity fields — stored on YANAOwner / YANAWorkspace nodes
# ---------------------------------------------------------------------------

_OWNER_FIELDS: dict[str, str] = {
    "PERSONA.md": "persona",
    "CREED.md": "creed",
    "BOND.md": "bond",
}
_WORKSPACE_FIELDS: dict[str, str] = {
    "MEMORY.md": "memory",
    "CAPABILITIES.md": "capabilities",
    "PULSE.md": "pulse",
    "pulse-config.yaml": "pulse_config",
}


async def save_sanctum_fields(
    cfg: dict, owner_id: str, workspace_id: str, fields: dict[str, str]
) -> None:
    """Write {filename: content} to YANAOwner and YANAWorkspace node properties."""
    owner_props = {_OWNER_FIELDS[k]: v for k, v in fields.items() if k in _OWNER_FIELDS}
    workspace_props = {_WORKSPACE_FIELDS[k]: v for k, v in fields.items() if k in _WORKSPACE_FIELDS}
    if owner_props:
        sets = ", ".join(f"o.{k} = ${k}" for k in owner_props)
        await _neo4j_write(
            cfg,
            f"MERGE (o:YANAOwner {{id: $owner_id}}) SET {sets}",
            {"owner_id": owner_id, **owner_props},
        )
    if workspace_props:
        sets = ", ".join(f"w.{k} = ${k}" for k in workspace_props)
        await _neo4j_write(
            cfg,
            f"MERGE (w:YANAWorkspace {{id: $workspace_id}}) SET {sets}",
            {"workspace_id": workspace_id, **workspace_props},
        )


async def load_sanctum_fields(cfg: dict, owner_id: str, workspace_id: str) -> dict[str, str]:
    """Load all sanctum fields from YANAOwner and YANAWorkspace, returns {filename: content}."""
    rows = await _neo4j_read(
        cfg,
        """
        OPTIONAL MATCH (o:YANAOwner {id: $owner_id})
        OPTIONAL MATCH (w:YANAWorkspace {id: $workspace_id})
        RETURN o.persona AS persona, o.creed AS creed, o.bond AS bond,
               w.memory AS memory, w.capabilities AS capabilities,
               w.pulse AS pulse, w.pulse_config AS pulse_config
        """,
        {"owner_id": owner_id, "workspace_id": workspace_id},
    )
    if not rows:
        return {}
    row = rows[0]
    inv = {v: k for k, v in {**_OWNER_FIELDS, **_WORKSPACE_FIELDS}.items()}
    return {inv[prop]: val for prop, val in row.items() if val and prop in inv}


def save_sanctum_fields_sync(owner_id: str, workspace_id: str, fields: dict[str, str]) -> None:
    _run_async(save_sanctum_fields(_load_config(), owner_id, workspace_id, fields))


def load_sanctum_fields_sync(owner_id: str, workspace_id: str) -> dict[str, str]:
    result = _run_async(load_sanctum_fields(_load_config(), owner_id, workspace_id))
    return result if isinstance(result, dict) else {}
