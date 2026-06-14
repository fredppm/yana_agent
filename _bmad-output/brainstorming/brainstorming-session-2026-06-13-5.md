---
stepsCompleted: [1, 2, 3, 4]
workflow_completed: true
ideas_generated: 10
inputDocuments: []
session_topic: 'Gmail connector para YANA'
session_goals: 'Design do contrato de API do connector Gmail — operações, shapes de dados, multi-conta, UX de voz, backend MCP'
selected_approach: 'ai-recommended'
techniques_used: ['Assumption Reversal', 'Cross-Pollination', 'SCAMPER Method']
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Fred
**Date:** 2026-06-13

## Session Overview

**Topic:** Gmail connector para YANA
**Goals:** Design do contrato de API do connector Gmail — operações, shapes de dados, multi-conta, UX de voz, backend MCP

### Session Setup

Connector Gmail MCP para YANA — acesso ao email real (respostas, compromissos, cobranças), separado do Newsletter Digest. Backend MCP-backed (mesmo padrão do GoogleCalendarMCPConnector). Fred tem 2 contas Google. Operações iniciais do issue: unread_summary, action_items, threads_by_sender, mark_read, label, draft_reply. Contexto: rotina matinal, resposta à pergunta "tem algo importante no email?".

## Technique Selection

**Approach:** AI-Recommended Techniques
**Analysis Context:** API design concreta com nuances específicas da YANA (voz, sanctum, multi-conta)

**Recommended Techniques:**

- **Assumption Reversal:** Derrubar suposições invisíveis sobre email para revelar constraints específicos do contexto YANA
- **Cross-Pollination:** Transferir padrões do GoogleCalendarMCPConnector, Garmin, e assistentes de voz para inventário de operações
- **SCAMPER Method:** Refinar a lista inicial do issue em feature list implementável

**AI Rationale:** Email é familiar demais — começar invertendo suposições abre espaço não óbvio. Cross-pollination do código existente acelera o design. SCAMPER fecha em decisões concretas de implementação.

## Idea Inventory (10 ideas)

### Theme 1: Connector Design Philosophy *(fundação — define tudo)*

- **#1 Importance Gate** — O connector não expõe "o que chegou" mas "o que precisa de Fred". A operação central é filtro de importância, não inbox dump.
- **#2 Dumb Connector, Smart YANA** — Connector Gmail intencionalmente burro: recebe email bruto, envia texto pronto. Toda inteligência (triagem, resposta) fica em YANA usando o sanctum. Connector é canal limpo.
- **#7 Remove action_items** — `action_items` eliminado. YANA extrai itens de ação do `body_text` usando sanctum context. Não duplica inteligência que YANA já tem.

### Theme 2: Data & Auth Architecture *(infraestrutura)*

- **#3 Gmail Primary as Importance Oracle** — YANA não inventa critério de triagem. Emails na aba Primary = importantes por definição. Zero lógica de triagem no connector — delega ao Gmail.
- **#4 One Instance Per Account, Isolated by Owner** — Dois connectors `GmailConnector` no `connectors.yaml` (`gmail_fred_work`, `gmail_fred_personal`), cada um com `owner: fred`. Framework faz o isolamento. Esposa registra os dela com `owner: esposa`.
- **#5 Email Format Contract** — `_format_email()` devolve `{"id", "thread_id", "from", "subject", "date", "snippet", "body_text"}`. HTML descartado no connector — YANA só recebe texto limpo.
- **#6 Configurable MCP Backend** — `mcp_command` no `connectors.yaml` define qual servidor Gmail MCP usar. Troca de backend sem tocar código — padrão transferido do GarminMCPConnector.

### Theme 3: Operations Contract *(API final)*

- **#8 search replaces threads_by_sender** — `threads_by_sender` substituído por `search(query: string)`. Fred diz "o que mandei pro contador no ano passado" — YANA traduz para sintaxe nativa do Gmail.

### Theme 4: Future Vision *(próximos passos)*

- **#9 Universal Communications Connector** — Abstração futura: `CommunicationsConnector` com `send_message(contact, text)`. YANA fala com pessoas, não com canais. Gmail é o primeiro backend.
- **#10 Gmail-first, Abstraction Later** — `GmailConnector` usa nomes genéricos onde possível. Issue #20 criada no GitHub para rastrear a abstração quando WhatsApp/Slack entrarem.

## Contrato Final de Operações

| Tipo | Operação | Parâmetros |
|---|---|---|
| query | `unread_important()` | — |
| query | `search(query)` | `query: string` |
| command | `send_message(to, subject, body)` | `to, subject, body: string` |
| command | `mark_read(email_id)` | `email_id: string` |
| command | `label(email_id, label_name)` | `email_id, label_name: string` |
| event | `new_important_email` | — |

## Decisões de Design

- **Triagem:** Gmail Primary como oráculo — zero lógica no connector
- **Inteligência:** YANA usa sanctum (BOND.md, MEMORY.md) para priorizar e rascunhar respostas
- **Multi-conta:** Uma instância por conta, `owner` faz isolamento via framework
- **Backend:** `mcp_command` configurável no `connectors.yaml`
- **Abstração futura:** Issue #20 — `CommunicationsConnector` multi-canal

## Session Insights

- O conector mais valioso não é o que traz mais dados — é o que filtra melhor
- YANA já tem o contexto de relacionamento no sanctum; o connector só precisa entregar o email bruto
- O padrão do `GoogleCalendarMCPConnector` transfere quase 1:1 para Gmail (auth, launcher, asyncio loop, format method)
- A abstração multi-canal (issue #20) emergiu naturalmente — Gmail é o tijolo 1
