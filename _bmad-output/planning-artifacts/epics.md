---
stepsCompleted: [1, 2]
inputDocuments:
  - _bmad-output/specs/spec-yana-programmer-mode/SPEC.md
  - _bmad-output/specs/spec-yana-programmer-mode/design-principles.md
partyModeReview: 2026-06-13
partyModeIssuesResolved:
  - Sprint 0 added (engine abstraction + decision-point taxonomy before any feature work)
  - NFR4 moved from Epic 3 to Epic 1 (voice/text mode is session setup, not methodology routing)
  - Worktree creation ordering hardened (after clarification, before engine dispatch)
  - Decision-point taxonomy made a deliverable artifact (Story 0.2) before filter implementation
  - Sad path ACs required explicitly in worktree lifecycle story
  - Handoff contract defined by engine.py abstraction in Sprint 0
---

# yana_agent - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for yana_agent, decomposing the requirements from SPEC-yana-programmer-mode into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: YANA routes development requests to an interchangeable coding engine without Fred changing tools or re-establishing context. (CAP-1)
FR2: Before routing, YANA surfaces missing or ambiguous requirements as explicit questions — never fills gaps silently. If Fred does not clarify, the process stops. (CAP-2)
FR3: YANA operates as the conversational interface to Fred's active development methodology (BMAD, SpecKit) without owning or controlling its flow. (CAP-3)
FR4: Fred receives from YANA only what requires a human decision. Technical output stays in the engine layer. (CAP-4)

### NonFunctional Requirements

NFR1: Coding engine integration is modular and configurable — same pattern as existing providers.py/providers.yaml. Engine declared in config, not hardcoded. Claude Code is the initial engine.
NFR2: Each YANA programmer session maps to one git worktree. YANA manages the worktree lifecycle.
NFR3: YANA defines the decision-point filter (what surfaces to Fred vs. stays in engine). Not configurable per repo in this version.
NFR4: YANA operates in voice, text, or hybrid mode within the same session. Mode is set explicitly; YANA does not infer mode switches.
NFR5: YANA never makes autonomous changes to code, branches, or PRs. Every state change requires an explicit signal from Fred.

### Additional Requirements

- Integration protocol: Anthropic Agent SDK (Python) — no subprocess overhead, supports multi-turn sessions via --resume, structured outputs via --json-schema
- Built on top of existing YANA infrastructure: sanctum, session log, voice/text modes, providers.py pattern
- Five design principles from design-principles.md are guardrails: (1) YANA is interface, engine is executor; (2) context switches always explicit; (3) YANA exposes gaps never fills; (4) mitigation not protection; (5) eliminate autonomy and technical noise

### UX Design Requirements

N/A — no UX design document. Interface is conversational (voice/text); no visual UI in scope.

### FR Coverage Map

| FR/NFR | Epic | Stories |
|--------|------|---------|
| NFR1 (engine abstraction) | Epic 0 | 0.1 |
| NFR3 (decision-point taxonomy) | Epic 0 | 0.2 |
| NFR4 (voice/text mode) | Epic 1 | 1.1 |
| FR2 (clarification before routing) | Epic 1 | 1.2 |
| FR1 (route to engine) | Epic 1 | 1.3 |
| FR4 (filter to decision points) | Epic 1 | 1.4 |
| NFR5 (no autonomous changes) | Epic 1 | 1.2, 1.3 |
| NFR2 (one worktree per session) | Epic 2 | 2.1 |
| FR3 (engine runs methodology in worktree) | Epic 2 | 2.2 |

## Epic List

- **Epic 0: Foundation Sprint** — Engine abstraction layer and decision-point taxonomy. Prerequisite for all other epics. No user-visible features.
- **Epic 1: Core Session Loop** — Programmer mode activation, clarification, routing to engine, and decision-point filtering. Full CAP-1, CAP-2, CAP-4 delivery.
- **Epic 2: Worktree + Methodology Routing** — One worktree per session (YANA-managed), engine runs BMAD/SpecKit inside worktree so artifacts commit to git. Full CAP-3 delivery.

### Epic Dependencies

```
Epic 0 → Epic 1 → Epic 2
```

Epic 1 cannot start until Epic 0 Story 0.1 (engine.py abstraction) is merged.
Epic 1 Story 1.4 (filter) cannot start until Epic 0 Story 0.2 (taxonomy) is merged.
Epic 2 cannot start until Epic 1 Story 1.3 (routing) is functional.

