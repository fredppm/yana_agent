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

Config is read from environment variables (see .env.example).
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

import os

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def _to_group_id(profile_id: str) -> str:
    """Profile UUID is used directly as Graphiti group_id — stable and immutable."""
    return profile_id


from strings import t as _t


def _context_query() -> str:
    """Return the memory context query in the active conversation language."""
    return _t("memory_context_query")


def _load_config() -> dict:
    """Read memory config from environment variables.

    NEO4J_URI and LITELLM_URL default to localhost (neutral dev defaults).
    YANA_MODEL_MEMORY and YANA_MODEL_EMBED are required — no opinionated default.
    """
    model = os.environ.get("YANA_MODEL_MEMORY")
    if not model:
        raise EnvironmentError("YANA_MODEL_MEMORY env var is not set")
    embed_model = os.environ.get("YANA_MODEL_EMBED")
    if not embed_model:
        raise EnvironmentError("YANA_MODEL_EMBED env var is not set")
    return {
        "uri":         os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
        "user":        os.environ.get("NEO4J_USER", ""),
        "password":    os.environ.get("NEO4J_PASSWORD", ""),
        "litellm_url": os.environ.get("LITELLM_URL", "http://127.0.0.1:4000"),
        "model":       model,
        "embed_model": embed_model,
    }


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def _make_graphiti(cfg: dict):  # synchronous — just constructs the Graphiti object
    from graphiti_core import Graphiti
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.openai_client import OpenAIClient
    from openai import AsyncOpenAI

    llm_cfg = LLMConfig(
        api_key="bedrock",
        base_url=cfg["litellm_url"],
        model=cfg["model"],
        small_model=cfg["model"],
    )
    # max_retries=0: auth/network errors fail immediately instead of retrying 2x.
    # Without this, a 401 from Bedrock causes LiteLLM to retry, adding ~2s delay on startup.
    _openai_client = AsyncOpenAI(
        api_key="bedrock",
        base_url=cfg["litellm_url"],
        max_retries=0,
    )
    llm = OpenAIClient(config=llm_cfg, client=_openai_client)
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key="bedrock",
            base_url=cfg["litellm_url"],
            embedding_model=cfg["embed_model"],
        ),
        client=_openai_client,
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


async def _build_write_client(cfg: dict):
    """Build a Graphiti client ready for writes — ensures indices exist first."""
    client = _make_graphiti(cfg)
    await client.build_indices_and_constraints()
    return client


async def _close_client(client) -> None:
    """
    Close a Graphiti client and drain all async cleanup tasks it spawns.

    When client.close() runs, httpx/httpcore schedule internal teardown tasks
    via asyncio.ensure_future().  If asyncio.run() closes the loop before those
    tasks finish, Python logs "Task exception was never retrieved /
    RuntimeError: Event loop is closed".  Draining them here prevents that.
    """
    # Cancel tasks already pending (embeddings, Neo4j queries, …)
    for task in asyncio.all_tasks():
        if task != asyncio.current_task():
            task.cancel()
    # Close client — httpx spawns NEW cleanup tasks internally during close
    try:
        await asyncio.wait_for(client.close(), timeout=1.0)
    except Exception:
        pass
    # Gather (and cancel) any tasks spawned by close itself
    remaining = [t for t in asyncio.all_tasks() if t != asyncio.current_task()]
    if remaining:
        for t in remaining:
            t.cancel()
        await asyncio.gather(*remaining, return_exceptions=True)


# ---------------------------------------------------------------------------
# Core operations (async)
# ---------------------------------------------------------------------------


async def _generate_session_title(conversation_text: str, cfg: dict) -> str:
    """
    Ask the LLM for a concise session title (max 8 words).
    Uses the same LiteLLM proxy already configured for Graphiti.
    Returns empty string on any failure — always best-effort.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key="bedrock",
        base_url=cfg["litellm_url"],
        max_retries=0,
    )
    try:
        short = conversation_text[:1500]
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=cfg["model"],
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Give a concise title (max 8 words, no punctuation) "
                            "that summarises what this conversation was about. "
                            "Reply with ONLY the title.\n\n"
                            f"{short}"
                        ),
                    }
                ],
                max_tokens=25,
                temperature=0.3,
            ),
            timeout=15.0,
        )
        title = resp.choices[0].message.content.strip().strip('"').strip("'")
        return title[:80] if title else ""
    except Exception as exc:
        log.debug("memory: title generation skipped (%s: %s)", type(exc).__name__, exc)
        return ""
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def store_session(messages: list[dict], session_id: str) -> None:
    """
    Persist raw session messages in PostgreSQL and add a Graphiti episode.
    """
    import core
    import store
    from graphiti_core.nodes import EpisodeType

    cfg = _load_config()
    profile_id = core.get_active_profile() or "yana-default"
    group_id = _to_group_id(profile_id)

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

    # Persist session + messages in PostgreSQL — always, independently of Graphiti
    store.create_session_sync(
        session_id,
        profile_id,
        created_at,
        preview,
        json.dumps(messages, ensure_ascii=False),
    )

    # Add one Graphiti episode — best-effort; failure does not affect PostgreSQL storage
    if conversation_text:
        try:
            client = await _build_write_client(cfg)
            try:
                await client.add_episode(
                    name=session_id,
                    episode_body=conversation_text,
                    source=EpisodeType.text,
                    source_description=f"YANA session {session_id}",
                    reference_time=datetime.now(UTC),
                    group_id=group_id,
                )
                log.debug("memory: stored session episode -> %s", session_id)
            finally:
                await _close_client(client)
        except Exception as exc:
            log.debug("memory: graphiti episode storage skipped (%s: %s)", type(exc).__name__, exc)

        # Generate a descriptive session title and update the preview — best-effort.
        # Runs after Graphiti regardless of whether episode storage succeeded.
        title = await _generate_session_title(conversation_text, cfg)
        if title:
            store.update_session_preview_sync(session_id, title)
            log.debug("memory: session title set -> %r", title)


async def load_context(query: str | None = None) -> str:
    """
    Retrieve relevant memory from Graphiti to inject into the system prompt.

    Returns a formatted markdown block, or empty string if unavailable.
    """
    import core

    if query is None:
        query = _context_query()

    cfg = _load_config()
    client = _make_graphiti(cfg)

    # Cancel the build_indices_and_constraints task that Graphiti.__init__ schedules
    # via create_task — we don't need it for reads and it competes with the search.
    for task in asyncio.all_tasks():
        if task != asyncio.current_task():
            task.cancel()

    profile_id = core.get_active_profile() or "yana-default"
    profile_gid = _to_group_id(profile_id)
    # Search only the profile group_id — UUID is the stable identifier
    search_group_ids = [profile_gid]
    try:
        # Search runs inside a background thread with a 30s outer budget, so 25s here
        # gives Bedrock/LiteLLM time to respond while still bounding the worst case.
        results = await asyncio.wait_for(
            client.search(query, group_ids=search_group_ids, num_results=15),
            timeout=25.0,
        )
    except TimeoutError:
        log.warning("load_context: search timed out after 25s")
        return ""
    except Exception as e:
        _msg = str(e).lower()
        if any(k in _msg for k in ("401", "authentication", "credentials", "unauthorized")):
            log.warning("load_context: auth error — skipping (check LiteLLM/Bedrock credentials)")
        else:
            log.warning("load_context failed (%s: %s)", type(e).__name__, e)
        return ""
    finally:
        await _close_client(client)

    if not results:
        return ""

    lines = ["---", "## Your context", ""]
    for fact in results:
        if hasattr(fact, "fact") and fact.fact:
            lines.append(f"- {fact.fact}")

    return "\n".join(lines) if len(lines) > 3 else ""


# ---------------------------------------------------------------------------
# Sync wrappers
# ---------------------------------------------------------------------------


def _install_graphiti_exception_handler(loop: asyncio.AbstractEventLoop) -> None:
    """
    Suppress expected asyncio shutdown noise from Graphiti/httpx cleanup tasks.

    Two variants occur in practice:
    - 'cannot schedule new futures after interpreter shutdown' — Graphiti's
      build_indices_and_constraints task is mid-flight when asyncio.run() tears down.
    - 'Event loop is closed' — httpx connection-pool cleanup tasks (spawned by
      client.close()) try to schedule work after the loop is already closed.

    Both are expected shutdown races with no actionable signal. Silence them here
    and log at DEBUG so the file handler captures them for posterity.
    """
    _SUPPRESS = frozenset(["cannot schedule new futures", "Event loop is closed"])

    def _handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        if isinstance(exc, RuntimeError) and any(s in str(exc) for s in _SUPPRESS):
            log.debug("memory: suppressed graphiti shutdown race: %s", exc)
            return
        loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)


def store_session_background(messages: list[dict], session_id: str) -> None:
    """
    Fire-and-forget: store session in a background thread.

    The TUI can close immediately. Thread is non-daemon so the process
    stays alive until indexing finishes (typically a few seconds).
    """

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _install_graphiti_exception_handler(loop)
        try:
            loop.run_until_complete(store_session(messages, session_id))
        except Exception as e:
            log.debug("memory: background store failed: %s", e)
        finally:
            loop.close()

    threading.Thread(target=_run, daemon=False, name="graphiti-store").start()


def load_context_sync(query: str | None = None, timeout: float = 5.0) -> str:
    """
    Synchronous wrapper for load_context with a timeout.

    Safe to call from sync code (e.g. core.load_system_prompt).
    Returns empty string on timeout or error — never raises.
    """
    result: list[str] = [""]

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _install_graphiti_exception_handler(loop)
        try:
            result[0] = loop.run_until_complete(load_context(query))
        except Exception as e:
            log.warning("load_context_sync failed (%s: %s)", type(e).__name__, e)
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result[0]
