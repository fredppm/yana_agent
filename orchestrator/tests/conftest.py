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
    credentials = Path("~/.yana/google_credentials.json").expanduser()
    if not credentials.exists():
        skip = pytest.mark.skip(reason="~/.yana/google_credentials.json not found")
        for item in items:
            if item.get_closest_marker("integration"):
                item.add_marker(skip)
