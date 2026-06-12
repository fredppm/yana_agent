"""
Pytest configuration for YANA test suite.

Integration tests (marked with @pytest.mark.integration) require real
credentials and a live network connection. They are skipped automatically
when credentials are not present, so they never block CI.

Run integration tests manually:
    pytest -m integration -v
"""

from __future__ import annotations

from pathlib import Path

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: requires real credentials and network — skipped when credentials absent",
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
