# YANA Agent — Claude Code Guide

This file is the authoritative contract for any Claude instance working in this repo.
Read it fully before touching code. Changes that break the contracts below will fail tests.

---

## Project Layout

```
yana_agent/
  orchestrator/           # Python entry point + all runtime logic
    main.py               # CLI: --text | --pulse | --programmer | default (voice)
    core.py               # System prompt assembly, profile/sanctum helpers
    store.py              # PostgreSQL storage — profiles, sanctum, sessions, connectors (SQLAlchemy)
    memory.py             # Graphiti episodic memory — Neo4j only
    providers.py          # Multi-model LLM routing (Anthropic / Bedrock / OpenAI)
    voice.py              # STT (faster-whisper) + TTS (edge-tts)
    sanctum_writer.py     # Post-session sanctum persistence via structured LLM call
    alembic.ini           # Alembic config (URL read from providers.yaml at runtime)
    alembic/
      env.py              # Alembic environment — imports Base and _load_url from store.py
      versions/           # Migration files — one per schema change, committed to git
    config/
      providers.yaml      # Model routing + DB connection config
    tests/                # Pytest suite for pure logic (no external deps)
  skills/
    agent-yana/           # YANA skill definition
      SKILL.md            # Identity seed (read-only at runtime)
      references/         # first-breath.md, memory-guidance.md, etc.
  docker-compose.yml      # Neo4j + PostgreSQL + LiteLLM
```

---

## TUI Screens

Use these names when reporting bugs or writing tests — they map 1-to-1 to Textual classes in `tui.py`.

| Screen name | Textual class | When shown |
|---|---|---|
| **Session Browser** | `ProfileSessionScreen` | On startup when ≥1 profile exists. Left/right navigate profiles; up/down navigate sessions. |
| **Chat** | `YANAApp` (main screen) | After selecting a session from the browser, or immediately on first run (First Breath). |
| **New Profile modal** | `NewProfileScreen` | Pushed on top of Session Browser when user presses `n`. |
| **Rename Profile modal** | `RenameProfileScreen` | Pushed on top of Session Browser when user presses `r`. |

**Chat sub-elements** (not screens, but commonly referenced):

| Element name | CSS id | Description |
|---|---|---|
| **Thinking row** | `#thinking` | Row above the input bar; shows spinner while YANA is processing. Hidden when idle. |
| **Input bar** | `#input-bar` | Bottom bar with prompt label (`❯`) and text input. |
| **Chat hint bar** | `#chat-hint` | Row below the input bar; shows keyboard shortcuts. |
| **Chat log** | `#chat` | Main scrolling area where messages appear. |

**First Breath** is not a separate screen — it is the Chat opening directly (skipping the Session Browser) with `auto_greet=True` because no profiles exist yet.

**Keyboard shortcuts in Chat:**

| Key | Action |
|---|---|
| `ctrl+d` | End session (triggers memory save + exit) |
| `ctrl+o` | Toggle history expand/collapse |
| `ctrl+t` | Toggle voice mode |
| `ctrl+c` | Force-quit (skips memory save) |

---

## Storage Architecture

Two separate backends, two separate concerns:

| Backend | Used for | Module |
|---|---|---|
| **PostgreSQL** | Profiles, owner identity (sanctum fields), sessions, connectors | `store.py` |
| **Neo4j (Graphiti)** | Episodic memory only — entities, relationships, fact search | `memory.py` |

**Never add operational data (profiles, sessions, config) to Neo4j. Never add episodic memory to PostgreSQL.**

### PostgreSQL models (store.py)

- `Owner` — identity of the owner (persona, creed, bond). One row per person.
- `Profile` — a context within an owner (`fred::pessoal`, `fred::work`). Stores capabilities, pulse, pulse_config.
- `Connector` — connector configs per profile.
- `SessionRecord` — raw message history per session.

### Sanctum fields

Owner-level (same across profiles): `persona`, `creed`, `bond`
Profile-level (per context): `capabilities`, `pulse`, `pulse_config`

LLM write protocol maps: `PERSONA` → `persona`, `BOND` → `bond`, `PULSE_CONFIG` → `pulse_config`, etc.

---

## Database Migrations (Alembic)

**All schema changes go through Alembic. Never edit the DB directly.**

### Startup

`store.init_schema_sync()` calls `alembic upgrade head` automatically on every startup.
It is idempotent — if the schema is already up to date, nothing happens.

### Adding or changing a column

```bash
# 1. Edit the SQLAlchemy model in store.py
# 2. Generate the migration
cd orchestrator
alembic revision --autogenerate -m "describe the change"

# 3. Review the generated file in alembic/versions/
#    For NOT NULL columns with existing rows, edit the upgrade() to:
#      a. add column as nullable
#      b. backfill existing rows
#      c. alter to NOT NULL
# Example:
#   def upgrade():
#       op.add_column('owners', sa.Column('timezone', sa.String(), nullable=True))
#       op.execute("UPDATE owners SET timezone = 'UTC'")
#       op.alter_column('owners', 'timezone', nullable=False)

# 4. Apply
alembic upgrade head

# 5. Commit the migration file with the model change
git add alembic/versions/<new_file>.py store.py
git commit -m "chore: add timezone column to owners"
```

### Other useful commands

```bash
alembic history          # list all migrations and their status
alembic current          # show current DB revision
alembic downgrade -1     # rollback one migration
alembic downgrade base   # rollback everything
```

---

## Public Contracts — must not break

### core.py

| Function | Signature | Contract |
|---|---|---|
| `sanctum_exists()` | `() -> bool` | True if owner persona is stored in PostgreSQL for active profile |
| `load_system_prompt()` | `() -> str` | Raises `FileNotFoundError` if SKILL.md missing |
| `is_quiet_hours(pulse_config?)` | `(dict?) -> bool` | Parses `quiet_hours: "HH:MM-HH:MM"` — handles overnight windows (e.g. 23:00–07:00) |
| `list_sessions(limit?)` | `(int) -> list[tuple[str, datetime, str]]` | Returns sessions from PostgreSQL as `(id, datetime, preview)` |
| `load_session_messages(session_id)` | `(str) -> list[dict]` | Returns messages from PostgreSQL for the given session |

### store.py

| Function | Signature | Contract |
|---|---|---|
| `init_schema_sync()` | `() -> None` | Runs `alembic upgrade head` — idempotent, safe on every startup |
| `load_sanctum_fields_sync(owner_id, profile_id)` | `(str, str) -> dict[str, str]` | Returns `{prop: val}` for all non-null sanctum fields |
| `save_sanctum_fields_sync(owner_id, profile_id, fields)` | `(str, str, dict) -> None` | Upserts owner + profile rows. Keys are LLM protocol names (e.g. `"BOND"`) |
| `list_profiles_sync()` | `() -> list[dict]` | Returns `[{id, label}]` ordered by `created_at` (creation time) |

### providers.py

| Function | Signature | Contract |
|---|---|---|
| `resolve_model(task, config?)` | `(str, dict?) -> tuple[str, str]` | Returns `(provider_name, model_id)`; raises `ValueError` if unresolvable |
| `call_llm(messages, system, task, stream, config?, timeout)` | `(...) -> str` | Routes to correct provider; `task="conversation"` may auto-downgrade to `"conversation_fast"` for short exchanges |
| `load_providers()` | `() -> dict` | Raises `FileNotFoundError` if `config/providers.yaml` missing |

**Auto-downgrade rule** (`_auto_task`): task stays `"conversation"` unless message < 120 chars AND history ≤ 6 turns → downgrades to `"conversation_fast"`. Do not change these thresholds without updating tests.

### voice.py

| Function | Signature | Contract |
|---|---|---|
| `strip_markdown(text)` | `(str) -> str` | Removes `**`, `##`, `-`, `` ` ``, `[text](url)`, `>`, `---`. Never raises. |
| `ts()` | `() -> str` | Returns `HH:MM:SS.mmm` — 12-char timestamp with milliseconds |
| `load_voice_config(providers_config)` | `(dict) -> dict` | Always returns dict with keys: `stt_provider`, `stt_model`, `stt_language`, `tts_voice`, `tts_rate`, `tts_volume` |

### sanctum_writer.py

| Function | Signature | Contract |
|---|---|---|
| `write_sanctum(messages, system, is_first_breath, config?, session_date?)` | `(...) -> dict[str, str]` | Returns `{filename: content}` of written files; empty dict if LLM produces no parseable blocks |
| `_parse_and_write(response)` | `(str) -> dict[str, str]` | Rejects filenames containing `..`, absolute paths, or empty parts. Format: `<<<FILE:name>>>\ncontent\n<<<END>>>` |

---

## LLM Routing

Edit `orchestrator/config/providers.yaml` to change models.

Routing key order: `conversation → conversation_fast → pulse_scheduled → pulse_triggered → first_breath`

Provider precedence for tier lookup: providers listed first in yaml win if tier exists.
Explicit `"provider:tier"` routing in `routing:` section bypasses precedence.

---

## Running Tests

```bash
cd orchestrator
python -m pytest tests/ -v
```

No network calls. No file system side effects outside tmp. Safe to run anywhere.

---

## Infrastructure

```bash
docker compose up -d   # starts Neo4j, PostgreSQL, LiteLLM
python main.py         # YANA runs store.init_schema_sync() on startup (alembic upgrade head)
```

---

## Git Workflow

### Branch protection
`main` is protected — **never push directly**. All changes go through a PR.

### Creating a PR
```bash
git checkout -b <type>/<short-description>
# ... make changes ...
git push origin <branch>
gh pr create --title "<type>: <description>"
```

### PR title — Conventional Commits (required, blocks merge)
Format: `<type>: <short description in imperative mood>`

| Type | When to use |
|---|---|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `docs` | Documentation only |
| `test` | Adding or updating tests |
| `ci` | CI/CD workflow changes |
| `chore` | Dependency updates, config, tooling |
| `revert` | Reverting a previous commit |
| `wip` | Work in progress (avoid merging) |

### Quality checks (all run on every PR)
| Check | Blocks merge? |
|---|---|
| Ruff lint + format | Yes |
| Mypy type check | Yes |
| pip-audit CVE scan | Yes |
| Pytest + coverage | Yes |
| PR title (conventional commits) | Yes |
| Vulture dead code | No — informational only |

---

## Text Layers

### 1. UI + Communication → `strings.py` (i18n-ready)

Any text the user reads as interface or conversation lives in `orchestrator/strings.py`.
Access via `t("key")` — never hardcode these strings at call sites.

### 2. Technical errors → `errors.py` (English, coded)

Exceptions and error output use coded messages via `errors.e("CODE", **kwargs)`.
Format: `{MODULE}-{SEQ}: {message}` — always English.

### 3. Operational logs → English, inline

Debug/status messages via `output.debug/status` — for developers, no catalog needed.

---

## Connector Authentication

All connectors must handle their own auth flow. The user configures `connectors.yaml` and runs YANA.
No external setup commands required for auth to work.

- **Credentials (e.g. Garmin)**: reads from `credentials_file` path in `connectors.yaml`. Prompts securely on first run, saves tokens for reuse.
- **Google OAuth**: one-time browser consent on first run, token auto-refreshed thereafter.

Never hardcode credentials. Never assume tokens exist.

---

## What NOT to change without discussion

1. Sanctum writer block format: `<<<FILE:name>>>..<<<END>>>` — changing breaks all existing LLM prompts
2. `_auto_task` thresholds (120 chars, 6 turns) — affects cost/quality tradeoff calibrated for Portuguese conversation
3. `strip_markdown()` in `voice.py` — called before TTS. YANA writes naturally; pipeline handles conversion.
4. Alembic migration files once applied — never edit a migration that has been committed and run in any environment. Create a new one instead.
5. PostgreSQL / Neo4j separation — operational data stays in PostgreSQL, episodic memory stays in Neo4j.
