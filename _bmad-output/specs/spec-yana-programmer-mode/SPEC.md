---
id: SPEC-yana-programmer-mode
companions:
  - design-principles.md
sources:
  - ../../brainstorming/brainstorming-session-2026-06-13-2.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# YANA Programmer Mode — Architecture

## Why

Fred's current development workflow forces a context break every time he codes: open a terminal, explain the project context from scratch, work in isolation, repeat. YANA already knows Fred — his history, preferences, and ongoing work — but that knowledge stops at the conversation layer. The opportunity is to extend YANA into a frictionless development co-pilot: Fred states intent in natural language (voice or text), YANA translates it for a dedicated coding engine, and Fred receives only the decisions that require a human. This is a vision spec for a new YANA mode — making development feel like a continuous conversation rather than a series of tool switches.

## Capabilities

- id: CAP-1
  intent: Fred issues development requests through YANA; YANA routes them to an interchangeable coding engine (PI) without Fred changing tools or re-establishing context.
  success: Fred states a development request; YANA formulates it for the PI with full session context; the PI executes; Fred never opens a separate terminal or re-explains the project. Replacing the PI with a different engine requires no change to YANA's interface.

- id: CAP-2
  intent: Before routing a request to the coding engine, YANA surfaces missing or ambiguous requirements as explicit questions rather than silently filling the gaps.
  success: Given an underspecified request, YANA asks at least one clarifying question that would materially change the implementation before the engine writes any code. If Fred does not provide clarification, the process stops — YANA never infers intent and proceeds.

- id: CAP-3
  intent: YANA collects Fred's intent via conversation and hands it to the coding engine; the coding engine runs the active development methodology (BMAD, SpecKit, or equivalent) inside the worktree so that all generated artifacts (specs, PRDs, stories) land in the git history.
  success: During a BMAD or SpecKit run, YANA gathers Fred's inputs conversationally and passes them to the engine; the engine executes the methodology inside the worktree; the resulting artifacts are committed to the repo. YANA never runs the methodology herself. Swapping the methodology requires no redesign of YANA.

- id: CAP-4
  intent: Fred receives from YANA only what requires a human decision — errors needing a choice, ambiguities, completion signals. Technical output (build logs, test runner output) stays in the PI layer.
  success: Fred can follow a complete development cycle (request → code → PR-ready) without reading raw compiler output or stack traces unless he explicitly asks for them.

## Constraints

- YANA never makes autonomous changes to code, branches, or PRs. Every state change requires an explicit signal from Fred.
- The coding engine integration is modular and configurable — following the same pattern as `providers.py`/`providers.yaml` in the existing YANA architecture. The initial implementation uses Claude Code. The engine is declared in config, not hardcoded.
- YANA does not reinvent standard coding-engine behavior (error recovery, test interpretation, git operations). Those capabilities belong to the engine.
- Each YANA programmer session maps to one git worktree. YANA manages the worktree lifecycle; the engine operates within the worktree YANA provides. Worktree isolation will be hardened separately (issue #3).
- YANA defines the decision-point filter (what surfaces to Fred vs. stays in the engine layer). This filter is not configurable per repo in this version.
- YANA operates in voice mode, text mode, or hybrid within the same session. The mode is set explicitly; YANA does not infer mode switches.
- See `design-principles.md` for the five principles that govern trade-offs not covered by the constraints above.

## Non-goals

- Autonomous operation: YANA does not continue development work while Fred is unavailable (Phase 2, tracked in issue #7).
- UI/visual interface: no web app, sidebar, or thread visualization panel in this spec (tracked in issues #5 and #6).
- Mobile or ambient hardware: Bluetooth headset, phone, satellite mic are out of scope.
- Multi-user or team scenarios: this spec covers Fred as sole operator.
- YANA does not own, run, or enforce the development methodology — she collects Fred's inputs and hands them to the engine, which runs the methodology inside the worktree.

## Success signal

Fred completes a full development cycle — from an idea stated in natural language to a PR opened on GitHub — using only YANA as his interface, in either voice or text mode, without opening a separate terminal or re-explaining context mid-cycle.

## Assumptions

- YANA's existing sanctum, session log, voice/text, and providers infrastructure are the foundation; this spec extends them.
- Fred is the sole operator; no team or multi-user scenarios apply.
- Claude Code is the initial coding engine; the modular architecture allows future engines without redesign.
- The integration protocol is the **Anthropic Agent SDK** (Python) — no subprocess overhead, supports multi-turn sessions via `--resume`, structured outputs via `--json-schema`. Follows the same modular pattern as `providers.py`. Subprocess (`claude -p`) remains available as fallback for one-shot tasks.
