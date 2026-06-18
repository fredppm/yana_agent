"""
tests/test_sanctum_writer.py — unit tests for sanctum_writer.py pure parsing logic.

_parse_and_write returns {field_name: content} without writing to disk.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import profiles
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
        response = "<<<FILE:BOND>>>\ncontent A\n<<<END>>>\n<<<FILE:PERSONA>>>\ncontent B\n<<<END>>>"
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


def _first_breath_llm_response(owner_name: str) -> str:
    """Minimal valid First Breath LLM output with the given OWNER_NAME."""
    return (
        f"<<<FILE:OWNER_NAME>>>\n{owner_name}\n<<<END>>>\n"
        "<<<FILE:PERSONA>>>\nYANA, a personal life partner.\n<<<END>>>\n"
        "<<<FILE:CREED>>>\nTo help the owner.\n<<<END>>>\n"
        "<<<FILE:BOND>>>\nThe owner is an engineer.\n<<<END>>>\n"
        "<<<FILE:PULSE>>>\nDaily check-ins.\n<<<END>>>\n"
        '<<<FILE:PULSE_CONFIG>>>\nquiet_hours: "23:00-07:00"\n<<<END>>>'
    )


@pytest.mark.tui_integration
def test_first_breath_pipeline_simple_name(db):
    """parse → create_first_owner_and_profile: plain first name ends up in DB correctly."""
    written = sanctum_writer._parse_and_write(_first_breath_llm_response("Fred"))
    assert written.get("OWNER_NAME") == "Fred"
    owner_id, _ = profiles.create_first_owner_and_profile(written)
    with db.Session(db._get_engine()) as s:
        owner = s.get(db.Owner, owner_id)
    assert owner.name == "Fred"
    assert db.list_profiles_sync()[0]["label"] == "Fred — Default"


@pytest.mark.tui_integration
def test_first_breath_pipeline_full_name_from_llm(db):
    """LLM writes full name → stored as-is."""
    written = sanctum_writer._parse_and_write(_first_breath_llm_response("Fred Mourao"))
    assert written.get("OWNER_NAME") == "Fred Mourao"
    owner_id, _ = profiles.create_first_owner_and_profile(written)
    with db.Session(db._get_engine()) as s:
        owner = s.get(db.Owner, owner_id)
    assert owner.name == "Fred Mourao"
    assert db.list_profiles_sync()[0]["label"] == "Fred Mourao — Default"


@pytest.mark.tui_integration
def test_first_breath_pipeline_missing_owner_name(db):
    """LLM omits OWNER_NAME entirely → falls back to 'User'."""
    response = "<<<FILE:PERSONA>>>\nYANA.\n<<<END>>>\n<<<FILE:BOND>>>\nThe owner.\n<<<END>>>"
    written = sanctum_writer._parse_and_write(response)
    assert "OWNER_NAME" not in written
    owner_id, _ = profiles.create_first_owner_and_profile(written)
    with db.Session(db._get_engine()) as s:
        owner = s.get(db.Owner, owner_id)
    assert owner.name == "User"


# ---------------------------------------------------------------------------
# _parse_title_response
# ---------------------------------------------------------------------------


class TestParseTitleResponse:
    def test_valid_title_and_summary(self):
        response = (
            "<<<TITLE>>>\nDiscussed project architecture and deployment strategy\n<<<END>>>\n"
            "<<<SUMMARY>>>\nWe reviewed the microservices layout. "
            "Pending: decide on message broker.\n<<<END>>>"
        )
        result = sanctum_writer._parse_title_response(response)
        assert "title" in result
        assert "summary" in result
        assert "architecture" in result["title"]
        assert "message broker" in result["summary"]

    def test_title_only_no_summary(self):
        response = "<<<TITLE>>>\nQuick check-in about weekend plans\n<<<END>>>"
        result = sanctum_writer._parse_title_response(response)
        assert "title" in result
        assert "summary" not in result

    def test_empty_response_returns_empty(self):
        result = sanctum_writer._parse_title_response("")
        assert result == {}

    def test_no_blocks_returns_empty(self):
        result = sanctum_writer._parse_title_response("Here is some text without blocks.")
        assert result == {}

    def test_empty_title_returns_empty(self):
        response = "<<<TITLE>>>\n\n<<<END>>>"
        result = sanctum_writer._parse_title_response(response)
        assert result == {}

    def test_empty_summary_excluded(self):
        response = "<<<TITLE>>>\nValid title here\n<<<END>>>\n<<<SUMMARY>>>\n\n<<<END>>>"
        result = sanctum_writer._parse_title_response(response)
        assert "title" in result
        assert "summary" not in result

    def test_title_truncated_to_200_chars(self):
        long_title = "x" * 300
        response = f"<<<TITLE>>>\n{long_title}\n<<<END>>>"
        result = sanctum_writer._parse_title_response(response)
        assert len(result["title"]) == 200

    def test_multiline_summary_preserved(self):
        response = (
            "<<<TITLE>>>\nProject review session\n<<<END>>>\n"
            "<<<SUMMARY>>>\nLine one.\nLine two.\nLine three.\n<<<END>>>"
        )
        result = sanctum_writer._parse_title_response(response)
        assert "Line one." in result["summary"]
        assert "Line two." in result["summary"]

    def test_surrounding_text_ignored(self):
        response = (
            "Here is my analysis:\n\n"
            "<<<TITLE>>>\nThe real title\n<<<END>>>\n"
            "And some more text\n"
            "<<<SUMMARY>>>\nThe real summary\n<<<END>>>\n"
            "Done!"
        )
        result = sanctum_writer._parse_title_response(response)
        assert result["title"] == "The real title"
        assert result["summary"] == "The real summary"


class TestWriteSessionTitle:
    def test_returns_empty_dict_on_empty_messages(self):
        result = sanctum_writer.write_session_title([])
        assert result == {}

    def test_returns_empty_dict_on_exception(self, monkeypatch):
        """write_session_title never raises — returns empty dict on any error."""
        monkeypatch.setattr(
            sanctum_writer.prov,
            "call_llm",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        result = sanctum_writer.write_session_title(
            [{"role": "user", "content": "hello"}],
            config={"litellm_url": "http://test", "models": {"conversation_fast": "test"}},
        )
        assert result == {}

    def test_parses_valid_llm_response(self, monkeypatch):
        fake_response = (
            "<<<TITLE>>>\nDiscussing weekend hiking plans\n<<<END>>>\n"
            "<<<SUMMARY>>>\nWe decided on the mountain trail.\n<<<END>>>"
        )
        monkeypatch.setattr(sanctum_writer.prov, "call_llm", lambda *a, **kw: fake_response)
        result = sanctum_writer.write_session_title(
            [{"role": "user", "content": "hello"}],
            config={"litellm_url": "http://test", "models": {"conversation_fast": "test"}},
        )
        assert result["title"] == "Discussing weekend hiking plans"
        assert result["summary"] == "We decided on the mountain trail."
