"""
tests/test_sanctum_writer.py — unit tests for sanctum_writer.py pure parsing logic.

_parse_and_write is tested by mocking sanctum_path() so no actual files are written.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import sanctum_writer

# ---------------------------------------------------------------------------
# _parse_and_write
# ---------------------------------------------------------------------------


class TestParseAndWrite:
    def _run(self, response: str) -> dict:
        """Run _parse_and_write with a real temp dir as sanctum."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("sanctum_writer.core.sanctum_path", return_value=Path(tmpdir)):
                return sanctum_writer._parse_and_write(response)

    def test_single_file_parsed(self):
        response = "<<<FILE:BOND.md>>>\nsome content\n<<<END>>>"
        written = self._run(response)
        assert "BOND.md" in written
        assert written["BOND.md"] == "some content"

    def test_multiple_files_parsed(self):
        response = (
            "<<<FILE:BOND.md>>>\ncontent A\n<<<END>>>\n<<<FILE:MEMORY.md>>>\ncontent B\n<<<END>>>"
        )
        written = self._run(response)
        assert set(written.keys()) == {"BOND.md", "MEMORY.md"}

    def test_subdirectory_created(self):
        response = "<<<FILE:sessions/2026-06-10.md>>>\nlog content\n<<<END>>>"
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("sanctum_writer.core.sanctum_path", return_value=Path(tmpdir)):
                written = sanctum_writer._parse_and_write(response)
                assert "sessions/2026-06-10.md" in written
                assert (Path(tmpdir) / "sessions" / "2026-06-10.md").exists()

    def test_content_written_to_disk(self):
        response = "<<<FILE:PERSONA.md>>>\nhello world\n<<<END>>>"
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("sanctum_writer.core.sanctum_path", return_value=Path(tmpdir)):
                sanctum_writer._parse_and_write(response)
                content = (Path(tmpdir) / "PERSONA.md").read_text(encoding="utf-8")
                assert content == "hello world"

    def test_empty_response_returns_empty(self):
        written = self._run("")
        assert written == {}

    def test_no_blocks_returns_empty(self):
        written = self._run("Here is some text with no file blocks at all.")
        assert written == {}

    def test_multiline_content_preserved(self):
        response = "<<<FILE:BOND.md>>>\nline one\nline two\nline three\n<<<END>>>"
        written = self._run(response)
        assert "line one" in written["BOND.md"]
        assert "line two" in written["BOND.md"]

    # Security: path traversal rejection
    def test_path_traversal_rejected(self, capsys):
        response = "<<<FILE:../../evil.txt>>>\nbad content\n<<<END>>>"
        written = self._run(response)
        assert written == {}

    def test_absolute_path_rejected(self, capsys):
        response = "<<<FILE:/etc/passwd>>>\nbad content\n<<<END>>>"
        written = self._run(response)
        assert written == {}

    def test_dot_path_rejected(self, capsys):
        response = "<<<FILE:./sneaky.md>>>\nbad content\n<<<END>>>"
        written = self._run(response)
        assert written == {}

    def test_valid_path_with_subdir_accepted(self):
        response = "<<<FILE:sessions/2026-01-01.md>>>\ncontent\n<<<END>>>"
        written = self._run(response)
        assert "sessions/2026-01-01.md" in written

    def test_whitespace_in_filename_stripped(self):
        # Filename may have trailing whitespace from LLM
        response = "<<<FILE:  BOND.md  >>>\ncontent\n<<<END>>>"
        written = self._run(response)
        assert "BOND.md" in written


# ---------------------------------------------------------------------------
# _build_sanctum_prompt
# ---------------------------------------------------------------------------


class TestBuildSanctumPrompt:
    def test_contains_all_file_names(self):
        files = ["BOND.md", "MEMORY.md"]
        prompt = sanctum_writer._build_sanctum_prompt(files, "2026-06-10")
        assert "BOND.md" in prompt
        assert "MEMORY.md" in prompt

    def test_contains_session_file(self):
        prompt = sanctum_writer._build_sanctum_prompt([], "2026-06-10")
        assert "sessions/2026-06-10.md" in prompt

    def test_contains_format_instructions(self):
        prompt = sanctum_writer._build_sanctum_prompt([], "2026-06-10")
        assert "<<<FILE:" in prompt
        assert "<<<END>>>" in prompt

    def test_first_breath_files_vs_regular(self):
        fb_prompt = sanctum_writer._build_sanctum_prompt(
            sanctum_writer.FIRST_BREATH_FILES, "2026-06-10"
        )
        reg_prompt = sanctum_writer._build_sanctum_prompt(
            sanctum_writer.REGULAR_SESSION_FILES, "2026-06-10"
        )
        # First breath requests more files → longer prompt
        assert len(fb_prompt) > len(reg_prompt)
        # The file lists themselves must differ
        assert len(sanctum_writer.FIRST_BREATH_FILES) > len(sanctum_writer.REGULAR_SESSION_FILES)
        # Regular session should NOT request CREED.md (first-breath-only file)
        # Check via count of occurrences: CREED.md appears once (rules body) vs twice (rules + file list)
        assert fb_prompt.count("CREED.md") > reg_prompt.count("CREED.md")
