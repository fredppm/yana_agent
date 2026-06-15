"""
memory.py — Graphiti-based episodic memory for YANA.

Stores conversation episodes in a Neo4j knowledge graph via Graphiti-core.
Operational data (profiles, sanctum, sessions, connectors) lives in store.py (PostgreSQL).

Architecture:
  YANA session end  → store_session_background()  → background thread
  YANA session start → load_context()              → injected into system prompt

Setup (see docker-compose.yml):
  - Neo4j:   bolt://localhost:7687
  - LiteLLM: http://localhost:4000  →  AWS Bedrock

Config lives in providers.yaml under the `graphiti:` key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

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
}


def _load_config() -> dict:
    """Read graphiti section from providers.yaml. Returns defaults if missing."""
    try:
        import yaml

        raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        return {**_DEFAULT_CONFIG, **raw.get("graphiti", {})}
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
    Persist raw session messages in PostgreSQL and add a Graphiti episode.
    """
    import store

    from graphiti_core.nodes import EpisodeType

    import core

    cfg = _load_config()
    profile_id = core.get_active_profile() or "yana-default"

    # Build conversation text for Graphiti episode
    lines = []
    for m in messages:
        if not isinstance(m.get("content"), str) or not m["content"].strip():
            continue
        role = "user" if m["role"] == "user" else "YANA"
        lines.append(f"{role}: {m['content']}")
    conversation_text = "\n".join(lines)

    # Preview: first user message, 60 chars
    preview = ""
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), str) and m["content"].strip():
            preview = m["content"].strip()[:60]
            break

    created_at = datetime.now(UTC).isoformat()

    # Persist session + messages in PostgreSQL
    store.create_session_sync(
        session_id,
        profile_id,
        created_at,
        preview,
        json.dumps(messages, ensure_ascii=False),
    )

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
                group_id=profile_id,
            )
            log.debug("memory: stored session episode -> %s", session_id)
        finally:
            await client.close()


async def load_context(
    query: str = "quem e o usuario, o que esta acontecendo na vida dele agora",
) -> str:
    """
    Retrieve relevant memory from Graphiti to inject into the system prompt.

    Returns a formatted markdown block, or empty string if unavailable.
    """
    import core

    cfg = _load_config()
    client = _build_client(cfg)
    profile_gid = core.get_active_profile() or "yana-default"
    # Search both owner-level (fred) and profile-level (fred::pessoal) group_ids
    owner_gid = profile_gid.split("::")[0]
    search_group_ids = list({owner_gid, profile_gid})
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
    query: str = "quem e o usuario, o que esta acontecendo na vida dele agora",
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
