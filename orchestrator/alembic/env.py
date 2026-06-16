import sys
from pathlib import Path

# Ensure orchestrator/ is on sys.path so store.py is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic import context
from store import Base, _load_url

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_load_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from store import _get_engine

    # Reuse the shared engine so we don't open a second cold TCP connection.
    connectable = _get_engine()
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
