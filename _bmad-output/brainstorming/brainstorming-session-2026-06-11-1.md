---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Scalable Connector Architecture for YANA Agent'
session_goals: 'Design a generic connector model that allows diverse connector types (Calendar, Wearable, APIs, IoT, etc.) to expose data and actions uniformly to the AI — extensible, scalable, MCP-inspired'
selected_approach: 'user-selected'
techniques_used: ['First Principles Thinking']
ideas_generated: [24]
context_file: ''
session_active: false
workflow_completed: true
---

## Session Overview

**Topic:** Scalable Connector Architecture for YANA Agent
**Goals:** Design a generic connector model that allows diverse connector types to expose capabilities uniformly to the AI

### Session Setup

Fred is thinking about how to build a connector system that:
- Starts with Google Calendar and Garmin as first connectors
- Is extensible to any future connector type
- Exposes data/actions to the AI in a structured way (possibly MCP-inspired: resources, tools, prompts)
- Is architecturally scalable — diverse types and styles of connectors

---

## Technique Execution — First Principles Thinking

### Ideas Generated (24 total)

**[Contrato #1]: Event-free Connectors**
_Concept:_ Connectors expose only queries and commands. Reactivity to events is not the connector's responsibility — it belongs to the PULSE/scheduler via polling. The Garmin connector only needs to answer "was there a new activity since T?"
_Novelty:_ Drastically simplifies the connector contract. The complexity of "when to act" stays in the orchestrator, not each connector.

**[Contrato #2]: Connector-Declared Freshness** *(evoluiu e foi descartado)*
_Concept:_ Connector declares expected data frequency as metadata. System auto-configures polling per resource.
_Novelty:_ Discarded — nobody knows the right value, problem delegated to PULSE.

**[Contrato #3]: Events como Capability Opcional**
_Concept:_ Events are not mandatory in the base contract — they are a capability the connector declares or not. Connectors without events fall back to polling. Connectors with events register a handler.
_Novelty:_ The model doesn't force all connectors to support push. Complexity exists only where necessary.

**[Contrato #4]: Freshness como Fallback de Polling** *(descartado)*
_Concept:_ If connector declares events, freshness is ignored. If not, freshness hints guide polling frequency.
_Novelty:_ Discarded — leaky abstraction, nobody knows the right value.

**[Contrato #5]: Timing é Problema do Orquestrador**
_Concept:_ The connector has no notion of time or frequency. It only answers queries and executes commands when called, or pushes events when capable. When to call is 100% the PULSE/orchestrator's decision.
_Novelty:_ Clear separation of concerns — connector is stateless regarding time. Simpler to implement and test.

**[Contrato #6]: Queries com Schema de Retorno Tipado**
_Concept:_ Each query declares not just what params it accepts, but the shape of what it returns — scalar, object, list. The AI reads this before calling and knows how to interpret the result.
_Novelty:_ The AI doesn't need to infer response format at runtime. Reduces hallucination about data structure.

**[Contrato #7]: Schema = Tipo + Unidade Opcional + Formato Opcional**
_Concept:_ Each query declares: the primitive return type, and optionally a unit of measure (for physical quantities) and an encoding format (for composite types). The three are independent — boolean has no unit or format, RGB has format but no unit.
_Novelty:_ Avoids forcing "unit" on things that don't have one — the contract is honest about the nature of the data.

**[Contrato #8]: Connector como Contrato AI-First**
_Concept:_ Everything in the connector — queries, commands, events — has a natural language `description` field. Not documentation for humans, it's what the AI reads to decide when and how to use each capability. The connector is self-describing for the AI.
_Novelty:_ The difference from a normal SDK: the contract is designed to be consumed by an LLM, not code. The description is as important as the schema.

**[Identidade #9]: Connector Específico por Capacidade**
_Concept:_ A generic "Smart Home connector" would be useless — the AI wouldn't know what it can do. Connectors are specific: `SimpleLight`, `RGBLight`, `GarminActivity`, `GoogleCalendar`. What unites them is the standard contract format, not a common category.
_Novelty:_ Granularity at the right level — not so generic the AI gets lost, not so specific it becomes just another API.

**[Identidade #10]: Sem Herança — Composição por Contrato**
_Concept:_ Connectors don't inherit from each other. If two connectors share something (e.g., on/off), each declares independently. What unites them is the contract format, not a type hierarchy.
_Novelty:_ Keeps the model simple and easy to implement. Inheritance can come later if there's concrete gain — not before.

**[Discovery #11]: Dynamic Connector Registry**
_Concept:_ The AI doesn't receive all connectors in the system prompt. There's a registry the AI queries on demand — "what connectors do I have?" or "is there a connector that does X?". Only loads the full contract when about to use it.
_Novelty:_ System scales to dozens of connectors without exploding context. The AI operates with the minimum necessary.

**[Discovery #12]: Two-Level Connector Discovery**
_Concept:_ Level 1 — system prompt has a lightweight manifest: just `name` + one-line `description` per connector. Level 2 — when AI decides to use a connector, loads the full contract (queries, commands, schemas) on demand.
_Novelty:_ AI always knows what exists without saturating context. Context cost is proportional to use, not catalog size.

**[Identidade #13]: Connector Type + Named Instance**
_Concept:_ The system distinguishes type (contract, capabilities) from instance (name, context, specific configuration). Multiple instances of the same type coexist in the manifest with unique ids and names. The AI resolves which to use by explicit name or context.
_Novelty:_ Solves the multiple lights problem without creating new types. The AI talks to instances, not types.

**[Identidade #14]: Context-Aware Instance Resolution**
_Concept:_ When command is ambiguous (no explicit target), the AI uses context — location, time, habits — to choose the most likely instance. When explicit, resolves by name directly.
_Novelty:_ The AI doesn't ask for confirmation every time. It acts with the most reasonable instance and user corrects if wrong.

**[Implementação #15]: Connector é Abstração Pura**
_Concept:_ The connector defines WHAT — what it exposes, what it accepts, what it returns. The HOW — how it connects to Garmin, which endpoint, which credential — is the implementation's problem, not the contract's. The instance in the manifest only needs `id`, `name`, `description`. Technical configuration stays separate.
_Novelty:_ The connector contract is protocol-agnostic. The same `GarminActivity` type can connect via REST API, Bluetooth, file export — the contract doesn't change.

**[Implementação #16]: Type → Instance → Implementation como Camadas Separadas**
_Concept:_ Three independent layers. The type is stable — rarely changes. The instance is configuration — which connectors the user has. The implementation is pluggable code — how each type connects to the real world. Adding a new provider doesn't change the contract.
_Novelty:_ You can have two `GarminActivity` implementations — one via official API, another via GPX file export — without changing anything in type or instances.

**[Implementação #17]: Call Interface Uniforme**
_Concept:_ All AI interaction with any connector uses the same form: `call(instance_id, operation, params?)`. Simple, predictable, easy to log and debug. The AI doesn't need to learn a different interface for each connector.
_Novelty:_ Total uniformity — the same mechanism serves query ("how much did I walk?"), command ("turn on light"), and event subscription.

**[Implementação #18]: Connector como Python Puro**
_Concept:_ Writing a connector is writing normal Python. The developer has full freedom of implementation — requests, SDKs, files, Bluetooth, whatever is needed. The framework doesn't restrict the HOW.
_Novelty:_ Unlike declarative systems (YAML, pure JSON Schema) — code is the source of truth. Logic can be as simple or complex as the case requires.

**[Implementação #19]: Decorators como Contrato — Código é a Fonte da Verdade**
_Concept:_ The connector contract emerges from decorators in Python code. `@query`, `@command`, `@event` declare capabilities alongside the implementation. The framework reads decorators and automatically builds the manifest and full schema.
_Novelty:_ Zero separate file to declare the contract. Developer writes once, in the right place. Refactored the method → contract updated automatically.

**[Capabilities #20]: Event Decorator com Callback Interno**
_Concept:_ The connector with `@event` assumes responsibility for detecting when the event occurs — internally can use polling, webhook, stream, whatever. When detected, calls a system callback. The orchestration layer doesn't know or care about the internal mechanism.
_Novelty:_ The event contract is always the same on the system side. Detection complexity is encapsulated in the connector.

**[Contrato #21]: Input Schema no Contrato — Validação Before Call**
_Concept:_ Queries and commands declare not just what they return but what they accept — name, type, required/optional, expected format. The framework validates params before calling the implementation. If AI sends `{ color: "red" }` and schema expects `[number, number, number]`, fails with clear error before reaching the code.
_Novelty:_ AI gets immediate feedback and can correct without retrying against the external API. Contract errors don't reach the implementation.

**[Identidade #22]: Connector com Owner Context**
_Concept:_ Each ConnectorInstance declares an optional `owner` — who it belongs to. Can be the user, a family member, an environment (home, work). This contextualizes how the AI uses and talks about the data, and directs which credential the implementation uses.
_Novelty:_ The AI doesn't need to infer "whose data is this" — the manifest makes it explicit. "Fred's Garmin" and "Ana's Garmin" are different instances with different owners of the same type.

**[Identidade #23]: Owner como Campo Opcional na Instância**
_Concept:_ `owner` is optional metadata on ConnectorInstance. Generic connectors (smart home, weather, Spotify) don't declare owner. Personal connectors (health, calendar, finances) declare whose they are. The AI uses this to contextualize language and access.
_Novelty:_ Without forcing a complex permissions model — most work without owner. Complexity exists only where necessary, same as the events model.

**[Contrato #24]: Return Explícito de Falha**
_Concept:_ Calls always return an envelope — `{ ok: true, data: ... }` or `{ ok: false, error: "timeout" | "auth" | "unavailable" }`. The AI never receives ambiguous null — it can distinguish "data is empty" from "connector failed".
_Novelty:_ The AI can reason about failures: "couldn't check Garmin right now, try later" instead of silently assuming zero.

---

## The Complete Model

```
ConnectorType {
  queries:  [ Query ]
  commands: [ Command ]
  events?:  [ Event ]        // optional capability
}

Query / Command {
  name:        string
  description: string        // natural language for AI
  params?: {
    [name]: {
      type:      "boolean" | "number" | "string" | "array" | "object"
      required:  boolean
      format?:   string
      unit?:     string
    }
  }
  returns: {
    type:    "boolean" | "number" | "string" | "object" | "list"
    unit?:   string          // "bpm", "steps/day", "km"
    format?: string          // "rgb", "rgba", "iso8601"
  }
}

Event {
  name:        string
  description: string
  schema:      { ... }       // what the event payload looks like
}

ConnectorInstance {
  id:          string
  name:        string        // "Luz do Banheiro", "Garmin do Fred"
  description: string        // one line for AI manifest
  type:        ConnectorType
  owner?:      string        // optional — only for personal connectors
  // HOW to connect: in the Implementation, not here
}

ConnectorResult {
  ok:     boolean
  data?:  any
  error?: "timeout" | "auth" | "unavailable" | string
}
```

```python
# Python with decorators — implementation example
class GarminActivityConnector(Connector):

    @query(
        description="Passos dados hoje",
        returns={"type": "number", "unit": "steps/day"}
    )
    def steps_today(self) -> int:
        return garmin_api.get_steps()

    @query(
        description="Nível de stress atual (0-100)",
        returns={"type": "number", "unit": "stress_score"}
    )
    def stress_level(self) -> int:
        return garmin_api.get_stress()

    @event(description="Nova atividade de corrida registrada")
    def on_new_activity(self, callback):
        # implementation decides HOW to detect
        ...
```

```yaml
# Manifest (Level 1 — always in context)
connectors:
  - type: GarminActivity
    id: garmin_fred
    name: "Garmin do Fred"
    description: "Dados de saúde e atividade física do Fred"
    owner: fred

  - type: GoogleCalendar
    id: calendar_fred
    name: "Agenda do Fred"
    description: "Eventos e compromissos do calendário do Fred"
    owner: fred

  - type: RGBLight
    id: rgb_sala
    name: "Luz da Sala"
    description: "Luz RGB da sala de estar"

  - type: RGBLight
    id: rgb_banheiro
    name: "Luz do Banheiro"
    description: "Luz RGB do banheiro"
```

---

## Idea Organization and Prioritization

**Thematic Organization:**

| Theme | Ideas | Core Insight |
|---|---|---|
| Contrato Base | #1, #3, #5, #6, #7, #8, #21, #24 | Schema AI-first com input/output tipado e return envelope |
| Identidade e Instâncias | #9, #10, #13, #14, #22, #23 | Type vs Instance vs Owner — granularidade certa |
| Discovery | #11, #12 | Dois níveis — manifesto leve + contrato sob demanda |
| Capabilities Opcionais | #3, #5, #20 | Events e timing são opcionais — complexidade onde necessária |
| Implementação Python | #15, #16, #17, #18, #19 | Decorators, camadas, call uniforme |

**Prioritization Results (Fred's order):**
1. Contrato Base — fundação de tudo
2. Identidade e Instâncias — como coexistem
3. Discovery — como a AI encontra
4. Capabilities Opcionais — reatividade depois da base
5. Implementação Python — DX de criação

**Discarded in process:**
- Freshness hints (#2, #4) — nobody knows the right value, PULSE handles timing

---

## Action Plan

**P1 — Contrato Base**
1. Definir classes `Query`, `Command` com input/output schema
2. Definir `ConnectorResult` envelope `{ ok, data?, error? }`
3. Escrever connector Garmin stub com contrato completo pra validar

**P2 — Identidade e Instâncias**
1. Definir `ConnectorType` vs `ConnectorInstance`
2. Criar manifesto YAML com 3+ instâncias (Garmin Fred, Calendar Fred, Luz da Sala)
3. Validar distinção owner vs sem owner

**P3 — Discovery**
1. Implementar manifesto leve (name + description only)
2. Implementar loader de contrato completo sob demanda
3. Testar fluxo: AI lê manifesto → escolhe connector → carrega contrato

**P4 — Capabilities Opcionais**
1. Definir decorator `@event` e mecanismo de callback
2. Integrar com PULSE para polling em connectors sem events

**P5 — Implementação Python**
1. Implementar decorators `@query`, `@command`, `@event`
2. Auto-geração do manifesto a partir dos decorators
3. Validação automática de params via schema

---

## Session Summary

**24 ideias** geradas via First Principles Thinking — partindo do zero até um modelo arquitetural completo.

**Maior breakthrough:** A distinção Type → Instance → Implementation resolve elegantemente múltiplos connectors do mesmo tipo (3 luzes RGB, 2 Garmins) sem herança e sem complexidade desnecessária.

**Princípio dominante:** Complexidade opcional onde necessária — events, owner, unit, format — todos seguem o mesmo padrão: existem só onde fazem sentido.

**Validado contra casos reais:** Google Calendar (queries + commands + events encaixam perfeitamente), Smart Home (type vs instance resolve múltiplas luzes), Garmin (queries com unidades físicas, events para atividades).

