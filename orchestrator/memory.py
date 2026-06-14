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
import logging
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent / "config" / "providers.yaml"

_DEFAULT_CONFIG: dict = {
    "enabled": False,
    "uri": "bolt://localhost:7687",
    "user": "",
    "password": "",
    "litellm_url": "http://localhost:4000",
    "model": "bedrock-claude-haiku",
    "embed_model": "bedrock-embed",
    "group_id": "yana-fred",
}


def _load_config() -> dict:
    """Read graphiti section from providers.yaml. Returns defaults if missing.

    litellm_url precedence:
      1. graphiti.litellm_url  — explicit override in the graphiti block
      2. llm.litellm_url       — shared top-level config (new format)
      3. _DEFAULT_CONFIG       — "http://localhost:4000"
    """
    try:
        import yaml

        raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        graphiti_cfg = raw.get("graphiti", {})
        # Inherit top-level litellm_url when the graphiti block does not override it
        if "litellm_url" not in graphiti_cfg:
            top_level_url = raw.get("llm", {}).get("litellm_url")
            if top_level_url:
                graphiti_cfg = {"litellm_url": top_level_url, **graphiti_cfg}
        return {**_DEFAULT_CONFIG, **graphiti_cfg}
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
    Add session messages to the Graphiti knowledge graph.

    Graphiti extracts entities, relations, and facts from the conversation
    via LLM (Bedrock through LiteLLM) — asynchronously on their side.
    This call returns as soon as messages are submitted.
    """
    from graphiti_core.nodes import EpisodeType

    cfg = _load_config()
    if not cfg.get("enabled"):
        log.debug("memory: graphiti disabled, skipping store_session")
        return

    client = _build_client(cfg)
    group_id = cfg["group_id"]

    try:
        for i, msg in enumerate(messages):
            if not isinstance(msg.get("content"), str) or not msg["content"].strip():
                continue
            role = "Fred" if msg["role"] == "user" else "YANA"
            await client.add_episode(
                name=f"{session_id}-msg-{i}",
                episode_body=f"{role}: {msg['content']}",
                source=EpisodeType.text,
                source_description=f"YANA session {session_id}",
                reference_time=datetime.now(datetime.UTC),
                group_id=group_id,
            )
        log.debug("memory: stored %d messages -> %s", len(messages), session_id)
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
    if not cfg.get("enabled"):
        return ""

    client = _build_client(cfg)
    try:
        results = await client.search(
            query,
            group_ids=[cfg["group_id"]],
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
    cfg = _load_config()
    if not cfg.get("enabled"):
        return

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
    cfg = _load_config()
    if not cfg.get("enabled"):
        return ""

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
