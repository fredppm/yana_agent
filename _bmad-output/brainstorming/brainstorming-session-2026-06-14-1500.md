---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Fundação de Communications, Contacts e Credentials no YANA'
session_goals: 'Definir as abstrações corretas para CommunicationsConnector (pessoa → canal), sistema de Contacts (mapping pessoa/canal/endereço) e centralização de Credentials'
selected_approach: 'ai-recommended'
techniques_used: ['Question Storming', 'First Principles Thinking', 'Morphological Analysis']
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Fred
**Date:** 2026-06-14

## Session Overview

**Topic:** Fundação de Communications, Contacts e Credentials no YANA
**Goals:** Definir as abstrações corretas para os 3 pilares interligados

### Session Setup

Três pilares a explorar:
1. **CommunicationsConnector** — abstração pessoa → canal (issue #20)
2. **Contacts** — sistema de contatos com mapping pessoa/canal/endereço
3. **Credentials** — centralização e eliminação de duplicação no connectors.yaml

## Technique Selection

**Approach:** AI-Recommended
1. **Question Storming** — clareza do espaço do problema
2. **First Principles Thinking** — reconstrução limpa das abstrações
3. **Morphological Analysis** — mapeamento de opções arquiteturais

---

## Technique 1 — Question Storming

### Decisions Surfaced

**[Design #1]**: Contacts Are User-Scoped
_Concept_: Contacts belong to Fred, not to the system. If Ana uses YANA too, her "contador" is hers, not shared.
_Novelty_: Eliminates a whole class of multi-user collision bugs before they exist.

**[Design #2]**: Two Layers — Persona vs Contact
_Concept_: Persona = who someone is (name, context, relationship). Contact = how to reach them (channel + address). A Contact references a Persona. A Persona can exist without a Contact.
_Novelty_: Allows YANA to "know" someone before knowing how to reach them — opens door for photo recognition, richer context, future capabilities.

**[Design #3]**: Both Live in Config (YANA-editable)
_Concept_: Personas and Contacts live in a config file, not the sanctum. YANA can edit config too — the distinction sanctum/config is about data type (narrative vs structured), not about who edits.
_Novelty_: Keeps structured data queryable and schema-validated, separate from freeform sanctum narrative.

**[Design #4]**: Credentials Belong to the Connector
_Concept_: The channel field on a Contact ("email", "whatsapp") is just a pointer to which connector to use. Credentials are the connector's concern, not the contact's.
_Novelty_: Clean separation of concerns — people layer knows nothing about auth.

**[Design #5]**: Contact Resolution via Tool
_Concept_: `resolve_contact(name, channel=None)` — the LLM calls a tool, doesn't reason through the mapping itself. If channel is omitted, uses preferred channel from config.
_Novelty_: Deterministic, testable, debuggable. LLM doesn't hallucinate contact details.

**[Design #6]**: Preferred Channel in Config, Ambiguity → YANA Asks
_Concept_: Preferred channel is explicit in Persona config as fallback. When name is ambiguous (two Joãos), YANA asks Fred — never guesses.
_Novelty_: Predictable behavior, Fred stays in control.

**[Design #7]**: `app_credentials` vs `user_tokens`
_Concept_: Explicit naming distinction in connectors.yaml — `app_credentials` (OAuth client id/secret, shared per provider, never refreshed) vs `user_tokens` (per-connector token files, refreshed independently). Eliminates false impression that everything is the same kind of secret.
_Novelty_: Solves concurrency concern: tokens refresh independently, app credentials never change.

---

## Technique 2 — First Principles Thinking

### Fundamental Truths Established

**[Truth #1]**: Persona Is Any Real-World Entity
_Concept_: Persona = any person, company, or organization with relevance in Fred's life. Fred himself is a Persona. All Personas have contact channels, some richer than others.
_Novelty_: The logged-in user is not a special system entity — just another Persona with an owner role.

**[Truth #2]**: Channel = Communication Medium (1 or More Personas)
_Concept_: A channel is the medium by which one or more Personas exchange information. Types: text, voice, video. Channels are not limited to 1:1 — groups and lists are valid channels.
_Novelty_: YANA today can only generate text, so voice/video channels are receive-only for now.

**[Truth #3]**: Named Channel — Destination Without Persona
_Concept_: Large channels (#geral-vtex, mailing lists) are valid destinations without needing Persona resolution. YANA learns Named Channels through conversation — Fred doesn't configure manually.
_Novelty_: Eliminates the forced Persona requirement for group/broadcast communication.

**[Truth #4]**: app_credential vs persona_token
_Concept_: `app_credential` = YANA's identity with a service (Client ID/Secret). Immutable, YANA owns it. `persona_token` = a Persona's authorization for YANA to act on their behalf. Expires, renews, unique per Persona × service.
_Novelty_: Naming makes the distinction explicit in code and config — no more false equivalence.

**[Truth #5]**: CommunicationsConnector Is a Postman
_Concept_: Receives `(address, text)`, returns `(ok, delivery_status)`. Knows nothing about Personas, relationships, urgency, or context. Delivery confirmation is its only output beyond ok/fail.
_Novelty_: Absolute separation — people knowledge never leaks into the delivery layer.

---

## Technique 3 — Morphological Analysis

### Architectural Decisions

| Variable | Decision | Rationale |
|---|---|---|
| Where Personas/Contacts live | `personas.yaml` + `contacts.yaml` separate, indexed by ID | File-based DB today, real DB tomorrow — clean migration path |
| Contact resolution | `find_persona(name)` + `get_contact(persona_id, channel?)` as two separate tools | Maximum reuse — find_persona works for any Persona-linked data, not just comms |
| Credentials structure | `app_credentials.yaml` + `persona_tokens/` directory per connector | Clear ownership — YANA owns app creds, Persona owns tokens. Future: secret manager |
| CommunicationsConnector relation | Separate `CommunicationChannel` interface — connectors implement both `Connector` + `CommunicationChannel` | Flexible — read-only channels implement partial interface; explicit typing |

---

## Idea Organization and Prioritization

### Thematic Clusters

**Theme 1 — People Model**
- Persona = any real entity (person, company, org) — Fred himself is a Persona
- Two layers: Persona (who they are) + Contact (how to reach them) — indexed by ID
- Named Channel = destination without Persona (large groups) — YANA learns, Fred doesn't configure
- Ambiguity → YANA asks, never guesses

**Theme 2 — Communications Architecture**
- `CommunicationChannel` as separate interface — connectors implement both interfaces
- Two reusable tools: `find_persona(name)` + `get_contact(persona_id, channel?)`
- Preferred channel in config as fallback — YANA helps configure
- CommunicationsConnector is a postman: `(address, text)` → `(ok, status)`

**Theme 3 — Credentials**
- `app_credential` = YANA's identity with a service (immutable, YANA owns)
- `persona_token` = Persona × service authorization (expires, renews, unique per connector)
- `app_credentials.yaml` separate + `persona_tokens/` per file
- Designed for future migration to secret manager

### Breakthrough Concept

`find_persona()` as a universal primitive — not just for communication, but for any data tied to a Persona (Garmin data for Ana, tasks for Fred, photo recognition). The people layer becomes the common foundation for all connectors.

### Prioritized Implementation Order

| Priority | Item | Why First |
|---|---|---|
| 1 | `personas.yaml` + `contacts.yaml` + schema definition | Foundation for everything else |
| 2 | Rename `credentials_file` → `app_credential`, `token_file` → `persona_token` | Quick win — immediate clarity, zero risk |
| 3 | `CommunicationChannel` interface | Unlocks Gmail + future channels |
| 4 | `find_persona` + `get_contact` tools | Connects everything to the LLM |

---

## Session Summary

**16 design decisions** across 3 techniques (Question Storming, First Principles, Morphological Analysis).

**Key insight:** The three pillars are not independent — they share a common foundation. Personas are the load-bearing concept: credentials attach to Personas (persona_tokens), contacts ARE Personas, and the CommunicationsConnector serves Personas. Build the people layer first.

**Session completed:** 2026-06-14
