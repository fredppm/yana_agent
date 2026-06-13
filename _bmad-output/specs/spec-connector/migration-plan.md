# Connector Migration Plan

Migration from Python-class backends to MCP server backends. Garmin and Google Calendar are the validation connectors — they prove the pattern before any further migrations.

## Approach

Test-driven. Capture the current connector contract as regression tests → swap backends to MCP servers → verify tests pass → remove Python connector code.

## Phase 1 — Contract capture

Extend `orchestrator/tests/test_connectors.py` to record expected outputs for every Garmin and Calendar operation currently exercised in production use. These become the regression spec that must survive Phase 2 and Phase 3 intact.

Operations to cover at minimum: `steps_today`, `stress_level`, `last_run`, `sync` (Garmin); `events_today`, `create_event` (Calendar).

## Phase 2 — Garmin migration

1. Evaluate `eddmann/garmin-connect-mcp` against contract tests — verify it exposes all required operations with compatible return shapes.
2. Configure two local MCP server instances: one for Fred's credentials, one for Ana's (separate process per owner, matching the `garmin_fred` / `garmin_ana` manifest entries).
3. Implement MCP backend adapter in the YANA registry — routes `call(instance_id, operation, params)` to the appropriate MCP server process via Python MCP SDK.
4. Run contract tests against MCP backend — all must pass.
5. Remove `GarminActivityConnector` Python class from repo.

## Phase 3 — Google Calendar migration

1. Configure `google-calendar-mcp` (official Google) with existing OAuth credentials.
2. Run contract tests — all must pass.
3. Remove `GoogleCalendarConnector` Python class from repo.

## Phase 4 — HA backbone

1. Enable HA MCP server integration on local HA instance (2024.10+).
2. Implement HA event subscription via MCP for PULSE triggers (new Garmin activity, etc.).
3. Route RGB light connectors through HA service calls via MCP.
4. Verify existing PULSE test coverage passes.

## Phase 5 — Validation gate

Full `pytest` suite passes. No Garmin or Calendar Python connector code remains in the repo. The Python `@query`/`@command`/`@event` decorator path remains available for future custom connectors with no MCP equivalent.

## Rollback

Until Phase 2 step 5, the Python connector remains in the repo. If contract tests fail against the MCP backend, hold at the Python connector and file issues against the MCP server.
