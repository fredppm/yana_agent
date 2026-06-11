---
id: SPEC-connector
companions:
  - connector-api.md
sources:
  - ../../brainstorming/brainstorming-session-2026-06-11-1.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# YANA Connector Architecture

## Why

YANA needs to interact with heterogeneous external systems — fitness trackers, calendars, smart home devices, health APIs — in a scalable, uniform way. Today the core has no mechanism to expose these external capabilities to the AI in a self-describing, discoverable form. Without a connector model, each integration is ad-hoc, the AI has no schema to reason against, and adding a new data source requires changes to the core. The connector architecture provides a plug-in contract any external system can implement, enabling CAP-6 (home automation, bureaucratic processes) and CAP-7 (PULSE autonomous monitoring) from SPEC-yana.

## Capabilities

- id: CAP-1
  intent: Any connector declares the queries (read state), commands (change state), and optionally events (push notifications) it supports, together with typed input/output schemas and AI-readable descriptions.
  success: A `GarminActivity` connector and a `GoogleCalendar` connector each satisfy the contract and YANA calls both through the same `call(instance_id, operation, params)` interface without connector-specific branching.

- id: CAP-2
  intent: The system distinguishes connector type (abstract contract), connector instance (named registry entry with optional owner), and connector implementation (pluggable Python class) as three independent layers.
  success: Two `GarminActivity` instances — "Garmin do Fred" (`owner: fred`) and "Garmin da Ana" (`owner: ana`) — coexist in the manifest. The AI addresses each by instance id, and the AI's response correctly attributes data to the right person by owner context.

- id: CAP-3
  intent: The AI receives only a lightweight manifest (instance name + one-line description) at session start and loads the full connector contract on demand when about to use a specific connector.
  success: A system with 20 registered connectors does not increase baseline context consumption relative to a system with 5. Adding a new connector to the manifest requires no system-prompt edit.

- id: CAP-4
  intent: A developer creates a connector by writing a Python class decorated with `@query`, `@command`, and `@event`. The framework derives the manifest entry and full contract from the decorators; no separate YAML contract file is required.
  success: A new connector (e.g., Spotify) written in a single Python file with decorators is automatically discoverable by the framework with its full schema, without any manual manifest authoring.

- id: CAP-5
  intent: The framework validates call params against the declared input schema before invoking the implementation. All calls return a typed envelope `{ ok, data?, error? }` so the AI distinguishes "empty data" from "connector failure".
  success: Sending wrong param types to a command returns a schema-validation error before the implementation is called. An unavailable connector returns `{ ok: false, error: "unavailable" }` rather than an unhandled exception or null.

## Constraints

- Connector contract is pure abstraction: credentials, endpoints, and connection details belong in the implementation layer only — never in the contract or manifest.
- No inheritance between connector types. Each type declares its capabilities independently.
- Events are an optional capability. Connectors without events rely on orchestrator-driven polling (PULSE); the connector itself has no notion of time or polling frequency.
- `call(instance_id, operation, params?)` is the sole call interface — uniform across all connector types, operations, and owners.
- Every query, command, and event must carry a natural-language `description` field. Schema alone is not sufficient for AI consumption.
- Input schema (params) and output schema (returns: type, unit?, format?) are both required on every query and command. A capability without a typed return is incomplete.
- `owner` is optional on ConnectorInstance. Generic connectors (smart home devices, weather) omit it. Personal connectors (health, calendar) declare it.

## Non-goals

- Event bus or message broker infrastructure at the connector layer.
- Inheritance hierarchy or shared base types between connector types.
- Connector-declared freshness or polling-frequency hints — polling schedule is PULSE config's responsibility.
- Sub-second latency or real-time streaming guarantees.
- Credential/authentication management — this is implementation-layer concern.
- Filesystem auto-discovery of connectors — instances are explicitly registered in the manifest.
- Multi-tenant or multi-household connector sharing beyond the single-household model.

## Success signal

Fred asks "quanto andei hoje?" by voice. YANA reads the lightweight manifest, identifies `garmin_fred` as the relevant instance, loads the `GarminActivity` contract on demand, calls `call("garmin_fred", "steps_today", {})`, receives `{ ok: true, data: 8423, unit: "steps/day" }`, and responds "Você andou 8.423 passos hoje" — correctly attributing the data to Fred (not Ana) via owner context. A second connector (`GoogleCalendar`) is also registered and callable via the same interface without any code change.

## Assumptions

- The PULSE scheduler is the correct place to configure polling frequency for connectors without event capability.
- Python decorators are the right DX target (vs. YAML-first or protocol-buffer schemas) for this project's contributor profile.
- Manifest is a YAML file loaded at session start; full contract is loaded as Python class introspection at call time.
- Google Calendar and Garmin are the two validation connectors for the initial implementation.
- `ConnectorResult` envelope errors are strings from a finite set: `"timeout"`, `"auth"`, `"unavailable"`, `"validation_error"` — open to extension.
- Connector Python files are discovered by scanning a designated folder (e.g. `connectors/`), not an explicit list in config.
- The format used to inject a full connector contract into AI context is an implementation detail of the framework — not a contract concern. Python introspection is the source of truth.
- `owner` values reference the same person identifiers defined for CAP-8 (voice profile to person mapping) in SPEC-yana. They are not free strings.
