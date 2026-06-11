# YANA — Roadmap

Companion to `SPEC.md`. **Princípio:** simples primeiro, valida, melhora depois.

## Fase 1 — YANA viva por voz (MVP)

**Gate de saída:** Fred consegue ter uma conversa por voz com YANA, ela persiste memória, e PULSE roda com pelo menos Google Calendar funcionando. First Breath acontece por voz.

| O que | Status | Notas |
|-------|--------|-------|
| Agent skill (`skills/agent-yana/`) | ✅ Pronto | Identidade, facets, capacidades, PULSE design |
| Voice layer: STT + TTS | ❌ próximo | Whisper (STT) + Piper/ElevenLabs (TTS) |
| Orchestrator (Python) | ❌ | Lê SKILL.md + sanctum, chama API, gerencia sessão |
| `providers.yaml` config | ❌ | Multi-model routing plugável |
| First Breath por voz | ❌ bloqueado | Precisa de voice layer + orchestrator |
| Google Calendar connector | ❌ | CAP-2 |
| Gmail connector | ❌ | CAP-7 email digest |
| Price watch connector | ❌ | CAP-5 + CAP-7 |
| PULSE scheduler | ❌ | Cron simples local |

## Fase 2 — Identificação por voz e mais connectors

**Gate de saída:** YANA distingue Fred da esposa por perfil de voz. Garmin e HA conectados.

| O que | Depende de |
|-------|-----------|
| Perfil de voz por pessoa | Fase 1 + decisão de biblioteca |
| Garmin connector (polling) | Fase 1 |
| Home Assistant connector (webhook) | Fase 1 |
| WhatsApp connector (rascunha + envia mensagens de texto) | Fase 1 |

## Fase 3 — YANA-Esposa e multi-usuário

| O que | Depende de |
|-------|-----------|
| Agent skill `agent-yana-f2` (nova alma) | Fase 2 |
| Memória compartilhada (arquivo YAML) | Fase 2 |

## Fase 4 — Hardening

| O que |
|-------|
| Docker container |
| Deploy na rede local ou nuvem |

## Próximo passo imediato

**Voice layer + Orchestrator** — os dois em paralelo pois se dependem:

1. Voice layer: Whisper para STT, Piper (local, gratuito) ou ElevenLabs (qualidade melhor) para TTS
2. Orchestrator: lê SKILL.md + sanctum, monta contexto, chama API escolhida, salva sessão
3. Conecta os dois: voz entra → STT → orchestrator → LLM → TTS → voz sai
