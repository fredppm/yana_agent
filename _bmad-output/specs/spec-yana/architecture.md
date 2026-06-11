# YANA — Architecture

Companion to `SPEC.md`. Descreve como as camadas do sistema se conectam.

## Camadas

```
┌─────────────────────────────────────────────────┐
│  Channels (como Fred fala com YANA)             │
│  Voice (STT/TTS) │ Text (CLI/API) │ HA trigger  │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│  Orchestrator (orquestrador Python)             │
│  - Lê SKILL.md + sanctum como contexto         │
│  - Roteia para o modelo certo via providers.yaml│
│  - Gerencia sessão e histórico                  │
│  - Aciona PULSE (scheduled + triggered)         │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│  LLM Providers (plugável via config)            │
│  Claude API │ OpenAI API │ outros               │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│  Agent Skill (skills/agent-yana/)               │
│  SKILL.md + sanctum (_bmad/memory/agent-yana/)  │
│  Facets │ Capabilities │ PULSE │ Memory         │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│  Integration Scripts (a construir)              │
│  google-calendar.py │ gmail.py │ garmin.py      │
│  home-assistant.py  │ price-watch.py            │
└─────────────────────────────────────────────────┘
```

## Config files (plugável, sem código)

```
providers.yaml       ← qual modelo para qual tipo de tarefa
pulse-config.yaml    ← frequência e enable/disable por tarefa PULSE
integrations.yaml    ← credenciais e endpoints de cada serviço
```

## PULSE execution

```
Scheduled (cron):
  orquestrador --headless → lê pulse-config.yaml → executa tarefas ativas

Triggered (event-driven):
  Home Assistant webhook → orquestrador --headless:trigger --source ha --event stock_low
  Garmin polling script  → orquestrador --headless:trigger --source garmin --event stress_high
```

## Multi-user (Fred + Esposa)

```
YANA-Fred:    skills/agent-yana/     + _bmad/memory/agent-yana/
YANA-Esposa:  skills/agent-yana-f2/  + _bmad/memory/agent-yana-f2/
Compartilhado: _bmad/memory/shared/  ← lista de compras, eventos, casa
```

## Deployment

- **Fase 1:** dev machine local de Fred (onde o Home Assistant também roda, ou máquina separada)
- **Fase 2:** container Docker na mesma rede local do HA
- **Fase 3:** migração opcional para nuvem (sem reescrita — apenas apontar providers.yaml para endpoints remotos)
