"""
spikes/memory_zep.py — Graphiti-core + FalkorDB + Bedrock (via LiteLLM) spike.

Stack 100% self-hosted, zero custo de API gerenciada:
  - FalkorDB    → knowledge graph (Redis-compatible, leve)
  - LiteLLM     → proxy OpenAI-compatible → AWS Bedrock
  - graphiti-core → extração de entidades e relações

Setup:
    # 1. Garante que as credenciais AWS estão no ambiente
    #    (já devem estar se você usa Bedrock no YANA normalmente)

    # 2. Sobe FalkorDB + LiteLLM
    cd orchestrator/spikes
    docker-compose up -d

    # 3. Instala deps
    pip install graphiti-core

    # 4. Roda o spike
    python orchestrator/spikes/memory_zep.py

O que este spike demonstra:
  1. store_session()  — substitui sanctum_writer.write_sanctum() — sem bloqueio no close
  2. load_context()   — substitui leitura de BOND.md + MEMORY.md no boot
  3. Demo end-to-end  — sessão → armazenamento → busca na próxima sessão
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
# Config
# ---------------------------------------------------------------------------

GRAPHITI_URI = os.environ.get("GRAPHITI_URI", "bolt://localhost:7687")
GRAPHITI_USER = os.environ.get("GRAPHITI_USER", "falkordb")
GRAPHITI_PASS = os.environ.get("GRAPHITI_PASS", "")

LITELLM_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
LITELLM_MODEL = os.environ.get("LITELLM_MODEL", "bedrock-claude-haiku")  # haiku = barato pra extração

# group_id escopa dados por instância YANA
# YANA-Fred e YANA-Esposa teriam group_ids diferentes
GROUP_ID = "yana-fred"


LITELLM_EMBED_MODEL = os.environ.get("LITELLM_EMBED_MODEL", "bedrock-embed")


def _client() -> Graphiti:
    """Graphiti conectado ao FalkorDB via LiteLLM → Bedrock (LLM + embeddings)."""
    llm = OpenAIClient(
        config=LLMConfig(
            api_key="bedrock",      # LiteLLM não valida a key quando proxeia pro Bedrock
            base_url=LITELLM_URL,
            model=LITELLM_MODEL,
            small_model=LITELLM_MODEL,  # evita fallback para gpt-4.1-nano
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
# 1. Store session — substitui sanctum_writer.write_sanctum()
#
# Pega as mensagens da sessão e adiciona ao knowledge graph.
# Graphiti extrai entidades, relações e fatos via Bedrock (através do LiteLLM).
# Não bloqueia o close — caller pode fazer fire-and-forget.
# ---------------------------------------------------------------------------


async def store_session(messages: list[dict], session_id: str) -> None:
    """
    Adiciona mensagens da sessão ao knowledge graph.

    Substitui sanctum_writer.write_sanctum(). O close da sessão não espera
    esta função — pode ser disparada como task em background.

    Args:
        messages: lista de {"role": "user"/"assistant", "content": "..."}
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
# 2. Load context at session start — substitui leitura de BOND.md + MEMORY.md
# ---------------------------------------------------------------------------


async def load_context(
    query: str = "quem é Fred, o que está acontecendo na vida dele agora",
) -> str:
    """
    Busca memória relevante para injetar no system prompt da YANA.

    Substitui a leitura dos arquivos do sanctum em core.py.
    Graphiti retorna fatos com temporalidade — fatos obsoletos são marcados.

    Returns:
        Bloco de texto para appender ao system prompt.
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
# 3. Setup — roda uma vez para criar índices no FalkorDB
# ---------------------------------------------------------------------------


async def setup() -> None:
    """Cria índices e constraints no FalkorDB. Idempotente."""
    client = _client()
    await client.build_indices_and_constraints()
    await client.close()
    print("[graphiti] índices criados no FalkorDB")


# ---------------------------------------------------------------------------
# Demo — fluxo end-to-end
# ---------------------------------------------------------------------------


async def demo() -> None:
    print("=== Graphiti + FalkorDB + Bedrock (LiteLLM) Spike ===\n")

    print("0. Setup índices no FalkorDB...")
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

    print(f"\n1. Armazenando sessão {session_id}...")
    await store_session(fake_session, session_id)

    print("\n   aguardando extração de entidades...")
    await asyncio.sleep(3)

    print("\n2. Carregando contexto para próxima sessão...")
    context = await load_context("o que Fred tem pendente e o que está acontecendo com ele")
    print(context or "(sem resultados ainda)")

    print("\n3. Buscando fato específico...")
    stripe = await load_context("entrevista Stripe")
    print(stripe or "(não encontrado)")

    print("\n=== Spike completo ===")
    print("\nSe funcionou, próximos passos:")
    print("  1. Substituir sw.write_sanctum() por store_session() em main.py:on_exit")
    print("  2. Injetar load_context() no system prompt em core.py:load_system_prompt()")
    print("  3. Avaliar usar haiku para extração e sonnet só para conversas")
    print("  4. Planejar migração do sanctum markdown existente para o graph")


if __name__ == "__main__":
    asyncio.run(demo())
