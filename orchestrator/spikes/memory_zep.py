"""
spikes/memory_zep.py — Graphiti-core + Neo4j + Bedrock (via LiteLLM) spike.

100% self-hosted stack, zero managed-service cost:
  - Neo4j        -> knowledge graph (Bolt protocol, port 7687)
  - LiteLLM      -> OpenAI-compatible proxy -> AWS Bedrock
  - graphiti-core -> entity and relation extraction

Setup:
    # 1. Ensure AWS credentials are in the environment
    #    (already set up if you use Bedrock for YANA normally)

    # 2. Start Neo4j + LiteLLM
    cd orchestrator/spikes
    docker-compose up -d

    # 3. Install deps
    pip install graphiti-core

    # 4. Run the spike
    python orchestrator/spikes/memory_zep.py

What this spike demonstrates:
  1. store_session()  -- replaces sanctum_writer.write_sanctum() -- no blocking on close
  2. load_context()   -- replaces reading BOND.md + MEMORY.md at boot
  3. End-to-end demo  -- session -> storage -> search in the next session
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_client import OpenAIClient
from graphiti_core.nodes import EpisodeType

# ---------------------------------------------------------------------------
# Config — override via environment variables
# ---------------------------------------------------------------------------

GRAPHITI_URI = os.environ.get("GRAPHITI_URI", "bolt://localhost:7687")
GRAPHITI_USER = os.environ.get("GRAPHITI_USER", "")
GRAPHITI_PASS = os.environ.get("GRAPHITI_PASS", "")

LITELLM_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
LITELLM_MODEL = os.environ.get("LITELLM_MODEL", "bedrock-claude-haiku")  # haiku = cheap for extraction
LITELLM_EMBED_MODEL = os.environ.get("LITELLM_EMBED_MODEL", "bedrock-embed")

# group_id scopes data per YANA instance — YANA-Fred and YANA-Wife have different group_ids.
# In production this comes from providers.yaml -> graphiti.group_id (see memory.py).
GROUP_ID = os.environ.get("YANA_GROUP_ID", "yana-fred")


def _client() -> Graphiti:
    """Build a Graphiti client connected to Neo4j via LiteLLM -> Bedrock."""
    llm = OpenAIClient(
        config=LLMConfig(
            api_key="bedrock",          # LiteLLM does not validate the key when proxying to Bedrock
            base_url=LITELLM_URL,
            model=LITELLM_MODEL,
            small_model=LITELLM_MODEL,  # prevent fallback to gpt-4.1-nano
        )
    )
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key="bedrock",
            base_url=LITELLM_URL,
            embedding_model=LITELLM_EMBED_MODEL,
        )
    )
    reranker = OpenAIRerankerClient(
        config=LLMConfig(
            api_key="bedrock",
            base_url=LITELLM_URL,
            model=LITELLM_MODEL,
        )
    )
    return Graphiti(
        GRAPHITI_URI,
        GRAPHITI_USER,
        GRAPHITI_PASS,
        llm_client=llm,
        embedder=embedder,
        cross_encoder=reranker,
    )


# ---------------------------------------------------------------------------
# 1. Store session — replaces sanctum_writer.write_sanctum()
#
# Takes session messages and adds them to the knowledge graph.
# Graphiti extracts entities, relations, and facts via Bedrock (through LiteLLM).
# Does not block on close — caller can fire-and-forget.
# ---------------------------------------------------------------------------


async def store_session(messages: list[dict], session_id: str) -> None:
    """
    Add session messages to the Graphiti knowledge graph.

    Replaces sanctum_writer.write_sanctum(). Session close does not wait
    for this function -- it can be dispatched as a background task.

    Args:
        messages: list of {"role": "user"/"assistant", "content": "..."}
        session_id: e.g. "2026-06-14_16-00-00"
    """
    client = _client()

    for i, msg in enumerate(messages):
        if not isinstance(msg.get("content"), str) or not msg["content"].strip():
            continue

        role = "Fred" if msg["role"] == "user" else "YANA"
        episode_body = f"{role}: {msg['content']}"

        await client.add_episode(
            name=f"{session_id}-msg-{i}",
            episode_body=episode_body,
            source=EpisodeType.text,
            source_description=f"YANA session {session_id}",
            reference_time=datetime.now(timezone.utc),
            group_id=GROUP_ID,
        )

    print(f"[graphiti] stored {len(messages)} messages -> session {session_id}")
    await client.close()


# ---------------------------------------------------------------------------
# 2. Load context at session start — replaces reading BOND.md + MEMORY.md
# ---------------------------------------------------------------------------


async def load_context(
    query: str = "who is Fred, what is happening in his life right now",
) -> str:
    """
    Search relevant memory to inject into YANA's system prompt.

    Replaces reading sanctum files in core.py.
    Graphiti returns facts with temporality -- stale facts are marked as such.

    Returns:
        Markdown block to append to the system prompt.
    """
    client = _client()
    results = await client.search(query, group_ids=[GROUP_ID], num_results=15)
    await client.close()

    if not results:
        return ""

    lines = ["## Memory\n"]
    for fact in results:
        if hasattr(fact, "fact") and fact.fact:
            lines.append(f"- {fact.fact}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. Setup — run once to create indexes in Neo4j
# ---------------------------------------------------------------------------


async def setup() -> None:
    """Create indexes and constraints in Neo4j. Idempotent."""
    client = _client()
    await client.build_indices_and_constraints()
    await client.close()
    print("[graphiti] indexes created in Neo4j")


# ---------------------------------------------------------------------------
# Demo — end-to-end flow
# ---------------------------------------------------------------------------


async def demo() -> None:
    print("=== Graphiti + Neo4j + Bedrock (LiteLLM) Spike ===\n")

    print("0. Setting up Neo4j indexes...")
    await setup()

    session_id = f"spike-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    fake_session: list[dict] = [
        {"role": "user", "content": "Oi YANA, tô num dia bem corrido"},
        {"role": "assistant", "content": "Oi Fred! Trabalho ou casa?"},
        {"role": "user", "content": "Trabalho. PR bloqueado há 3 dias esperando review"},
        {"role": "assistant", "content": "Entendi. Acompanho e te aviso amanhã cedo se não sair."},
        {"role": "user", "content": "Perfeito. Ah, semana que vem tenho entrevista na Stripe"},
        {"role": "assistant", "content": "Entrevista na Stripe — anoto. Quer que eu te ajude a preparar?"},
    ]

    print(f"\n1. Storing session {session_id}...")
    await store_session(fake_session, session_id)

    print("\n   waiting for entity extraction...")
    await asyncio.sleep(3)

    print("\n2. Loading context for next session...")
    context = await load_context("what does Fred have pending and what is happening with him")
    print(context or "(no results yet)")

    print("\n3. Searching for specific fact...")
    stripe = await load_context("Stripe interview")
    print(stripe or "(not found)")

    print("\n=== Spike complete ===")
    print("\nNext steps if it worked:")
    print("  1. Replace sw.write_sanctum() with store_session() in main.py:on_exit")
    print("  2. Inject load_context() into the system prompt in core.py:load_system_prompt()")
    print("  3. Evaluate using haiku for extraction and sonnet only for conversations")
    print("  4. Plan migration of existing sanctum markdown files into the graph")


if __name__ == "__main__":
    asyncio.run(demo())
