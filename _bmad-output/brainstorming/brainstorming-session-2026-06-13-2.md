---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'YANA as programming assistant — voice-driven, end-to-end (conversation → code → PR), orchestrating sub-agents'
session_goals: 'Define the programmer flow for YANA; design sub-agent orchestration model; envision BMAD integration via voice; explore mobile/ambient future'
selected_approach: 'ai-recommended'
techniques_used: ['Question Storming', 'Dream Fusion Laboratory', 'SCAMPER Method']
ideas_generated: [29]
workflow_completed: true
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Fred
**Date:** 2026-06-13

## Session Overview

**Topic:** YANA como programadora — assistente de ponta a ponta (voz → código → PR)
**Goals:** Definir o fluxo do modo programmer da YANA; orquestração de sub-agentes; integração com BMAD via voz; visão mobile/ambient

### Session Setup

Fred quer que a YANA seja sua parceira de programação completa — não só conversa, mas capaz de criar código, abrir PRs, e guiar o processo BMAD por voz. YANA como orquestradora de sub-agentes especializados. Visão de futuro: voz onipresente, sem tela, no celular em trânsito.

## Technique Execution Results

**Techniques used:** Question Storming → Dream Fusion Laboratory → SCAMPER

### Question Storming — Mapping the Problem Space

**Key Breakthroughs:**
- YANA is not a coder — she is the voice/text interface to a coding engine (PI)
- The methodology (BMAD, SpecKit, OpenSpec) controls the flow; YANA is the interface with it
- YANA lives in the gap between Fred's imprecise communication and what the engine needs
- What YANA does NOT do is as important as what she does — no reinventing standard LLM behavior

### Dream Fusion Laboratory — The Impossible Dream

**Scenario:** Fred wakes up early, glances at open threads, starts one while making coffee. AI processes while Fred showers, goes to the office. YANA holds context across all gaps. Multiple threads run in parallel — 4 work repos, 2 personal. YANA notifies Fred when a thread needs input, Fred context-switches by natural conversation. Eventually a PR opens. Fred reviews in GitHub, comes back to YANA for adjustments.

**Key Breakthroughs:**
- AI processing time as intentional pause — the delay is a feature, not a bug
- Context switch happens through dialogue, like talking to a human coworker
- "Ok, entendi, estou pensando" as the release signal — Fred can move on
- YANA frees Fred from the screen entirely in the ideal state

### SCAMPER — Grounding in the Existing Architecture

| Lens | Key Insight |
|---|---|
| Substitute | Replace isolated sessions with shared-awareness sessions |
| Combine | Sanctum + thread state combined into one memory layer |
| Adapt | Isolated execution env for PI (already in issue #3) |
| Modify | Session log → active session summary |
| Put to other use | Sanctum as developer profile (coding style, patterns) |
| Eliminate | Autonomy and technical noise from programmer mode |
| Reverse | YANA-initiated contact — thread calls Fred, not the other way |

## Idea Inventory (29 ideas)

### Theme 1: Architecture (to be specced before implementation)

**#3** YANA as Voice/Text Layer over Interchangeable Coding Engine
_YANA doesn't code — she has a programmer module. The engine (Claude Code, Aider, OpenCode) is pluggable underneath._

**#5** YANA as Methodology-Agnostic Interface
_YANA doesn't control the BMAD/SpecKit flow — the methodology does. YANA is the voice that talks to Fred on its behalf._

**#7** What is NOT YANA's Responsibility
_Standard LLM behavior (fix errors, ask when stuck) stays with the engine. YANA adds persistent context, Fred-knowledge, and multi-modal presence._

**#18** YANA + PI — Separation of Interface and Execution
_YANA is the interface. PI (the coding engine) is the executor. Two distinct agents, two distinct roles._

**#19** YANA as Filter and Translator, not Executor
_YANA filters what comes from the coding engine — Fred only sees what needs a decision. The engine can connect to GitHub directly without routing through YANA._

**#26** Eliminate Autonomy and Technical Noise from Programmer Mode
_YANA doesn't act autonomously. She doesn't dump technical output at Fred — she digests and surfaces only decision points._

**#2** YANA as Specification Clarifier
_Before execution, YANA exposes gaps, doesn't fill them. She asks uncomfortable questions like a senior engineer before writing a line of code._

**#17** Mitigation, Not Protection
_YANA doesn't protect Fred from his own choices. She mitigates negative effects. Rules emerge from real use, not imposed upfront._

**#4** YANA as Guide Through Full BMAD Cycle
_YANA accompanies Fred from brainstorm to PR. She changes mode per phase: facilitator, spec-gatherer, task manager, code orchestrator._

---

### Theme 2: Thread Management (→ GitHub Issue)

**#9** Thread Context Cards
_YANA maintains a living card per active thread — repo, branch, what's being done, where it stopped, next step. One sentence when Fred asks "what was that again?"_

**#10** YANA as Intelligent Dispatcher
_All of Fred's input goes through YANA first. She routes: conversation with me (coworker) or command to dev sub-agent? Fred speaks naturally, YANA routes._

**#11** Interleaved Thread Execution
_Fred fires thread A, while AI processes switches to thread B, fires, moves to C. YANA tracks all and notifies when each needs human input. Like a chef with 4 pots._

**#12** Explicit Context Switch as Interface Primitive
_YANA never infers a context switch. Fred always signals — verbally ("let's switch context") or physically (UI element). Inside a context, everything is for that thread._

**#13** Thread as Neutral Context
_Threads have no pre-defined type (code vs. chat). Every thread starts equal. Whether it becomes dev work or brainstorm emerges naturally from the conversation._

**#22** Replace Isolated Sessions with Shared-Awareness Sessions
_Multiple console instances today are islands. They need shared state: all YANA instances know which threads exist, their status, when they need Fred._

---

### Theme 3: Memory and Context (→ GitHub Issue)

**#25** Session Summary as Active Mechanism
_Modify the session log to generate a contextual summary. Appears when: Fred navigates back to session, closes/reopens cmd, or focuses a window open for a long time._

**#16** Context Depth Proportional to Time
_10 minutes ago = 1 sentence. 2 hours = 3 sentences. 2 days = full paragraph with decisions open. YANA calibrates how much scaffolding Fred needs to re-orient._

**#15** Thread Summary as Cognitive Anchor
_When Fred returns after doing something else, YANA offers: "we were implementing the payment endpoint, code generated, tests ran, 2 errors pending, awaiting your timeout decision."_

**#6** The Context Gap as Integration Point
_The biggest integration point is not technical — it's the gap between what Fred knows and what the methodology needs as input. YANA lives there._

**#1** Repo-Aware Dev Flow
_Each repository defines its own dev flow in a config file (e.g. `.yana/dev-flow.yaml`). When Fred talks about a repo, YANA loads the right context automatically._

**#23** Combine Sanctum + Thread State
_The sanctum knows who Fred is. Extended to also know what Fred is doing. When resuming a thread, personal context and technical context arrive together for the coding engine._

**#29** Sanctum as Evolving Developer Profile
_The sanctum gains a developer layer — Fred's coding preferences, patterns, strengths, blind spots. Over time, YANA needs less explanation. Fred becomes less manually present in the code._

---

### Theme 4: Experience / Interface

**#8** AI Processing Time as Intentional Pause
_The AI delay is a feature. Fred fires a process, makes coffee, showers, goes to the office. YANA holds context. When Fred returns (5 min or 2h), state is there waiting._

**#14** Hands-Free Development
_Ideal YANA frees Fred from the screen. Development happens while Fred cooks, changes a lightbulb. Fred speaks, listens, speaks back. The screen is optional._

**#20** Context Switch Through Natural Conversation
_Fred is cooking. YANA says: "the yana-programmer thread is asking X." Fred doesn't remember, asks YANA. YANA summarizes. Fred answers. YANA: "ok, got it, thinking." Two seconds later: "about the MCP feature, which capabilities?" — no UI, no click._

**#21** "Ok, entendi, estou pensando" as Communication Primitive
_YANA confirms she received input and is processing. Fred knows he can drop context — YANA has it. The "received" feedback is the release for Fred to continue his life._

---

### Theme 5: Future — Phase 2 (→ GitHub Issue)

**#27** YANA-Initiated Contact — Contextual Notification
_YANA doesn't wait for Fred to return — she notifies when a thread needs input. Not autonomy ("I solved it"), but notification ("I need you here"). With context intelligence: doesn't interrupt an active conversation without signaling, doesn't shout into an empty room, doesn't notify at 2am._

**#28** Presence Sensors as Notification Condition
_For YANA to know when to interrupt, she needs presence signals — is Fred at the computer? On his phone? Gone? Today: "last input was X minutes ago" is already a proxy. Future: richer sensors._

**#24** Isolated Execution Environment for PI _(already in issue #3)_
_Code being developed by PI runs in isolation — compilation, tests, libs, all separate from Fred's main environment._

## Idea Organization and Prioritization

**Thematic Organization:** 5 themes + 1 future cluster — 29 ideas total

**Prioritization Results:**

- **To spec (foundational):** Theme 1 — Architecture (YANA + PI separation, methodology interface, design principles)
- **To implement (features):** Themes 2, 3, 4 — Thread management, memory/context, experience
- **Phase 2 (future):** Theme 5 — YANA-initiated contact, presence sensors

**GitHub Issues created from this session:**
- `feat: thread management — context cards and multi-thread awareness` (Theme 2)
- `feat: session resume/summary — context depth by time` (Theme 3)
- `feat: YANA-initiated contact — contextual notification` (Theme 5, Phase 2)

**Next step for Theme 1:** Continue to spec phase via BMAD flow.

## Session Summary and Insights

**Key Achievements:**
- Defined YANA's architectural role in programmer mode: interface layer, not executor
- Established the YANA + PI (coding engine) separation as the foundational design decision
- Mapped 29 concrete ideas across architecture, UX, memory, and future capabilities
- Identified the "mitigation not protection" and "no autonomy" principles as hard constraints

**Breakthrough Moments:**
- "I don't want autonomy, I want ease of execution" — reframed the entire design direction
- AI processing time as intentional pause — inverts the human-machine relationship
- "Ok, entendi, estou pensando" — a tiny phrase that unlocks hands-free development
- YANA-initiated contact as Reverse SCAMPER — the thread calling Fred, not the other way

**Design Principles Established:**
1. YANA is interface; PI is executor — always separate
2. Context switches are always explicit — never inferred
3. YANA exposes gaps, never fills them
4. Mitigation not protection — Fred controls, YANA supports
5. Eliminate autonomy and technical noise from the programmer mode
