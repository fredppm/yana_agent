---
stepsCompleted: [1, 2, 3]
inputDocuments:
  - _bmad-output/specs/spec-yana-programmer-mode/SPEC.md
  - _bmad-output/specs/spec-yana-programmer-mode/design-principles.md
  - _bmad-output/planning-artifacts/epics.md
---

# yana_agent - Stories

## Epic 0: Foundation Sprint

> Prerequisite for all other epics. No user-visible features. Establishes the engine abstraction boundary and the decision-point taxonomy artifact that downstream stories depend on.

---

### Story 0.1 — Engine Abstraction Layer

**As a** YANA developer,
**I want** a modular engine abstraction (`orchestrator/programmer/engine.py`) with a declared interface,
**so that** all programmer mode features route through a stable contract and swapping engines requires no changes to YANA's interaction layer.

#### Acceptance Criteria

**AC-0.1.1 — Engine interface defined**
- `orchestrator/programmer/engine.py` defines an abstract base class `CodingEngine` with three methods:
  - `dispatch(request: EngineRequest) -> EngineSession` — sends a clarified request to the engine
  - `send(session: EngineSession, message: str) -> None` — sends a follow-up within an active session
  - `events(session: EngineSession) -> Iterator[EngineEvent]` — yields structured events from the engine
- `EngineRequest` carries: `prompt: str`, `context: str`, `worktree_path: Path`, `session_id: str`
- `EngineEvent` is a typed union: `DecisionPoint | ProgressUpdate | CompletionSignal | EngineError`

**AC-0.1.2 — Claude Code implementation**
- `orchestrator/programmer/engines/claude_code.py` implements `CodingEngine` using the Anthropic Agent SDK
- Engine is instantiated via `providers.yaml` engine section (see AC-0.1.3) — not hardcoded
- Subprocess fallback (`claude -p`) is available as an alternative implementation for one-shot tasks

**AC-0.1.3 — providers.yaml engine section**
- `orchestrator/config/providers.yaml` gains an `engines:` top-level key
- Format mirrors existing `providers:` structure: engine declared by name, config (model, flags) per engine
- Example:
  ```yaml
  engines:
    default: claude_code
    claude_code:
      sdk: anthropic_agent
      model: claude-sonnet-4-6
  ```
- `engine.py` reads this config via `load_providers()` — no new config loader needed

**AC-0.1.4 — Handoff contract documented**
- `orchestrator/programmer/engine.py` module docstring specifies the full handoff contract:
  - What YANA sends: clarified request text, sanctum context summary, worktree path, session ID
  - What engine returns: stream of `EngineEvent` — only `DecisionPoint` and `CompletionSignal` surface to Fred
  - What engine never returns to YANA: raw build logs, compiler output, stack traces (these stay in engine layer)

**AC-0.1.5 — Tests**
- Unit tests in `orchestrator/tests/test_engine.py` cover:
  - `EngineRequest` construction
  - `EngineEvent` type discrimination
  - `load_providers()` correctly reads `engines:` section
  - Engine instantiation from config (mock engine implementation)
- No Anthropic API calls in tests (mock the SDK client)

**AC-0.1.6 — Existing tests still pass**
- `python -m pytest orchestrator/tests/ -v` — all pre-existing tests green

---

### Story 0.2 — Decision-Point Taxonomy

**As a** YANA developer,
**I want** a written and code-level taxonomy of what constitutes a decision point vs. technical noise,
**so that** Story 1.4 (filter implementation) has an unambiguous contract to implement against and the filter is not defined ad hoc.

#### Acceptance Criteria

**AC-0.2.1 — Taxonomy artifact written**
- `orchestrator/programmer/decision_points.py` defines:
  ```python
  class DecisionPointKind(Enum):
      ERROR_REQUIRING_CHOICE = "error_requiring_choice"   # e.g. "file exists, overwrite?" 
      AMBIGUITY = "ambiguity"                              # engine hit underspec mid-task
      COMPLETION = "completion"                            # task done, ready for Fred's next step
      PERMISSION_REQUEST = "permission_request"            # engine needs explicit approval to proceed
      ENGINE_FAILURE = "engine_failure"                    # unrecoverable engine error requiring Fred
  ```
- `TechnicalNoise` is documented as: build logs, test runner stdout/stderr, compiler output, linter output, git operation confirmations. These never surface to Fred unless he explicitly requests them.

**AC-0.2.2 — EngineEvent uses taxonomy**
- `EngineEvent.DecisionPoint` in `engine.py` carries a `kind: DecisionPointKind` field
- `EngineEvent.ProgressUpdate` is explicitly typed as technical noise (Fred never sees it unless he asks)
- The filter in Story 1.4 will use `kind` to route events — this AC ensures the type exists before that story starts

**AC-0.2.3 — Tests**
- `test_decision_points.py`: verify all `DecisionPointKind` values are present, no typos, `EngineEvent` union covers all taxonomy entries

---

## Epic 1: Core Session Loop

> Programmer mode activation, voice/text setup, clarification gate, routing to engine, and decision-point filtering. Delivers CAP-1, CAP-2, CAP-4 end-to-end. Depends on Epic 0 complete.

---

### Story 1.1 — Programmer Mode Activation + Voice/Text Setup

**As** Fred,
**I want** to activate YANA's programmer mode with an explicit command and set my interaction mode (voice, text, or hybrid),
**so that** YANA knows she is operating as my coding co-pilot and my mode preference is locked for the session.

#### Acceptance Criteria

**AC-1.1.1 — Mode entry command**
- Running `python main.py --programmer` starts programmer mode
- Running `python main.py --programmer --text` starts programmer mode in text-only interaction
- Running `python main.py --programmer --voice` starts programmer mode in voice-only interaction
- If neither `--text` nor `--voice` is passed, YANA asks Fred to choose before proceeding
- YANA never infers voice/text mode from prior sessions or environment — it must be explicit

**AC-1.1.2 — Mode persists for the full session**
- Once voice or text mode is set at activation, YANA does not switch mid-session unless Fred issues an explicit switch command (`/switch-mode voice` or `/switch-mode text`)
- YANA does not infer a mode switch from ambient signals (e.g. Fred suddenly typing when previously voice-only)

**AC-1.1.3 — Sanctum context loaded**
- On programmer mode activation, YANA loads the full sanctum context (BOND.md, MEMORY.md, PERSONA.md) as background context for all downstream engine dispatches
- Sanctum load failure is a hard stop — programmer mode does not activate without it

**AC-1.1.4 — Programmer mode signals its readiness**
- YANA outputs a single confirmation line: "Programmer mode active — [voice|text|hybrid]. Ready for your request."
- In voice mode, this is spoken via TTS
- No banner, no setup noise beyond this line

**AC-1.1.5 — Tests**
- `test_programmer_mode.py`: mode flag parsing, sanctum load, mode persistence logic (no mode switch on unmarked input)

---

### Story 1.2 — Clarification Gate (FR2)

**As** Fred,
**I want** YANA to ask me clarifying questions before sending any request to the engine,
**so that** the engine never executes based on ambiguous intent and I never discover a misunderstanding after code is written.

#### Acceptance Criteria

**AC-1.2.1 — Gap detection**
- Before dispatching to the engine, YANA evaluates the request for: missing target (which file/repo/feature?), conflicting signals, missing scope boundary, or any gap that would cause the engine to make an assumption
- Gap detection uses an LLM call with the request + sanctum context as input
- If no gaps detected, YANA proceeds to dispatch (Story 1.3) without asking

**AC-1.2.2 — Clarifying questions surfaced**
- For each detected gap, YANA asks exactly one question — not a list dump
- Questions are asked sequentially: YANA waits for Fred's answer before asking the next
- YANA does not suggest answers, fill in plausible defaults, or proceed with a "best guess"

**AC-1.2.3 — Hard stop on no response**
- If Fred does not answer a clarifying question (sends empty input, types `/skip`, or says "skip" in voice mode), YANA stops the request entirely
- YANA outputs: "Request cancelled — clarification was needed to proceed. Start a new request when ready."
- No partial dispatch occurs

**AC-1.2.4 — Clarification does not create a worktree**
- The git worktree for this session does not exist during the clarification phase
- Worktree is created only after all clarifying questions are answered and Fred confirms the request is ready to dispatch

**AC-1.2.5 — Clarification context carried forward**
- Fred's answers to clarifying questions are appended to the request before dispatch
- The engine receives the original request + all clarifications as a single enriched prompt — not separate messages

**AC-1.2.6 — No autonomy**
- YANA never proceeds to engine dispatch without explicit confirmation from Fred that the request is complete and ready
- This applies even if YANA detects no gaps — dispatch requires Fred's go-ahead (can be implicit: if Fred's original message is complete and unambiguous, the go-ahead is the message itself)

**AC-1.2.7 — Tests**
- `test_clarification_gate.py`: gap detection logic, sequential question flow, hard stop on empty answer, enriched prompt assembly

---

### Story 1.3 — Route Request to Engine (FR1)

**As** Fred,
**I want** YANA to send my clarified request to the coding engine with full session context,
**so that** the engine has everything it needs and I never re-explain the project or my preferences.

#### Acceptance Criteria

**AC-1.3.1 — Worktree created at dispatch time**
- YANA creates the git worktree immediately before calling `engine.dispatch()`
- Worktree name: `programmer-{session_id}` on branch `programmer/{session_id}`
- If worktree creation fails, YANA reports: "Could not create worktree: {reason}. Request not dispatched." and stops
- No worktree is created during clarification (enforced by Story 1.2 AC-1.2.4)

**AC-1.3.2 — Context assembly**
- `EngineRequest` is built with:
  - `prompt`: original request + all clarification answers
  - `context`: sanctum summary (BOND.md + MEMORY.md condensed to ≤500 tokens) + active session summary
  - `worktree_path`: path to the newly created worktree
  - `session_id`: unique ID for this programmer session

**AC-1.3.3 — Engine dispatch via abstraction**
- YANA calls `engine.dispatch(request)` — never calls Claude Code APIs directly
- Engine is resolved from `providers.yaml` `engines.default` — not hardcoded

**AC-1.3.4 — Fred is notified of dispatch**
- YANA outputs: "Request sent to engine. I'll surface decisions that need you." (spoken in voice mode)
- No further output until an `EngineEvent` arrives (Story 1.4 handles routing of events)

**AC-1.3.5 — No autonomous re-dispatch**
- YANA never automatically re-dispatches a failed or timed-out request
- If the engine session ends unexpectedly, YANA surfaces an `ENGINE_FAILURE` decision point (Story 1.4) and waits for Fred

**AC-1.3.6 — Tests**
- `test_routing.py`: `EngineRequest` assembly, worktree creation before dispatch, failure on worktree error, no direct engine API calls

---

### Story 1.4 — Decision-Point Filter (FR4, NFR3)

**As** Fred,
**I want** YANA to surface only what requires my decision and suppress everything else,
**so that** I can follow a full development cycle without reading build logs or stack traces.

#### Acceptance Criteria

**AC-1.4.1 — Filter uses taxonomy**
- The filter reads `EngineEvent` objects from `engine.events(session)`
- Events of type `DecisionPoint` are surfaced to Fred — all other event types are suppressed
- Suppressed event types: `ProgressUpdate` (technical noise)
- `CompletionSignal` is surfaced as a special case: "Engine finished. [summary of outcome]. What's next?"
- `EngineError` with `kind=ENGINE_FAILURE` is surfaced with the failure message — Fred decides whether to retry, abandon, or inspect

**AC-1.4.2 — Decision point presentation**
- Each `DecisionPoint` is presented to Fred with:
  - The question or choice required
  - Enough context to decide (one sentence max — no raw output)
  - Available options if applicable (e.g. "overwrite / skip / cancel")
- In voice mode, the decision point is spoken; Fred responds verbally
- In text mode, Fred types a response

**AC-1.4.3 — Fred's response forwarded to engine**
- Fred's answer to a decision point is sent to the engine via `engine.send(session, answer)`
- YANA does not interpret, modify, or act on Fred's answer — she forwards it verbatim
- After sending, YANA resumes listening to `engine.events()` for the next event

**AC-1.4.4 — Technical output on demand**
- Fred can request raw output at any point via `/show-output` or "mostra o output" in voice mode
- YANA retrieves the buffered technical output for the current engine session and displays/reads it
- This is Fred's explicit override — YANA never proactively surfaces technical output

**AC-1.4.5 — No output until event arrives**
- Between dispatch and the first `EngineEvent`, YANA is silent (no polling messages, no "still thinking" updates unless > 60 seconds, after which YANA may say "Engine is still running." once)
- This prevents technical noise from the waiting period itself

**AC-1.4.6 — Tests**
- `test_filter.py`: `DecisionPoint` surfaces, `ProgressUpdate` suppressed, `CompletionSignal` formatted, `EngineError` surfaces, `/show-output` retrieves buffer

---

## Epic 2: Worktree + Methodology Routing

> One worktree per session managed by YANA, engine runs BMAD/SpecKit inside the worktree so methodology artifacts commit to git. Delivers CAP-3. Depends on Epic 1 Story 1.3 (routing functional).

---

### Story 2.1 — Worktree Lifecycle Management (NFR2)

**As** Fred,
**I want** YANA to manage the full lifecycle of the git worktree for my programmer session,
**so that** each session is isolated, I never accidentally contaminate the main branch, and cleanup happens reliably.

#### Acceptance Criteria

**AC-2.1.1 — Worktree creation (happy path)**
- On dispatch (Story 1.3 AC-1.3.1), YANA creates a worktree at `.yana/worktrees/programmer-{session_id}` on branch `programmer/{session_id}`
- Branch is created from the current HEAD of the repo's default branch
- Worktree path and branch name are passed to the engine in `EngineRequest`

**AC-2.1.2 — Worktree cleanup on session end**
- When Fred ends the session (`/end-session`, "encerra sessão" in voice, or Ctrl+C), YANA:
  1. Signals the engine to stop
  2. Waits for engine acknowledgement (up to 5 seconds, then force-stops)
  3. Removes the worktree: `git worktree remove --force .yana/worktrees/programmer-{session_id}`
  4. Deletes the branch if it was not pushed: `git branch -d programmer/{session_id}`
  5. Outputs: "Session ended. Worktree cleaned up."
- If the branch was pushed (a PR was opened), the branch is NOT deleted — Fred owns it from that point

**AC-2.1.3 — Worktree creation failure (sad path)**
- If `git worktree add` fails (e.g. branch already exists, disk full, not a git repo), YANA surfaces `ENGINE_FAILURE` with the git error message
- No engine dispatch occurs
- Fred receives: "Could not create worktree: {reason}. Request not dispatched."
- YANA does not retry automatically

**AC-2.1.4 — Engine crash mid-session (sad path)**
- If the engine process dies unexpectedly during a session, YANA:
  1. Detects the abrupt end of `engine.events()` (no `CompletionSignal` received)
  2. Surfaces `ENGINE_FAILURE`: "Engine stopped unexpectedly. Your worktree is intact at {path}. Resume, inspect, or end session?"
  3. Waits for Fred's choice
  4. Does NOT clean up the worktree until Fred explicitly says to (the partial work may be valuable)

**AC-2.1.5 — Fred cancels mid-session (sad path)**
- If Fred cancels via `/cancel` or "cancela" in voice during engine execution:
  1. YANA sends a stop signal to the engine
  2. After engine stop, YANA asks: "Cancel complete. Keep the worktree for inspection, or clean it up?"
  3. YANA acts on Fred's answer — no default cleanup

**AC-2.1.6 — Session termination criteria**
- A session is considered complete when any of:
  - Fred issues `/end-session`
  - The engine returns `CompletionSignal` AND Fred issues a termination command
  - Fred abandons the terminal (SIGTERM) — worktree is preserved, cleanup logged as deferred
- YANA never terminates a session autonomously

**AC-2.1.7 — Tests**
- `test_worktree.py`: creation, cleanup, branch deletion logic, failure on git error, crash detection, cancel flow — use subprocess mocks, no real git calls

---

### Story 2.2 — Methodology Routing (FR3)

**As** Fred,
**I want** to tell YANA I'm starting a BMAD or SpecKit run, have her collect my inputs conversationally, and then hand everything to the engine to execute inside the worktree,
**so that** all methodology artifacts (specs, PRDs, stories) land in the git history without me manually running methodology tools.

#### Acceptance Criteria

**AC-2.2.1 — Methodology mode activation**
- Fred can activate methodology mode with: "vamos fazer um BMAD" / "start a SpecKit run" / `/methodology bmad` or `/methodology speckit`
- YANA recognizes the methodology intent and shifts to input-collection mode
- YANA does not activate methodology mode unless Fred explicitly signals it (no inference)

**AC-2.2.2 — Conversational input collection**
- YANA asks Fred for the inputs the methodology needs (e.g. for BMAD: project name, what to build, session goals)
- Questions are asked one at a time; Fred answers conversationally in voice or text
- YANA does not run the methodology herself — she only collects inputs

**AC-2.2.3 — Handoff to engine**
- Once Fred's inputs are collected, YANA assembles them into a structured prompt and dispatches to the engine via `engine.dispatch()`
- The prompt includes: which methodology to run, Fred's inputs, the worktree path
- The engine is responsible for running the methodology CLI/SDK inside the worktree

**AC-2.2.4 — Artifacts committed inside worktree**
- After the methodology run, generated artifacts (SPEC.md, PRD, stories, etc.) exist inside the worktree
- YANA verifies at least one file was created/modified in the worktree after engine completion
- YANA does not commit the artifacts — that is the engine's responsibility (or Fred's explicit next step)

**AC-2.2.5 — Swappable methodology**
- Adding a new methodology (e.g. OpenSpec) requires only: adding it to the input-collection prompt set and adding its trigger phrases
- No changes to `engine.py`, `dispatch()`, or the worktree lifecycle
- The methodology name is passed as part of `EngineRequest.prompt` — engine resolves what to run

**AC-2.2.6 — YANA never owns methodology execution**
- YANA does not call BMAD scripts directly
- YANA does not parse methodology output
- YANA does not validate methodology artifacts
- These are all engine responsibilities

**AC-2.2.7 — Tests**
- `test_methodology_routing.py`: methodology mode activation, input collection sequence, prompt assembly, dispatch call verification (mock engine), artifact existence check

