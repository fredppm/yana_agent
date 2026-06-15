"""
tests/test_sanctum_writer.py — unit tests for sanctum_writer.py pure parsing logic.

_parse_and_write returns {filename: content} without writing to disk.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import sanctum_writer

# ---------------------------------------------------------------------------
# _parse_and_write
# ---------------------------------------------------------------------------


class TestParseAndWrite:
    def test_single_file_parsed(self):
        response = "<<<FILE:BOND.md>>>\nsome content\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert "BOND.md" in written
        assert written["BOND.md"] == "some content"

    def test_multiple_files_parsed(self):
        response = (
            "<<<FILE:BOND.md>>>\ncontent A\n<<<END>>>\n<<<FILE:MEMORY.md>>>\ncontent B\n<<<END>>>"
        )
        written = sanctum_writer._parse_and_write(response)
        assert set(written.keys()) == {"BOND.md", "MEMORY.md"}

    def test_subdirectory_path_accepted(self):
        response = "<<<FILE:sessions/2026-06-10.md>>>\nlog content\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert "sessions/2026-06-10.md" in written
        assert written["sessions/2026-06-10.md"] == "log content"

    def test_content_returned(self):
        response = "<<<FILE:PERSONA.md>>>\nhello world\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert written["PERSONA.md"] == "hello world"

    def test_empty_response_returns_empty(self):
        written = sanctum_writer._parse_and_write("")
        assert written == {}

    def test_no_blocks_returns_empty(self):
        written = sanctum_writer._parse_and_write("Here is some text with no file blocks at all.")
        assert written == {}

    def test_multiline_content_preserved(self):
        response = "<<<FILE:BOND.md>>>\nline one\nline two\nline three\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert "line one" in written["BOND.md"]
        assert "line two" in written["BOND.md"]

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
        response = "<<<FILE:./sneaky.md>>>\nbad content\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert written == {}

    def test_valid_path_with_subdir_accepted(self):
        response = "<<<FILE:sessions/2026-01-01.md>>>\ncontent\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert "sessions/2026-01-01.md" in written

    def test_whitespace_in_filename_stripped(self):
        # Filename may have trailing whitespace from LLM
        response = "<<<FILE:  BOND.md  >>>\ncontent\n<<<END>>>"
        written = sanctum_writer._parse_and_write(response)
        assert "BOND.md" in written


# ---------------------------------------------------------------------------
# _build_sanctum_prompt
# ---------------------------------------------------------------------------


class TestBuildSanctumPrompt:
    def test_contains_all_file_names(self):
        files = ["BOND.md", "MEMORY.md"]
        prompt = sanctum_writer._build_sanctum_prompt(files)
        assert "BOND.md" in prompt
        assert "MEMORY.md" in prompt

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
        # Regular session should NOT request CREED.md (first-breath-only file)
        assert fb_prompt.count("CREED.md") > reg_prompt.count("CREED.md")
