"""
Pytest configuration for YANA test suite.

Integration tests (marked with @pytest.mark.integration) require real
credentials and a live network connection. They are skipped automatically
when credentials are not present, so they never block CI.

TUI integration tests (marked with @pytest.mark.tui_integration) spin up
a real PostgreSQL container via testcontainers. They require Docker to be
running and are skipped otherwise.

Run integration tests manually:
    pytest -m integration -v
    pytest -m tui_integration -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: requires real credentials and network — skipped when credentials absent",
    )
    config.addinivalue_line(
        "markers",
        "tui_integration: requires Docker (spins up PostgreSQL via testcontainers)",
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    gcal_creds = Path("~/.yana/google_credentials.json").expanduser()
    garmin_token = Path("~/.yana/tokens/garmin_fred").expanduser()

    for item in items:
        if not item.get_closest_marker("integration"):
            continue
        path_str = str(item.fspath)
        needs_google = any(kw in path_str for kw in ("calendar", "tasks"))
        needs_garmin = "garmin" in path_str
        if needs_google and not gcal_creds.exists():
            item.add_marker(pytest.mark.skip(reason="~/.yana/google_credentials.json not found"))
        elif needs_garmin and not garmin_token.exists():
            item.add_marker(
                pytest.mark.skip(
                    reason="~/.yana/tokens/garmin_fred not found — run once to seed tokens"
                )
            )


# ---------------------------------------------------------------------------
# PostgreSQL TestContainer — session-scoped, starts once for all tui tests
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    try:
        import subprocess

        r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


@pytest.fixture(scope="session")
def pg_container():
    """Spin up a real PostgreSQL container. Skipped when Docker unavailable."""
    if not _docker_available():
        pytest.skip("Docker not available — skipping tui_integration tests")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def pg_url(pg_container):
    """psycopg2-compatible URL for the test PostgreSQL container."""
    url: str = pg_container.get_connection_url()
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


@pytest.fixture()
def db(pg_url):
    """
    Per-test: point store.py at the test container, ensure schema exists,
    yield the store module, then truncate all tables for isolation.

    Uses SQLAlchemy create_all (faster than Alembic for tests — no stamp
    overhead, no migration history needed).
    """
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import store

    # Reset module-level engine cache and point at test container
    store._engine_cache = None
    _orig_load_url = store._load_url
    store._load_url = lambda: pg_url

    store.Base.metadata.create_all(store._get_engine())

    yield store

    # Truncate in FK-safe order
    from sqlalchemy import text

    with store.Session(store._get_engine()) as session:
        for tbl in ("connectors", "sessions", "profiles", "owners"):
            session.execute(text(f"TRUNCATE {tbl} CASCADE"))
        session.commit()

    store._load_url = _orig_load_url
    store._engine_cache = None
