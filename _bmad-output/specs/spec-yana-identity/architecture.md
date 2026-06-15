# Identity Architecture — Companion to SPEC-yana-identity

## Two-Layer Model

```
owners/
  {owner}/                        ← owner slug (e.g. "fred", "fernanda")
    persona → Graphiti             ← group_id: "{owner}" (e.g. "fred")
                                     nodes: persona, values, relationship style
    workspaces/
      {context}/                  ← context slug (e.g. "pessoal", "trabalho", "test")
        connectors.yaml            ← connector config for this workspace
        memory → Graphiti          ← group_id: "{owner}::{context}"
                                     nodes: episodic memory, open threads, facts
```

## group_id Assignment

| Scope | group_id | Example | Stores |
|---|---|---|---|
| Owner | `{owner}` | `fred` | Persona, CREED, long-term identity facts |
| Workspace | `{owner}::{context}` | `fred::pessoal` | Episodic memory, session facts, open threads |

## TUI Navigation Model

Single unified screen. No separate "profile switcher" and "session list" — they are one.

```
◄ fred::pessoal │ fred::trabalho │ fernanda::pessoal ►
─────────────────────────────────────────────────────
  ↑ session 2026-06-14_16-00  "Oi YANA, tô num dia..."
  │ session 2026-06-13_09-30  "PR bloqueado há 3..."
  ↓ session 2026-06-12_20-15  "Entrevista na Stripe..."
```

- **Left / Right** — shifts active profile; session list updates immediately
- **Up / Down** — scrolls sessions of the active profile
- **Enter** — opens selected session
- **New session** — starts a session in the active profile

## Launch States

```
launch
  │
  ├─ no owners exist ──────────────────────► First Breath
  │                                           (creates owner + first workspace,
  │                                            writes group_id to providers.yaml)
  │
  └─ owners exist ─────────────────────────► Unified profile+session screen
                                              (active profile = last used)
```

## First Breath Output

One conversation produces two Graphiti writes:

1. **Owner-level** (`group_id: "{owner}"`): persona, values, relationship style, how YANA addresses the owner
2. **Workspace-level** (`group_id: "{owner}::{context}"`): operational context, initial facts, connector needs identified

And one config write:

- `providers.yaml → graphiti.active_profile: "{owner}::{context}"`

## Connector Scoping

Each workspace has its own `connectors.yaml` at `workspaces/{context}/connectors.yaml`. The runtime loads connectors from the active workspace only. The same connector type (e.g. `google_calendar`) may appear in multiple workspaces with different credentials:

```
workspaces/
  pessoal/
    connectors.yaml   ← google_calendar: credentials_file: ~/.yana/google_personal.json
  trabalho/
    connectors.yaml   ← google_calendar: credentials_file: ~/.yana/google_vtex.json
                         jira: ...
                         github: ...
```

## Static File Migration Path (CAP-3)

Existing users with markdown sanctum files follow this path:

1. First session after upgrade: system detects markdown files exist, Graphiti owner nodes do not
2. Migration prompt in TUI: "Import your existing sanctum into Graphiti?"
3. On confirm: `init-sanctum.py` reads markdown files, writes equivalent Graphiti nodes
4. Markdown files are renamed to `.bak` (not deleted) for one release cycle
5. Subsequent sessions load from Graphiti; markdown files are ignored
