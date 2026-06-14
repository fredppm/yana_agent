# YANA Agent — Claude Code Guide

This file is the authoritative contract for any Claude instance working in this repo.
Read it fully before touching code. Changes that break the contracts below will fail tests.

---

## Project Layout

```
yana_agent/
  orchestrator/           # Python entry point + all runtime logic
    main.py               # CLI: --text (text mode) | --pulse (PULSE run) | default (voice)
    core.py               # System prompt assembly, session persistence, sanctum state
    providers.py          # Multi-model LLM routing (Anthropic / Bedrock / OpenAI)
    voice.py              # STT (faster-whisper) + TTS (edge-tts)
    sanctum_writer.py     # Post-session sanctum persistence via structured LLM call
    config/
      providers.yaml      # Model routing config — edit here to change models/providers
    tests/                # Pytest suite for pure logic (no external deps)
  skills/
    agent-yana/           # YANA skill definition
      SKILL.md            # Identity seed (read-only at runtime)
      references/         # first-breath.md, memory-guidance.md, etc.
      scripts/            # init-sanctum.py (one-time setup)
  data/
    agent-yana/           # Sanctum — YANA's persistent memory (gitignored)
      PERSONA.md
      CREED.md
      BOND.md             # Who Fred IS (enduring truths)
      MEMORY.md           # Current situations, open threads
      CAPABILITIES.md
      PULSE.md
      pulse-config.yaml
      sessions/           # Per-date session logs
```

---

## Public Contracts — must not break

### core.py

| Function | Signature | Contract |
|---|---|---|
| `sanctum_exists()` | `() -> bool` | True iff `data/agent-yana/PERSONA.md` exists |
| `sanctum_path()` | `() -> Path` | Always `project_root/data/agent-yana` |
| `load_system_prompt()` | `() -> str` | Raises `FileNotFoundError` if SKILL.md missing |
| `is_quiet_hours(pulse_config?)` | `(dict?) -> bool` | Parses `quiet_hours: "HH:MM-HH:MM"` — handles overnight windows (e.g. 23:00–07:00) |
| `save_session_log(messages, session_id)` | `(list[dict], str) -> None` | Writes to `data/agent-yana/sessions/session-{id}.md` |

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

## Sanctum File Roles

- **BOND.md** — enduring truths about Fred. Things that would still be true tomorrow, next year.
- **MEMORY.md** — current situations, open threads, tracked items. Changes each session.
- **PERSONA.md** — YANA's identity as it crystallized through First Breath.
- **CREED.md** — mission, values, standing orders calibrated to Fred.
- **PULSE.md** — autonomous routine descriptions.
- **pulse-config.yaml** — machine-readable PULSE config (quiet hours, scheduled tasks).
- **sessions/{date}.md** — raw session log, written every session.

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

## Git Workflow

### Branch protection
`main` is protected — **never push directly**. All changes go through a PR.

### Creating a PR
```bash
git checkout -b <type>/<short-description>   # e.g. feat/google-calendar-integration
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

Examples: `feat: add Garmin stress trigger handler` · `fix: resolve overnight quiet hours window` · `chore: bump anthropic sdk to 0.45`

### Quality checks (all run on every PR)
| Check | Blocks merge? |
|---|---|
| Ruff lint + format | Yes |
| Mypy type check | Yes |
| pip-audit CVE scan | Yes |
| Pytest + coverage | Yes |
| PR title (conventional commits) | Yes |
| Vulture dead code | No — informational only |

Errors from ruff and mypy appear **inline in the PR diff**. The full table is in the "Summary" tab of the Actions run.

---

## Text Layers

All user-facing text is separated into three distinct layers:

### 1. UI + Communication → `strings.py` (i18n-ready)

Any text the user reads as interface or conversation lives in `orchestrator/strings.py`.
Access via `t("key")` — never hardcode these strings at call sites.

```python
from strings import t
print(t("banner"))           # UI chrome
input(f"{t('user_label')}: ")  # conversation label
```

| Category | Examples | Keys |
|---|---|---|
| UI | banner, setup messages, output prefixes | `banner`, `sanctum_missing`, `warn_prefix`, `error_prefix` |
| Communication | greetings, conversational labels | `greeting`, `user_label` |

To add a string: add a key to `_STRINGS["pt_BR"]` in `strings.py`.
To add a locale: add a new locale dict and change `_LOCALE`. Call sites don't change.

### 2. Technical errors → `errors.py` (English, coded)

Exceptions and error output use coded messages via `errors.e("CODE", **kwargs)`.
Format: `{MODULE}-{SEQ}: {message}` — always English.

| Module | File |
|---|---|
| `CFG` | config / providers.yaml |
| `LLM` | providers.py |
| `SYS` | core.py |
| `MEM` | sanctum_writer.py |
| `VOX` | voice.py |

### 3. Operational logs → English, inline

Debug/status messages that go through `output.debug/status` are English inline strings.
These are for developers and operators, not end users — no catalog needed.

```python
output.debug("listening...")
output.status("saving sanctum...")
```

---

## Connector Authentication

All connectors — MCP-backed or pure Python — must handle their own auth
flow. The user configures `connectors.yaml` and runs YANA. No external
setup commands should be required for auth to work.

### Scenario 1 — Username/password credentials (e.g. Garmin)

The connector reads a `credentials_file` (JSON with `email`/`password`)
from a path configured in `connectors.yaml`. That file lives outside the
repo (e.g. `~/.yana/credentials/garmin_fred.json`) and is never committed.

On first run, if the credentials file is missing or incomplete, the
connector prompts securely in the terminal (echo suppressed — see
`_read_password()` in `connectors/garmin.py`). After a successful login,
tokens are saved to `token_dir` and reused on subsequent runs — no
password prompt again unless tokens expire.

### Scenario 2 — Google OAuth app credentials (e.g. Calendar, Gmail)

One-time infrastructure step (done once per Google Cloud project, not
per session):
1. Create a project in Google Cloud Console
2. Enable the relevant API (Calendar API, Gmail API, etc.)
3. Create OAuth 2.0 credentials (Desktop app) and download the JSON
4. Save to the path set in `connectors.yaml` (e.g. `credentials_file:
   "~/.yana/google_credentials.json"`)

On first run, the connector opens a browser for OAuth consent and saves
the token to `token_file`. Subsequent runs use the saved token
(auto-refreshed when expired) — no browser needed again.

### What NOT to do

- Never instruct the user to run an external auth command
  (e.g. `uvx some-server auth`) before starting YANA
- Never hardcode credentials or tokens in `connectors.yaml` or source code
- Never assume tokens exist — the connector must handle the first-run
  auth case gracefully

---

## What NOT to change without discussion

1. Sanctum path: `data/agent-yana/` — changing breaks all existing sanctums
2. Session log filename pattern: `session-{id}.md` — changing breaks `load_recent_sessions()`
3. Sanctum writer block format: `<<<FILE:name>>>..<<<END>>>` — changing breaks all existing LLM prompts
4. `_auto_task` thresholds (120 chars, 6 turns) — affects cost/quality tradeoff calibrated for Portuguese conversation
5. `strip_markdown()` in `voice.py` — called before TTS to clean symbols. YANA writes naturally; the pipeline handles conversion.
