"""
test_programmer_mode.py — Story 1.1: programmer mode activation tests.

Tests:
  - Mode flag parsing (--programmer, --text, --voice combinations)
  - Sanctum load (happy path + hard stop)
  - Mode persistence (no implicit mode switch on unmarked input)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from programmer.mode import (
    InteractionMode,
    SanctumContext,
    _resolve_mode,
    is_explicit_mode_switch,
    parse_mode_switch,
)

# ---------------------------------------------------------------------------
# InteractionMode
# ---------------------------------------------------------------------------


class TestInteractionMode:
    def test_text_label(self) -> None:
        assert InteractionMode.TEXT.label() == "text"

    def test_voice_label(self) -> None:
        assert InteractionMode.VOICE.label() == "voice"

    def test_enum_values(self) -> None:
        assert InteractionMode.TEXT.value == "text"
        assert InteractionMode.VOICE.value == "voice"


# ---------------------------------------------------------------------------
# Mode flag resolution (_resolve_mode)
# ---------------------------------------------------------------------------


class TestResolveMode:
    def test_text_flag_returns_text(self) -> None:
        assert _resolve_mode(text_flag=True, voice_flag=False) is InteractionMode.TEXT

    def test_voice_flag_returns_voice(self) -> None:
        assert _resolve_mode(text_flag=False, voice_flag=True) is InteractionMode.VOICE

    def test_both_flags_text_wins(self) -> None:
        # Unambiguous safe default when both are set
        assert _resolve_mode(text_flag=True, voice_flag=True) is InteractionMode.TEXT

    def test_neither_flag_prompts_user_and_returns_text(self) -> None:
        with patch("builtins.input", return_value="t"):
            result = _resolve_mode(text_flag=False, voice_flag=False)
        assert result is InteractionMode.TEXT

    def test_neither_flag_prompts_user_and_returns_voice(self) -> None:
        with patch("builtins.input", return_value="v"):
            result = _resolve_mode(text_flag=False, voice_flag=False)
        assert result is InteractionMode.VOICE

    def test_full_word_text_accepted(self) -> None:
        with patch("builtins.input", return_value="text"):
            result = _resolve_mode(text_flag=False, voice_flag=False)
        assert result is InteractionMode.TEXT

    def test_full_word_voice_accepted(self) -> None:
        with patch("builtins.input", return_value="voice"):
            result = _resolve_mode(text_flag=False, voice_flag=False)
        assert result is InteractionMode.VOICE

    def test_invalid_input_retries_then_accepts(self) -> None:
        inputs = iter(["what?", "x", "text"])
        with patch("builtins.input", side_effect=inputs):
            result = _resolve_mode(text_flag=False, voice_flag=False)
        assert result is InteractionMode.TEXT


# ---------------------------------------------------------------------------
# Sanctum context load (from Neo4j via mocked memory)
# ---------------------------------------------------------------------------


class TestSanctumContext:
    def _mock_fields(self, fields: dict[str, str]):
        """Patch memory + core so SanctumContext.load() returns the given fields."""
        return [
            patch("memory.load_sanctum_fields_sync", return_value=fields),
            patch("core.get_active_profile", return_value="fred::pessoal"),
        ]

    def test_load_happy_path(self) -> None:
        fields = {
            "bond": "Fred is a developer.",
            "persona": "I am YANA.",
        }
        patches = self._mock_fields(fields)
        for p in patches:
            p.start()
        try:
            ctx = SanctumContext.load()
            assert "Fred is a developer" in ctx.bond
            assert "YANA" in ctx.persona
        finally:
            for p in patches:
                p.stop()

    def test_load_missing_profile_raises(self) -> None:
        with patch("core.get_active_profile", return_value=""):
            with pytest.raises(FileNotFoundError):
                SanctumContext.load()

    def test_load_no_persona_raises(self) -> None:
        patches = self._mock_fields({"bond": "something"})
        for p in patches:
            p.start()
        try:
            with pytest.raises(FileNotFoundError):
                SanctumContext.load()
        finally:
            for p in patches:
                p.stop()

    def test_load_partial_sanctum_fills_empty_strings(self) -> None:
        fields = {"persona": "I am YANA."}
        patches = self._mock_fields(fields)
        for p in patches:
            p.start()
        try:
            ctx = SanctumContext.load()
            assert ctx.persona == "I am YANA."
            assert ctx.bond == ""
        finally:
            for p in patches:
                p.stop()

    def test_as_context_string_includes_bond(self) -> None:
        ctx = SanctumContext(bond="Fred values speed.", persona="I am YANA.")
        result = ctx.as_context_string()
        assert "Fred values speed" in result

    def test_as_context_string_excludes_persona(self) -> None:
        ctx = SanctumContext(bond="Fred.", persona="YANA persona info.")
        result = ctx.as_context_string()
        assert "YANA persona info" not in result

    def test_as_context_string_truncates_at_max_tokens(self) -> None:
        long_text = "x" * 10_000
        ctx = SanctumContext(bond=long_text, persona="")
        result = ctx.as_context_string(max_tokens=100)
        assert len(result) <= 100 * 4 + 100  # allow for header text overhead


# ---------------------------------------------------------------------------
# Mode persistence — is_explicit_mode_switch
# ---------------------------------------------------------------------------


class TestModePeristence:
    def test_unmarked_input_is_not_mode_switch(self) -> None:
        unmarked = [
            "add a hello function",
            "run the tests",
            "what does this do?",
            "let's work on the auth module",
            "voice",  # just the word — not a command
            "text",  # just the word — not a command
        ]
        for text in unmarked:
            assert not is_explicit_mode_switch(text), f"Should not be a mode switch: {text!r}"

    def test_explicit_commands_are_mode_switches(self) -> None:
        explicit = [
            "/switch-mode voice",
            "/switch-mode text",
            "/switch-mode v",
            "/switch-mode t",
            "switch to voice",
            "switch to text",
        ]
        for cmd in explicit:
            assert is_explicit_mode_switch(cmd), f"Should be a mode switch: {cmd!r}"

    def test_case_insensitive(self) -> None:
        assert is_explicit_mode_switch("/SWITCH-MODE VOICE")
        assert is_explicit_mode_switch("Switch To Text")

    def test_parse_mode_switch_voice(self) -> None:
        assert parse_mode_switch("/switch-mode voice") is InteractionMode.VOICE
        assert parse_mode_switch("switch to voice") is InteractionMode.VOICE

    def test_parse_mode_switch_text(self) -> None:
        assert parse_mode_switch("/switch-mode text") is InteractionMode.TEXT
        assert parse_mode_switch("switch to text") is InteractionMode.TEXT

    def test_parse_mode_switch_non_command_returns_none(self) -> None:
        assert parse_mode_switch("add a function") is None
        assert parse_mode_switch("") is None


# ---------------------------------------------------------------------------
# run_programmer_mode hard stop on missing sanctum
# ---------------------------------------------------------------------------


class TestRunProgrammerModeHardStop:
    def test_exits_with_1_if_sanctum_missing(self) -> None:
        with (
            patch("core.get_active_profile", return_value=""),
            pytest.raises(SystemExit) as exc_info,
        ):
            from programmer.mode import run_programmer_mode

            run_programmer_mode(
                text_flag=True,
                voice_flag=False,
                speak_fn=None,
            )

        assert exc_info.value.code == 1
