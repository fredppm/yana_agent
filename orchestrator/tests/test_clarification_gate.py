"""
test_clarification_gate.py — Story 1.2: clarification gate tests.

No LLM calls — detect_gaps is mocked throughout.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from programmer.clarification import (
    Cancelled,
    Clarified,
    _assemble_enriched_prompt,
    _is_skip,
    _parse_questions,
    run_clarification_gate,
)

# ---------------------------------------------------------------------------
# _parse_questions
# ---------------------------------------------------------------------------


class TestParseQuestions:
    def test_parses_json_array(self) -> None:
        result = _parse_questions('["Which file?", "Should it be async?"]')
        assert result == ["Which file?", "Should it be async?"]

    def test_empty_array(self) -> None:
        assert _parse_questions("[]") == []

    def test_strips_markdown_fences(self) -> None:
        result = _parse_questions('```json\n["Which file?"]\n```')
        assert result == ["Which file?"]

    def test_strips_plain_code_fences(self) -> None:
        result = _parse_questions('```\n["Which file?"]\n```')
        assert result == ["Which file?"]

    def test_invalid_json_returns_empty(self) -> None:
        assert _parse_questions("not json at all") == []

    def test_non_array_json_returns_empty(self) -> None:
        assert _parse_questions('{"key": "value"}') == []

    def test_filters_empty_strings(self) -> None:
        result = _parse_questions('["Which file?", "", "   "]')
        assert result == ["Which file?"]

    def test_converts_non_strings_to_str(self) -> None:
        result = _parse_questions("[42, true]")
        assert result == ["42", "True"]


# ---------------------------------------------------------------------------
# _is_skip
# ---------------------------------------------------------------------------


class TestIsSkip:
    def test_empty_string_is_skip(self) -> None:
        assert _is_skip("") is True

    def test_whitespace_only_is_skip(self) -> None:
        assert _is_skip("   ") is True

    def test_slash_skip_is_skip(self) -> None:
        assert _is_skip("/skip") is True

    def test_word_skip_is_skip(self) -> None:
        assert _is_skip("skip") is True

    def test_case_insensitive(self) -> None:
        assert _is_skip("SKIP") is True
        assert _is_skip("/SKIP") is True

    def test_real_answer_is_not_skip(self) -> None:
        assert _is_skip("utils.py") is False
        assert _is_skip("yes, make it async") is False
        assert _is_skip("the auth module") is False


# ---------------------------------------------------------------------------
# _assemble_enriched_prompt
# ---------------------------------------------------------------------------


class TestAssembleEnrichedPrompt:
    def test_no_answers_returns_original(self) -> None:
        result = _assemble_enriched_prompt("add hello()", [])
        assert result == "add hello()"

    def test_answers_appended(self) -> None:
        result = _assemble_enriched_prompt(
            "add hello()",
            [("Which file?", "utils.py"), ("Async?", "no")],
        )
        assert "add hello()" in result
        assert "Which file?" in result
        assert "utils.py" in result
        assert "Async?" in result
        assert "no" in result

    def test_clarifications_section_header(self) -> None:
        result = _assemble_enriched_prompt(
            "add hello()",
            [("Which file?", "utils.py")],
        )
        assert "Clarifications" in result

    def test_qa_format(self) -> None:
        result = _assemble_enriched_prompt(
            "add hello()",
            [("Which file?", "utils.py")],
        )
        assert "Q: Which file?" in result
        assert "A: utils.py" in result


# ---------------------------------------------------------------------------
# run_clarification_gate — gap detection mocked
# ---------------------------------------------------------------------------


class TestRunClarificationGate:
    def test_no_gaps_returns_clarified_immediately(self) -> None:
        with patch("programmer.clarification.detect_gaps", return_value=[]):
            result = run_clarification_gate(
                request="add hello() to utils.py",
                context="",
            )
        assert isinstance(result, Clarified)
        assert result.enriched_prompt == "add hello() to utils.py"

    def test_gap_answered_returns_clarified(self) -> None:
        with patch(
            "programmer.clarification.detect_gaps",
            return_value=["Which file should it go in?"],
        ):
            with patch("builtins.input", return_value="utils.py"):
                result = run_clarification_gate(
                    request="add hello()",
                    context="",
                )

        assert isinstance(result, Clarified)
        assert "add hello()" in result.enriched_prompt
        assert "Which file" in result.enriched_prompt
        assert "utils.py" in result.enriched_prompt

    def test_skip_returns_cancelled(self) -> None:
        with patch(
            "programmer.clarification.detect_gaps",
            return_value=["Which file?"],
        ):
            with patch("builtins.input", return_value="/skip"):
                result = run_clarification_gate(
                    request="add hello()",
                    context="",
                )

        assert isinstance(result, Cancelled)

    def test_empty_answer_returns_cancelled(self) -> None:
        with patch(
            "programmer.clarification.detect_gaps",
            return_value=["Which file?"],
        ):
            with patch("builtins.input", return_value=""):
                result = run_clarification_gate(
                    request="add hello()",
                    context="",
                )

        assert isinstance(result, Cancelled)

    def test_sequential_questions_all_answered(self) -> None:
        questions = ["Which file?", "Should it be async?"]
        answers_iter = iter(["utils.py", "no"])

        with patch("programmer.clarification.detect_gaps", return_value=questions):
            with patch("builtins.input", side_effect=answers_iter):
                result = run_clarification_gate(
                    request="add hello()",
                    context="",
                )

        assert isinstance(result, Clarified)
        assert "utils.py" in result.enriched_prompt
        assert "no" in result.enriched_prompt
        assert "Which file?" in result.enriched_prompt
        assert "async?" in result.enriched_prompt

    def test_first_question_skipped_stops_immediately(self) -> None:
        questions = ["Which file?", "Should it be async?"]
        answers_iter = iter(["/skip", "no"])  # second answer should never be reached

        with patch("programmer.clarification.detect_gaps", return_value=questions):
            with patch("builtins.input", side_effect=answers_iter):
                result = run_clarification_gate(
                    request="add hello()",
                    context="",
                )

        assert isinstance(result, Cancelled)

    def test_second_question_skipped_stops(self) -> None:
        questions = ["Which file?", "Should it be async?"]
        answers_iter = iter(["utils.py", ""])  # second answer empty → cancelled

        with patch("programmer.clarification.detect_gaps", return_value=questions):
            with patch("builtins.input", side_effect=answers_iter):
                result = run_clarification_gate(
                    request="add hello()",
                    context="",
                )

        assert isinstance(result, Cancelled)

    def test_no_gap_does_not_call_input(self) -> None:
        """When no gaps, user is never asked anything."""
        with patch("programmer.clarification.detect_gaps", return_value=[]):
            with patch("builtins.input") as mock_input:
                run_clarification_gate(request="add hello() to utils.py", context="")
                mock_input.assert_not_called()

    def test_speak_fn_called_for_each_question(self) -> None:
        speak = MagicMock()

        with patch(
            "programmer.clarification.detect_gaps",
            return_value=["Which file?", "Async?"],
        ):
            with patch("builtins.input", return_value="utils.py"):
                run_clarification_gate(
                    request="add hello()",
                    context="",
                    speak_fn=speak,
                )

        assert speak.call_count == 2

    def test_listen_fn_used_instead_of_input(self) -> None:
        listen = MagicMock(return_value="utils.py")

        with patch(
            "programmer.clarification.detect_gaps",
            return_value=["Which file?"],
        ):
            result = run_clarification_gate(
                request="add hello()",
                context="",
                listen_fn=listen,
            )

        listen.assert_called_once()
        assert isinstance(result, Clarified)


# ---------------------------------------------------------------------------
# detect_gaps — LLM fallback on error
# ---------------------------------------------------------------------------


class TestDetectGapsFallback:
    def test_llm_failure_returns_empty_list(self) -> None:
        """LLM error must not block the workflow."""
        import providers as prov

        with patch.object(prov, "call_llm", side_effect=RuntimeError("LLM down")):
            from programmer.clarification import detect_gaps

            result = detect_gaps("add hello()", context="", config={"engines": {}, "llm": {}})
        assert result == []
