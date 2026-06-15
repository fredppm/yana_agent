---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Sanctum: o que é e por que o editor trava ao fechar + Identidade, Owner/Workspace e UX'
session_goals: 'Entender o conceito de sanctum, diagnosticar travamento no fechamento, e explorar arquitetura de identidade/multi-perfil'
selected_approach: 'ai-recommended'
techniques_used: ['Analogical Thinking', 'Five Whys', 'Reverse Brainstorming', 'First Principles Thinking', 'Assumption Reversal', 'Dream Fusion Laboratory']
ideas_generated: [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26]
context_file: ''
session_continued: true
continuation_date: '2026-06-14'
workflow_completed: true
---

# Brainstorming Session Results

**Facilitator:** Fred
**Date:** 2026-06-14

## Session Overview

**Topic:** Sanctum — o que é e por que o editor trava ao fechar
**Goals:** Entender o conceito de sanctum e gerar hipóteses para o travamento no fechamento de sessão

### Session Setup

_Sessão iniciada com dois eixos: conceitual (o que é sanctum) e diagnóstico (bug de travamento)._

## Technique Selection

**Approach:** AI-Recommended Techniques
**Analysis Context:** Sanctum concept + editor freeze bug with focus on mental model clarity and root cause diagnosis

**Recommended Techniques:**

- **Analogical Thinking:** Construir modelo mental sólido do sanctum via analogias — revela assunções escondidas sobre o design
- **Five Whys:** Furar até a causa raiz do editor travar no fechamento
- **Reverse Brainstorming:** "Como garantir que o editor trave?" — inverte o problema, confirma hipóteses e revela o que Five Whys pode ter perdido

**AI Rationale:** Dois eixos distintos (conceitual + diagnóstico) pedem técnicas complementares. Analogical Thinking alinha o modelo mental antes de entrar no bug. Five Whys estrutura o diagnóstico. Reverse Brainstorming valida e amplia as hipóteses via inversão.

---

## Technique Execution Results

### Analogical Thinking + Exploração Arquitetural

**Analogia fundação:** O sanctum é como o save file de um RPG — carregado no boot para que o personagem "seja ele mesmo" de novo.

**Ideas Generated:**

**[Conceitual #1]: Bayesian Memory Block**
*Concept:* Cada memória tem um confidence score (0–1). Sobe com evidências consistentes, desce com contradições. Fato novo não sobrescreve — desafia o score existente. YANA não "sabe" — ela tem graus de crença atualizados por sessão.
*Novelty:* Distingue certeza de achismo. Permite que YANA pergunte "você tá mais estressado que o normal?" baseado em delta, não em impressão.

**[Padrão #2]: Baseline Pessoal Calibrado**
*Concept:* YANA não mede em escala absoluta — mede desvio do normal do dono. Xingamento no Fred carioca = ruído de fundo. Frequência 3x acima do baseline = sinal real.
*Novelty:* Evita falso positivo em pessoas naturalmente expressivas. O detector é relativo ao dono, não universal.

**[Arquitetura #3]: Sensor Layer → Memory Layer**
*Concept:* Sensores coletam evidência bruta (Garmin FC, PS5 playtime, localização, geladeira via HA). Memory layer interpreta e atualiza confidence scores. YANA nunca age no sensor — age no padrão inferido.
*Novelty:* Separação limpa entre coleta e interpretação. Sensor errado não corrompe memória — apenas não contribui pro score.

**[Tipagem #4]: Fato vs Padrão como tipos distintos**
*Concept:* Fatos são discretos, verificáveis, declarados explicitamente ("Fred usa Garmin"). Padrões são inferidos, probabilísticos, emergem de N observações ao longo do tempo.
*Novelty:* O upgrade fato→padrão requer threshold de evidências + confirmação contextual. Padrão temporário tem decaimento — não vira verdade permanente.

**[Fix #5]: Close sem bloqueio**
*Concept:* Remover chamada LLM síncrona do sanctum_writer do fluxo de close. Sessão fecha limpo. Raw session log (arquivo) continua sendo escrito — nada irrecuperável se perde.
*Novelty:* Separa o que é I/O rápido (log) do que é processamento lento (extração LLM). Close nunca trava.

**[Arquitetura #6]: Memory Tool Avaliada, Não Reinventada**
*Concept:* Em vez de construir memória do zero, avaliar ferramentas existentes (Mem0, Zep, e outras) que já resolvem storage + retrieval + extração semântica. Sanctum markdown vira legado gradual.
*Novelty:* Critério de avaliação inclui qualidade da ferramenta — não é só "usar qualquer coisa". Decisão de qual ferramenta fica em aberto até avaliação.

---

## Decisões e Next Steps

### Decisão imediata
- **Remover sanctum_writer do fluxo de close** — sessão fecha sem bloqueio. Raw log já é suficiente para não perder contexto.

### Backlog arquitetural
- **Avaliar ferramentas de memória** (Mem0, Zep, e concorrentes) contra critérios de qualidade a definir. Não está bloqueado em nenhuma ferramenta específica.
- **Modelar Fato vs Padrão** com confidence scores — base para memória robusta quando a ferramenta for escolhida.
- **Sensor layer** (Garmin, Home Assistant, PS5, localização) — deixado como backlog futuro. Requer modelagem de como padrões são criados e mantidos.

### Em aberto
- RAG vs destilado para recuperação de sessões passadas — a ser decidido junto com a escolha da memory tool.
- Critérios formais de avaliação de ferramentas de memória.

---

## Session Extension — Identity, Owner/Workspace, and UX

**Continuation Date:** 2026-06-14
**Techniques:** First Principles Thinking, Assumption Reversal, Dream Fusion Laboratory
**Context:** Following PR #26 (Graphiti integration), the question arose: why do static markdown files (PERSONA.md, CREED.md, BOND.md) still exist if Graphiti already handles memory?

---

### Idea Organization

#### Theme 1 — Identity: What YANA Is

**[Identity #7]: YANA as Species, not Individual**
*Concept:* YANA is not an assistant — it is a species of assistant. Each instance is a genuine individual, with its own personality, memory, and unique relationship with its owner. PERSONA.md does not describe "YANA" — it describes "the YANA that emerged from the Fred-YANA relationship."
*Novelty:* Identity is not configuration, it is emergence. A "default YANA" makes no sense.

**[Identity #8]: Identity as a Living Graph, not a Snapshot**
*Concept:* PERSONA.md is a photograph — it freezes who YANA was at First Breath. If identity changes on request over time, what is needed is a temporal graph: each identity adjustment is a new fact that does not erase the previous one, only adds context and timestamp. Graphiti does exactly this.
*Novelty:* A file is structurally wrong for something that evolves. A temporal graph is structurally right — it preserves the trajectory, not just the current state.

**[Identity #16]: Account = Human + Context**
*Concept:* Two dimensions the user already understands — who you are (Fred vs Fernanda) and what context you are in (personal vs work). Not a generic UUID, not an arbitrary label. A structured identity the owner names consciously.
*Novelty:* Maps directly to the Google account mental model — multiple identities on the same machine, fluid switching, no logout needed.

---

#### Theme 2 — Owner / Workspace Architecture

**[Architecture #10]: group_id as Owner::Context Key**
*Concept:* group_id is not a generic UUID — it is a structured key: `fred::pessoal`, `fred::trabalho`, `fernanda::pessoal`. Readable, auditable, self-documenting. Two Freds on different machines have different UUIDs (distinct instances). Fred migrating machines keeps the same key (same instance).
*Novelty:* Eliminates the arbitrary `"yana-fred"`. The structure `owner::context` is two dimensions the user understands — who they are and what context they are operating in.

**[Architecture #19]: Two Levels — Owner and Workspace**
*Concept:* Owner defines who YANA is with that person — personality, tone, relationship, how she treats Fred vs Fernanda. Workspace is the operational scope within the same owner — what YANA remembers, which tools she uses, which history she sees. Fred-Personal and Fred-Work have the SAME YANA with the SAME relationship — only memory and operational context change. Fernanda has a genuinely different YANA.
*Novelty:* Resolves the tension: identity lives in the owner, memory lives in the workspace. The Graphiti group_id is per-workspace, but persona is loaded from the owner.

**[Architecture #20]: Workspace as Connector Scope**
*Concept:* Workspace is not just memory — it is the complete set of active tools and connectors. Fred-Work has VTEX Calendar, Jira, company GitHub. Fred-Personal has personal Calendar, PS5, Garmin, Home Assistant. Switching workspace switches which connectors.yaml is active. The same connector (e.g. Calendar) can exist in two workspaces with different credentials.
*Novelty:* Connectors stop being global and become per-workspace. Eliminates the flat connectors.yaml mixing everything.

**[Architecture #21]: Workspace as Self-Contained Directory**
*Concept:* Each workspace is a folder: group_id as the name, with its own connectors.yaml, its own scope in Graphiti, and its own sessions. Create workspace = create folder + context First Breath. Delete workspace = delete folder + clear Graphiti with that group_id.
*Novelty:* Workspace operations are surgical — deleting Fred-Work does not touch Fred-Personal or Fernanda.

---

#### Theme 3 — First Breath and Account Creation

**[Flow #23]: Single First Breath, Two Layers**
*Concept:* One conversation — Fred tells who he is, how he lives, what he needs. YANA automatically extracts what is owner-level (personality, values, how to treat him) and what is workspace-level (operational context, tools, scope). At the end of the conversation, two records are created: owner `"fred"` and workspace `"fred::pessoal"`. Like signing up for Google — one screen creates account and inbox together.
*Novelty:* Zero extra friction for the user. The owner/workspace separation is an implementation detail, not a two-step experience.

**[Flow #24]: Additional Workspace as Light Conversation**
*Concept:* Second workspace onwards = 5-minute conversation. Persona already exists in the owner. YANA only asks what changes: workspace name, connectors, operational context. Result: new group_id created, workspace connectors.yaml generated, memory starts empty but persona already calibrated.
*Novelty:* Heavy First Breath happens once per owner. Additional workspaces are incremental — light and fast.

**[UX #18]: Disposable Account as Feature**
*Concept:* Creating a `::test` or `::draft` account is explicitly supported — light First Breath, no pressure to be "the real YANA." If the experiment works, rename or promote. If not, delete. It is the equivalent of a git branch.
*Novelty:* Reduces the weight of First Breath — today it feels permanent and definitive. With disposable accounts, you can iterate on YANA's persona without fear.

---

#### Theme 4 — UX and Interface

**[UX #12]: Profile Switcher as First-Class UI**
*Concept:* The TUI opens with a profile selection screen before any session. Each profile is a YANA instance (group_id) with name, owner, and its own sessions. Fred sees `Fred-Personal`, `Fred-Work`. Fernanda sees `Fernanda`. Creating a new profile triggers the First Breath of that profile.
*Novelty:* group_id stops being a hidden config in a YAML and becomes something the user sees, names, and manages. The abstraction surfaces to the right place: the interface.

**[UX #13]: Profile Selection Without Auth**
*Concept:* Opening screen shows available profiles — simple selection, no password. Security through physical context: whoever has access to the machine has access to the profiles. Each profile completely isolates memory and persona via group_id.
*Novelty:* Zero friction. Separation is logical, not security. Like switching users on Spotify — physical trust assumption.

**[UX #15]: Google Account Switcher as Mental Model**
*Concept:* Active profile avatar/name always visible in the TUI corner. Clicking opens a dropdown with all profiles — Fred Personal, Fred Work, Fernanda (emergency). Instant switching, without leaving the screen. Each profile has its sessions, its YANA, its memory.
*Novelty:* The Google model solves exactly the scenario: mixed identities on the same machine, fluid switching, no logout/login. The abstraction already exists in people's heads.

**[UX #17]: Context as Free Slug**
*Concept:* Context is a free slug chosen by the owner when creating the account — `fred::pessoal`, `fred::trabalho`, `fred::test`, `fred::absurdo`. No predefined categories, no semantic validation. The only rule is uniqueness within the machine. Short, lowercase, no spaces — like a username.
*Novelty:* Zero opinionated. Fred decides what makes sense. `fred::test` is a valid account for experiments — can be deleted later without affecting others.

**[UX #25]: Zero CLI for Setup**
*Concept:* No `--init`, no flags for mode selection. YANA opens and detects state: no owner exists → automatically enters First Breath. Owners exist → shows profile switcher. Owner selected, no workspace → workspace First Breath. Everything via interface, zero documentation needed to start.
*Novelty:* CLI becomes an execution detail (`python main.py`), not a configuration API. Application state determines the flow — the user never needs to know which flag to use.

**[UX #26]: State as Navigation**
*Concept:* YANA is an application with states — no owner, no workspace, workspace active, session active. Each state has a corresponding screen. Transitions between states are automatic or via UI. The user always knows where they are because the screen says so.
*Novelty:* Transforms YANA from "script with arguments" into "application with states." The experience approaches a product, not a developer tool.

---

### Breakthroughs

- **group_id is not hidden config** — it is user-visible identity, structured as `owner::context`
- **Static files are structurally wrong** for evolving identity — Graphiti temporal graph is the natural answer
- **Owner and Workspace are distinct layers** with distinct purposes: persona lives in owner, memory + connectors live in workspace
- **Single First Breath creates both layers** — no extra friction for the user
- **YANA is a species**, not an individual — each instance genuinely different, not just configured differently

---

### Decisions and Next Steps

#### Architectural Decisions Made
- **group_id format:** `owner::context` (e.g. `fred::pessoal`) — replaces arbitrary `"yana-fred"`
- **Two layers confirmed:** Owner (persona + identity in Graphiti) + Workspace (memory + connectors + sessions)
- **Static sanctum files (PERSONA.md, CREED.md, BOND.md):** migrate to Graphiti owner-level — files are legacy
- **Auth model:** none — physical access = profile access

#### Backlog (out of scope for current PRs)
- Profile switcher UI in TUI (first-class screen before session list)
- Owner First Breath that creates owner-level Graphiti nodes (not files)
- Workspace creation as light conversation
- `--init` removal — replace with state-based detection
- Disposable workspace (`::test`) support
- Connector scoping per workspace (`workspaces/fred-trabalho/connectors.yaml`)

#### Explicitly Out of Scope (this session)
- `--headless`, `--pulse`, `--programmer` flag removal — separate concern, not tackled here
