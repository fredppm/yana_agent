"""
tests/test_profiles.py — unit and integration tests for profiles.py.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import profiles

# ---------------------------------------------------------------------------
# create_first_owner_and_profile (integration — requires PostgreSQL)
# ---------------------------------------------------------------------------


@pytest.mark.tui_integration
def test_create_first_owner_and_profile_simple_name(db):
    """create_first_owner_and_profile with a plain first name creates owner + profile correctly."""
    owner_id, _profile_id = profiles.create_first_owner_and_profile({"OWNER_NAME": "Fred"})
    profile_list = db.list_profiles_sync()
    assert len(profile_list) == 1
    assert profile_list[0]["label"] == "Fred — Default"
    from sqlalchemy.orm import Session

    with Session(db._get_engine()) as s:
        owner = s.get(db.Owner, owner_id)
    assert owner is not None
    assert owner.name == "Fred"


@pytest.mark.tui_integration
def test_create_first_owner_and_profile_full_name_preserved(db):
    """When LLM writes full name, it is stored as-is."""
    owner_id, _profile_id = profiles.create_first_owner_and_profile({"OWNER_NAME": "Fred Mourao"})
    from sqlalchemy.orm import Session

    with Session(db._get_engine()) as s:
        owner = s.get(db.Owner, owner_id)
    assert owner.name == "Fred Mourao"
    profile_list = db.list_profiles_sync()
    assert profile_list[0]["label"] == "Fred Mourao — Default"


@pytest.mark.tui_integration
def test_create_first_owner_and_profile_empty_name_fallback(db):
    """Empty OWNER_NAME falls back to 'User'."""
    owner_id, _profile_id = profiles.create_first_owner_and_profile({})
    from sqlalchemy.orm import Session

    with Session(db._get_engine()) as s:
        owner = s.get(db.Owner, owner_id)
    assert owner.name == "User"
    profile_list = db.list_profiles_sync()
    assert profile_list[0]["label"] == "User — Default"
