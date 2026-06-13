---
id: SPEC-connector
version: 2
companions:
  - connector-api.md
  - migration-plan.md
sources:
  - ../../brainstorming/brainstorming-session-2026-06-11-1.md
  - ../../brainstorming/brainstorming-session-2026-06-13-1.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale this contract intentionally omits.

# YANA Connector Architecture

## Why

YANA needs to interact with heterogeneous external systems — fitness trackers, calendars, smart home devices, health APIs — in a scalable, uniform way. The connector architecture provides a plug-in contract any external system can implement, enabling CAP-6 (home automation, PULSE autonomous monitoring) from SPEC-yana.

The LLM-facing interface — a meta-tool gateway with two-level manifest — keeps token cost fixed regardless of connector count and is architecturally superior to direct MCP tool registration for YANA's scale. Behind this interface, connector backends are preferentially sourced from the MCP server ecosystem (community and official servers) rather than built from scratch. Custom Python connectors are reserved for integrations with no MCP equivalent.

## Capabilities

- id: CAP-1
  intent: Any connector declares the queries (read state), commands (change state), and optionally events (push notifications) it supports, together with typed input/output schemas and AI-readable descriptions. The declared contract is independent of the backend implementation.
  success: A `GarminActivity` connector (MCP-backed) and a `GoogleCalendar` connector (MCP-backed) each satisfy the contract and YANA calls both through the same `call(instance_id, operation, params)` interface without connector-specific branching.

- id: CAP-2
  intent: The system distinguishes connector type (abstract contract), connector instance (named registry entry with optional owner), and connector backend (MCP server reference or Python class) as three independent layers.
  success: Two `GarminActivity` instances — "Garmin do Fred" (`owner: fred`) and "Garmin da Ana" (`owner: ana`) — coexist in the manifest, each backed by a separate local MCP server process with its own credentials. The AI addresses each by instance id and correctly attributes data to the right person via owner context.

- id: CAP-3
  intent: The AI receives only a lightweight manifest (instance name + one-line description) at session start and loads the full connector contract on demand when about to use a specific connector.
  success: With 20 registered connectors, the system prompt grows by at most one line per connector relative to a system with 5. Adding a new connector requires no system-prompt edit.

- id: CAP-4
  intent: A connector backend is declared as either an MCP server reference (preferred — for services with existing community or official MCP servers) or a Python class with `@query`, `@command`, and `@event` decorators (fallback — for custom integrations with no MCP equivalent). The registry routes calls to the correct backend transparently; the LLM-facing interface is identical in both cases.
  success: The Garmin connector routes calls to a local `garmin-connect-mcp` process. The Google Calendar connector routes calls to a local `google-calendar-mcp` process. A hypothetical custom connector with no MCP equivalent routes to a Python class. All three satisfy the same `call(instance_id, operation, params)` interface. A connector declared as MCP-backed requires no Python connector code in the YANA repo.

- id: CAP-5
  intent: The framework validates call params against the declared input schema before invoking the backend. All calls return a typed envelope `{ ok, data?, error? }` so the AI distinguishes "empty data" from "connector failure".
  success: Sending wrong param types to a command returns `{ ok: false, error: "validation_error" }` before the backend is invoked. An unavailable connector returns `{ ok: false, error: "unavailable" }` rather than an unhandled exception or null.

- id: CAP-6
  intent: The LLM invokes any registered connector operation through a fixed-size tool surface — the number of LLM-exposed tools does not grow with connector or operation count.
  success: With 20 registered connectors totaling 100+ operations, the tool list in the LLM context contains at most 2 entries. YANA calls `call_connector("garmin_fred", "steps_today", {})` and receives the `ConnectorResult` data in the same conversation turn.

- id: CAP-7
  intent: Home Assistant is the backend for home device connectors — devices that have no dedicated MCP server (lights, switches, thermostats). Services with their own dedicated MCP server (Garmin, Google Calendar) connect directly via that MCP server; HA is not in their path.
  success: An RGB light connector routes `set_color` commands through HA service calls via MCP — no custom Python class required. A Garmin connector routes `steps_today` directly to `garmin-connect-mcp`, not through HA. The two paths are independent and do not share infrastructure.

## Constraints

- The LLM-facing tool surface is fixed at 2 tools (`call_connector`, `get_connector_contract`) regardless of connector or operation count.
- MCP-backed connectors are the default. Python class connectors are the exception, reserved for integrations with no published MCP server equivalent.
- Garmin Connect and Google Calendar implementations MUST be backed by community/official MCP servers — not custom Python. These are the two validation connectors for the migration.
- Connector backend selection (MCP vs Python) is a per-connector-type configuration decision declared in the manifest, not a per-call decision.
- Credentials and auth belong to the backend (MCP server process or Python class implementation), never to the YANA manifest or contract layer.
- Every query, command, and event must carry an AI-readable `description`. Schema alone is not sufficient for AI consumption.
- Input schema (params) and output schema (returns: type, unit?, format?) are required on every query and command.
- `owner` is optional on ConnectorInstance. Generic connectors omit it; personal connectors (health, calendar) declare it.
- The lightweight manifest is always present in the LLM system prompt at session start.
- MCP server processes are local — no cloud-hosted MCP servers for personal data connectors.
- No inheritance between connector types. Each type declares its capabilities independently.

## Non-goals

- Custom Python connectors for Garmin Connect or Google Calendar — MCP servers exist for both.
- A "force sync" operation on Garmin — the existing `sync` command was internal cache invalidation, not a real device sync. MCP servers manage their own connection lifecycle.
- Event bus or message broker infrastructure at the YANA connector layer — HA handles events via WebSocket.
- One LLM tool per connector operation (direct MCP tool registration without the meta-tool gateway).
- Connector versioning or backward-compatibility contracts between schema versions.
- Sub-second latency or real-time streaming guarantees.
- Multi-tenant or multi-household connector sharing beyond the single-household model.
- Filesystem auto-discovery of connector implementations — backends are explicitly declared in the manifest.

## Success signal

Fred asks "quanto andei hoje?" by voice. YANA reads the lightweight manifest, identifies `garmin_fred`, loads the `GarminActivity` contract on demand (fetched from the local `garmin-connect-mcp` process), calls `call("garmin_fred", "steps_today", {})`, receives `{ ok: true, data: 8423, unit: "steps/day" }`, and responds "Você andou 8.423 passos hoje" — correctly attributing data to Fred via owner context. The `garmin-connect-mcp` process handles Garmin auth independently; no auth code exists in the YANA repo for this connector.

A second signal: Fred says "apaga a luz da sala". YANA calls `call("rgb_sala", "set_color", { color: "off" })`, which routes through the HA MCP server. No Python connector class exists for the light. Garmin data in the same session routes directly to `garmin-connect-mcp` — HA is not in that path.

## Assumptions

- `eddmann/garmin-connect-mcp` (or equivalent community server) exposes the operations currently in production use (`steps_today`, `stress_level`, `last_run`, `sync`) — to be validated against the existing test suite before removing the Python connector.
- The Python MCP SDK provides sufficient client primitives to manage local MCP server processes (stdio-based) without custom transport code in YANA.
- HA MCP server (official, 2024.10+) exposes adequate entity and service surface for home device commands (lights, switches). Garmin and Calendar do not route through HA.
- Migration is test-driven: `test_connectors.py` captures the current Python connector contract and must pass unchanged after backends are swapped to MCP (see `migration-plan.md`).
- Python class connectors remain valid for YANA-specific integrations with no MCP equivalent; this capability is not removed, only demoted to exception status.
- `owner` values reference person identifiers defined in SPEC-yana CAP-8 (voice profile mapping), not free strings.
- `ConnectorResult` envelope errors are strings from a finite set: `"timeout"`, `"auth"`, `"unavailable"`, `"validation_error"` — open to extension.
