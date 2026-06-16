"""
tests/test_sanctum_writer.py — unit tests for sanctum_writer.py pure parsing logic.

_parse_and_write returns {field_name: content} without writing to disk.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import sanctum_writer

# ---------------------------------------------------------------------------
# _parse_and_write
# ---------------------------------------------------------------------------


class TestParseAndWrite:
    def test_single_field_parsed(self):
        response = "<<<FILE:BOND>>>\nsome content\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert "BOND" in written
        assert written["BOND"] == "some content"

    def test_multiple_fields_parsed(self):
        response = (
            "<<<FILE:BOND>>>\ncontent A\n<<<END>>>\n<<<FILE:PERSONA>>>\ncontent B\n<<<END>>>"
        )
        written = sanctum_writer._parse_and_write(response)
        assert set(written.keys()) == {"BOND", "PERSONA"}

    def test_content_returned(self):
        response = "<<<FILE:PERSONA>>>\nhello world\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert written["PERSONA"] == "hello world"

    def test_empty_response_returns_empty(self):
        written = sanctum_writer._parse_and_write("")
        assert written == {}

    def test_no_blocks_returns_empty(self):
        written = sanctum_writer._parse_and_write("Here is some text with no file blocks at all.")
        assert written == {}

    def test_multiline_content_preserved(self):
        response = "<<<FILE:BOND>>>\nline one\nline two\nline three\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert "line one" in written["BOND"]
        assert "line two" in written["BOND"]

    # Security: path traversal rejection
    def test_path_traversal_rejected(self, capsys):
        response = "<<<FILE:../../evil.txt>>>\nbad content\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert written == {}

    def test_absolute_path_rejected(self, capsys):
        response = "<<<FILE:/etc/passwd>>>\nbad content\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert written == {}

    def test_dot_path_rejected(self, capsys):
        response = "<<<FILE:./sneaky>>>\nbad content\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert written == {}

    def test_whitespace_in_name_stripped(self):
        response = "<<<FILE:  BOND  >>>\ncontent\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert "BOND" in written


# ---------------------------------------------------------------------------
# _build_sanctum_prompt
# ---------------------------------------------------------------------------


class TestBuildSanctumPrompt:
    def test_contains_all_field_names(self):
        files = ["BOND", "CREED"]
        prompt = sanctum_writer._build_sanctum_prompt(files)
        assert "BOND" in prompt
        assert "CREED" in prompt

    def test_contains_format_instructions(self):
        prompt = sanctum_writer._build_sanctum_prompt([])
        assert "<<<FILE:" in prompt
        assert "<<<END>>>" in prompt

    def test_first_breath_files_vs_regular(self):
        fb_prompt = sanctum_writer._build_sanctum_prompt(sanctum_writer.FIRST_BREATH_FILES)
        reg_prompt = sanctum_writer._build_sanctum_prompt(sanctum_writer.REGULAR_SESSION_FILES)
        # First breath requests more files -> longer prompt
        assert len(fb_prompt) > len(reg_prompt)
        # The file lists themselves must differ
        assert len(sanctum_writer.FIRST_BREATH_FILES) > len(sanctum_writer.REGULAR_SESSION_FILES)
        # Regular session should NOT request CREED (first-breath-only field)
        assert fb_prompt.count("CREED") > reg_prompt.count("CREED")


# ---------------------------------------------------------------------------
# First Breath pipeline: LLM output → parse → create owner in DB
# ---------------------------------------------------------------------------


import pytest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import core


def _first_breath_llm_response(owner_name: str) -> str:
    """Minimal valid First Breath LLM output with the given OWNER_NAME."""
    return (
        f"<<<FILE:OWNER_NAME>>>\n{owner_name}\n<<<END>>>\n"
        "<<<FILE:PERSONA>>>\nYANA, a personal life partner.\n<<<END>>>\n"
        "<<<FILE:CREED>>>\nTo help the owner.\n<<<END>>>\n"
        "<<<FILE:BOND>>>\nThe owner is an engineer.\n<<<END>>>\n"
        "<<<FILE:PULSE>>>\nDaily check-ins.\n<<<END>>>\n"
        "<<<FILE:PULSE_CONFIG>>>\nquiet_hours: \"23:00-07:00\"\n<<<END>>>"
    )


@pytest.mark.tui_integration
def test_first_breath_pipeline_simple_name(db):
    """parse → create_first_owner_and_profile: plain first name ends up in DB correctly."""
    written = sanctum_writer._parse_and_write(_first_breath_llm_response("Fred"))
    assert written.get("OWNER_NAME") == "Fred"
    owner_id, _ = core.create_first_owner_and_profile(written)
    with db.Session(db._get_engine()) as s:
        owner = s.get(db.Owner, owner_id)
    assert owner.username == "fred"
    assert owner.name == "Fred"
    assert db.list_profiles_sync()[0]["label"] == "Fred — Default"


@pytest.mark.tui_integration
def test_first_breath_pipeline_full_name_from_llm(db):
    """LLM writes full name → only first token becomes username, not OS fallback."""
    written = sanctum_writer._parse_and_write(_first_breath_llm_response("Fred Mourao"))
    assert written.get("OWNER_NAME") == "Fred Mourao"
    owner_id, _ = core.create_first_owner_and_profile(written)
    with db.Session(db._get_engine()) as s:
        owner = s.get(db.Owner, owner_id)
    assert owner.username == "fred"   # not "mourao" (old bug)
    assert owner.name == "Fred"
    assert db.list_profiles_sync()[0]["label"] == "Fred — Default"


@pytest.mark.tui_integration
def test_first_breath_pipeline_missing_owner_name(db):
    """LLM omits OWNER_NAME entirely → falls back to 'user', not OS username."""
    response = (
        "<<<FILE:PERSONA>>>\nYANA.\n<<<END>>>\n"
        "<<<FILE:BOND>>>\nThe owner.\n<<<END>>>"
    )
    written = sanctum_writer._parse_and_write(response)
    assert "OWNER_NAME" not in written
    owner_id, _ = core.create_first_owner_and_profile(written)
    with db.Session(db._get_engine()) as s:
        owner = s.get(db.Owner, owner_id)
    assert owner.username == "user"   # not OS username
