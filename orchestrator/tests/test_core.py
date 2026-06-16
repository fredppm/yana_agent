"""
tests/test_core.py — unit tests for core.py pure logic.
"""

import sys
from datetime import datetime
from datetime import time as dtime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import core


def _at(hour: int, minute: int = 0):
    """Context manager: mock datetime.now().time() to a fixed local time."""
    return patch(  # type: ignore[call-overload]
        "core.datetime",
        **{
            "now.return_value.time.return_value": dtime(hour, minute),
            "strptime.side_effect": datetime.strptime,
        },
    )


def _quiet(window: str):
    """Context manager: mock load_pulse_config to return a specific quiet_hours."""
    return patch("core.load_pulse_config", return_value={"quiet_hours": window})


# ---------------------------------------------------------------------------
# is_quiet_hours
# ---------------------------------------------------------------------------


class TestIsQuietHours:
    def test_inside_daytime_window(self):
        with _quiet("09:00-18:00"), _at(12):
            assert core.is_quiet_hours() is True

    def test_outside_daytime_window(self):
        with _quiet("09:00-18:00"), _at(20):
            assert core.is_quiet_hours() is False

    def test_overnight_window_after_start(self):
        with _quiet("23:00-07:00"), _at(23, 30):
            assert core.is_quiet_hours() is True

    def test_overnight_window_before_end(self):
        with _quiet("23:00-07:00"), _at(6):
            assert core.is_quiet_hours() is True

    def test_overnight_window_outside(self):
        with _quiet("23:00-07:00"), _at(12):
            assert core.is_quiet_hours() is False

    def test_exact_boundary_start(self):
        with _quiet("23:00-07:00"), _at(23, 0):
            assert core.is_quiet_hours() is True

    def test_exact_boundary_end(self):
        with _quiet("23:00-07:00"), _at(7, 0):
            assert core.is_quiet_hours() is True

    def test_invalid_format_returns_false(self):
        with patch("core.load_pulse_config", return_value={"quiet_hours": "not-a-time"}):
            assert core.is_quiet_hours() is False
        with patch("core.load_pulse_config", return_value={"quiet_hours": ""}):
            assert core.is_quiet_hours() is False
        with patch("core.load_pulse_config", return_value={}):
            # falls back to default "23:00-07:00" — just check it doesn't crash
            assert isinstance(core.is_quiet_hours(), bool)


# ---------------------------------------------------------------------------
# create_first_owner_and_profile (integration — requires PostgreSQL)
# ---------------------------------------------------------------------------


import pytest


@pytest.mark.tui_integration
def test_create_first_owner_and_profile_simple_name(db):
    """create_first_owner_and_profile with a plain first name creates owner + profile correctly."""
    owner_id, profile_id = core.create_first_owner_and_profile({"OWNER_NAME": "Fred"})
    profiles = db.list_profiles_sync()
    assert len(profiles) == 1
    assert profiles[0]["label"] == "Fred — Default"
    from sqlalchemy.orm import Session
    with Session(db._get_engine()) as s:
        owner = s.get(db.Owner, owner_id)
    assert owner is not None
    assert owner.name == "Fred"


@pytest.mark.tui_integration
def test_create_first_owner_and_profile_full_name_preserved(db):
    """When LLM writes full name, it is stored as-is."""
    owner_id, profile_id = core.create_first_owner_and_profile({"OWNER_NAME": "Fred Mourao"})
    from sqlalchemy.orm import Session
    with Session(db._get_engine()) as s:
        owner = s.get(db.Owner, owner_id)
    assert owner.name == "Fred Mourao"
    profiles = db.list_profiles_sync()
    assert profiles[0]["label"] == "Fred Mourao — Default"


@pytest.mark.tui_integration
def test_create_first_owner_and_profile_empty_name_fallback(db):
    """Empty OWNER_NAME falls back to 'User'."""
    owner_id, profile_id = core.create_first_owner_and_profile({})
    from sqlalchemy.orm import Session
    with Session(db._get_engine()) as s:
        owner = s.get(db.Owner, owner_id)
    assert owner.name == "User"
    profiles = db.list_profiles_sync()
    assert profiles[0]["label"] == "User — Default"
