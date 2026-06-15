---
id: SPEC-pulse
companions:
  - task-schema.md
  - ../spec-yana/SPEC.md
sources:
  - ../../brainstorming/brainstorming-session-2026-06-14-1400.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only.

# Pulse — YANA Autonomous Observation Engine

## Why

YANA's autonomous operation (CAP-7 in spec-yana) was designed before connectors existed — the current `--pulse` flag, `PULSE.md`, and `pulse-config.yaml` are placeholders without a real execution engine. Fred's concrete need: receive a daily newsletter summary from Gmail every morning without triggering YANA manually. This forces Pulse to become a real, runnable system — a standalone process that observes the world on Fred's behalf, executes tasks against connectors, and delivers results through YANA sessions. The opportunity is now because the first connector (Gmail) is arriving.

## Capabilities

- id: CAP-1
  intent: A standalone Pulse process loads task definitions, executes them at scheduled times against YANA connectors, and delivers results to a YANA session — independently of whether YANA is actively running.
  success: "`python -m pulse` starts, picks up a newsletter summary task scheduled for 10:00, invokes the Gmail connector at that time, generates a summary, and writes the result as a message to a YANA session persisted under `data/agent-yana/sessions/`."

- id: CAP-2
  intent: Tasks are defined with three fields (`observe`, `schedule`, `deliver`) sufficient for the runner to know what to monitor, when, and where to send the result.
  success: A YAML task with valid `observe`, `schedule`, and `deliver` fields is loaded, validated, and executed by the runner without additional runtime input.

- id: CAP-3
  intent: YANA creates, updates, and removes Pulse tasks through natural language conversation, writing the task config without Fred editing any file.
  success: Fred says "quero receber todo dia às 10h um resumo das newsletters do Gmail" and YANA produces a valid task entry in the Pulse config with no manual file editing required.

- id: CAP-4
  intent: Tasks that fail are retried with exponential backoff up to three attempts; final failure delivers an error notification to the Pulse session.
  success: A task that fails three consecutive times writes an error message to the Pulse session and stops retrying.

- id: CAP-5
  intent: Pulse delivers task results into a YANA session; if no session is active, Pulse creates one. That session persists in the normal session history and feeds the sanctum.
  success: After task execution, the result appears as a session under `data/agent-yana/sessions/` in the same format as a user-initiated session.

## Constraints

- Pulse is a separate executable (`python -m pulse`) — not a flag or mode of `main.py`. The existing `--pulse` flag may be removed.
- YANA is the sole operator of task configuration; Fred never edits the Pulse task file directly.
- Pulse does not call external services directly — it uses YANA connectors as its tool layer.
- MVP supports Fixed schedule mode only (explicit time in config). Adaptive/intent scheduling is post-MVP.
- Existing `PULSE.md`, `pulse-config.yaml`, and `--pulse` flag carry no backward compatibility obligation and may be replaced or removed.
- Distributed coordination across multiple Pulse instances is not in scope.
- Pulse writes session results directly to `data/agent-yana/sessions/` as files following the existing session format — no imports from the YANA orchestrator codebase.
- YANA communicates with Pulse exclusively via Pulse's localhost HTTP API. Pulse is the persistent process; YANA is the ephemeral caller.
- Task config lives at `data/agent-yana/pulse-tasks.yaml`.

## Non-goals

- Adaptive scheduling — Pulse learning timing patterns from observation (post-MVP).
- Result-driven criticality routing — YANA deciding urgent vs. summary delivery based on sanctum context (post-MVP).
- Multi-instance distributed coordination.
- OS-level push notifications (system tray, Windows toast).
- External delivery channels (email, Slack, WhatsApp) — YANA session is the only inbox.
- A UI or dashboard for task management.

## Success signal

Fred tells YANA "quero receber todo dia às 10h um resumo das newsletters do Gmail." YANA writes the task config. The Pulse process runs in the background, executes at 10:00, fetches newsletters via the Gmail connector, generates a summary, and writes it to a YANA session. Fred opens YANA and reads the summary without having asked for it.

## Assumptions

- Gmail connector (in development on `feat/gmail-connector`) will be available when Pulse is implemented.
- APScheduler or equivalent Python scheduling library is an acceptable dependency.
- "Pulse session" is a standard YANA session created programmatically by the runner — not a special session type.
- Pulse's localhost HTTP API port is fixed and known to YANA (e.g., configured in `connectors.yaml` or a Pulse-specific config).
