# YANA — You Are Not Alone

Personal life partner and autonomous daily companion.

---

## Requirements

- Python 3.11+
- [Podman](https://podman.io/) or Docker with Compose
- AWS credentials configured (for Bedrock models via LiteLLM)

---

## Setup

### 1. Start infrastructure

```bash
# From the project root
docker-compose up -d        # or: podman compose up -d
```

This starts:
| Service | Port | Purpose |
|---|---|---|
| PostgreSQL 16 | 5432 | Profiles, sessions, sanctum |
| Neo4j 5 | 7687 | Episodic memory (Graphiti) |
| LiteLLM | 4000 | AWS Bedrock proxy |

### 2. Install Python dependencies

```bash
cd orchestrator
pip install -r requirements.txt
```

### 3. Run

```bash
python main.py --text     # text mode (TUI)
python main.py            # voice mode
python main.py --pulse    # autonomous PULSE run
```

On first launch with no profiles in the database, YANA enters **First Breath** — an onboarding conversation where she learns who you are. The sanctum is written to PostgreSQL at the end of the session.

---

## Database

YANA uses **PostgreSQL** for operational data (profiles, sessions, sanctum fields) and **Neo4j** for episodic memory via [Graphiti](https://github.com/getzep/graphiti).

### Schema is managed automatically

The database schema is managed with [Alembic](https://alembic.sqlalchemy.org/). On every startup, YANA runs:

```python
alembic upgrade head  # applied automatically in store.init_schema_sync()
```

This is idempotent — if the schema is already up to date, nothing happens. **You never need to update the database manually.**

### Adding or changing a column

```bash
cd orchestrator

# 1. Edit the SQLAlchemy model in store.py
# 2. Generate the migration
alembic revision --autogenerate -m "describe the change"

# 3. Review the generated file in alembic/versions/
#    For NOT NULL columns with existing rows, edit upgrade() to:
#      a. add column as nullable
#      b. backfill existing rows
#      c. alter to NOT NULL

# 4. Commit the migration file alongside the model change
git add alembic/versions/<new_file>.py store.py
git commit -m "chore: add <column> to <table>"

# 5. Next startup applies it automatically
```

### Other Alembic commands

```bash
alembic history          # list all migrations
alembic current          # show current DB revision
alembic downgrade -1     # rollback one migration
alembic downgrade base   # rollback everything
```

---

## Configuration

Edit `orchestrator/config/providers.yaml` to configure:
- LLM model routing (conversation, pulse, first breath)
- PostgreSQL connection URL
- Neo4j / LiteLLM endpoints

---

## Development

```bash
cd orchestrator
python -m pytest tests/ -v
```

Tests have no external dependencies — no network, no database, no filesystem side effects outside tmp.

See `CLAUDE.md` for the full architecture reference and public contracts.
