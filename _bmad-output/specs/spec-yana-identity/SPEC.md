---
id: SPEC-yana-identity
companions:
  - architecture.md
sources:
  - ../_bmad-output/brainstorming/brainstorming-session-2026-06-14-1600.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# YANA Identity — Owner, Workspace, and Multi-Profile Architecture

## Why

YANA currently models identity as static markdown files (PERSONA.md, CREED.md, BOND.md) and a flat, single-instance `group_id` string. This model breaks under three pressures that are already real: (1) identity evolves over time but files are snapshots; (2) a machine may serve more than one person (Fred and Fernanda) or one person in distinct operational contexts (work, personal); (3) `group_id` is an opaque config value with no user-facing meaning. The opportunity is to replace the snapshot model with a two-layer, Graphiti-backed identity model that gives each YANA instance a durable, legible identity and scopes memory and connectors cleanly per context.

## Capabilities

- id: CAP-1
  intent: A user can navigate profiles and sessions from a single unified TUI screen — left/right switches between profiles (owner::context), up/down navigates sessions of the active profile.
  success: The TUI home screen shows the active profile's sessions; swiping left or right shifts to an adjacent profile with its own session list; selecting a session enters it with the correct persona and connector config loaded for that profile.

- id: CAP-2
  intent: The system maintains two distinct identity layers — Owner (persona, relationship, how YANA treats this person) and Workspace (memory scope, connector configuration) — identified by a structured `group_id` of the form `owner::context`.
  success: Two workspaces of the same owner (e.g. `fred::pessoal` and `fred::trabalho`) share the same YANA persona but have completely isolated Graphiti memory and connector configs; changing the active workspace changes what YANA knows and can do, not who she is to Fred.

- id: CAP-3
  intent: Owner identity (persona, values, relationship) lives in Graphiti at the owner-level group_id, replacing static markdown files (PERSONA.md, CREED.md, BOND.md).
  success: Removing PERSONA.md does not alter YANA's persona; persona is loaded from Graphiti owner nodes on every session start. A new YANA installation with no markdown files boots and behaves identically to one that migrated from files.

- id: CAP-4
  intent: A single First Breath conversation establishes both the owner identity and the first workspace in one flow, with no second separate setup step.
  success: After First Breath completes, Graphiti contains owner-level nodes (persona, values) and workspace-level nodes (operational context, first connector config), and `providers.yaml` contains the active `group_id` in `owner::context` format.

- id: CAP-5
  intent: A user with an existing owner profile can create additional workspaces through a short contextual conversation, without repeating the full First Breath.
  success: Creating `fred::trabalho` after `fred::pessoal` exists takes a focused conversation about the new operational context only; owner persona is inherited, not re-established.

- id: CAP-6
  intent: YANA detects its own state on launch and routes to the correct screen — no CLI flags, no documentation required to start.
  success: `python main.py` on a fresh install leads to First Breath; on an install with one profile leads to the session list; on an install with multiple profiles leads to the profile switcher. No `--init`, `--text`, or mode flags are required for the interactive path.

- id: CAP-7
  intent: A user can create disposable workspaces (e.g. `fred::test`) for experimentation and delete them from within the TUI without affecting other profiles.
  success: Deleting `fred::test` via the TUI removes its Graphiti data and connector config; `fred::pessoal` and `fred::trabalho` are unaffected. No files need to be touched — there are no workspace files to clean up.

## Constraints

- `group_id` format is `owner::context` where `owner` is a human identity slug and `context` is a free, lowercase slug chosen by the user (e.g. `fred::pessoal`, `fernanda::pessoal`, `fred::test`). No other format is valid.
- Owner persona is never duplicated per workspace — it lives once at the owner level and is referenced by all workspaces of that owner.
- Connector configuration is scoped per workspace; the same connector type (e.g. Google Calendar) may appear in multiple workspaces with different credentials.
- No authentication gate between profiles — separation is logical (Graphiti `group_id`), not credential-based. Physical access to the machine implies access to all profiles on it.
- All storage is self-hosted (Graphiti + Neo4j). No managed memory service.
- Static markdown sanctum files (PERSONA.md, CREED.md, BOND.md, MEMORY.md, CAPABILITIES.md, PULSE.md) are retired as the source of truth for identity once CAP-3 is implemented. No automatic import from files to Graphiti is built into the runtime — migration is an optional out-of-band script, not a product feature.

## Non-goals

- Password-based or token-based authentication between profiles.
- Cloud sync of profiles or workspaces across machines.
- Changes to `--headless`, `--pulse`, or `--programmer` CLI modes — those are separate concerns.
- Sensor layer integration (Garmin, Home Assistant, PS5) — separate backlog.
- Bayesian confidence scoring on memories — separate backlog.
- Real-time memory sharing between workspaces of the same owner.

## Success signal

Fred opens YANA on a machine that has `fred::pessoal` and `fred::trabalho`; the profile switcher appears, he selects `fred::trabalho`, and YANA greets him with her established persona but knows only work-context memory and has VTEX Calendar and Jira available as connectors. Fernanda opens YANA on the same machine, selects `fernanda::pessoal`, and interacts with a YANA that has a completely different persona calibrated to her. Neither user touches a config file or passes a CLI flag to reach their session.

## Assumptions

- Neo4j and Graphiti are already integrated (PR #26 baseline); this spec builds on that foundation.
- `providers.yaml` is the authoritative runtime config file; the active `group_id` lives there.
- The Textual TUI is the primary interactive surface; all profile management flows through it.
- Persona extraction from First Breath conversation is handled by the existing LLM routing (Bedrock via LiteLLM).

