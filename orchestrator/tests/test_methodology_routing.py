"""
test_methodology_routing.py — Story 2.2: methodology routing tests.

Covers: trigger detection, conversational input collection, prompt assembly,
dispatch call verification (mock engine), artifact existence check.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from programmer.methodology import (
    METHODOLOGY_QUESTIONS,
    MethodologyCancelled,
    MethodologyInputs,
    assemble_methodology_prompt,
    check_artifacts,
    collect_methodology_inputs,
    detect_methodology,
)

# ---------------------------------------------------------------------------
# detect_methodology
# ---------------------------------------------------------------------------


class TestDetectMethodology:
    def test_bmad_slash_command(self) -> None:
        assert detect_methodology("/methodology bmad") == "bmad"

    def test_speckit_slash_command(self) -> None:
        assert detect_methodology("/methodology speckit") == "speckit"

    def test_bmad_portuguese_trigger(self) -> None:
        assert detect_methodology("vamos fazer um bmad") == "bmad"

    def test_case_insensitive(self) -> None:
        assert detect_methodology("START BMAD") == "bmad"
        assert detect_methodology("/METHODOLOGY SPECKIT") == "speckit"

    def test_not_a_methodology_trigger(self) -> None:
        assert detect_methodology("add a new function to utils.py") is None

    def test_partial_phrase_not_triggered(self) -> None:
        # "let's do bmad later" is not an exact trigger phrase
        assert detect_methodology("let's do bmad later") is None

    def test_empty_string(self) -> None:
        assert detect_methodology("") is None

    def test_leading_trailing_whitespace_stripped(self) -> None:
        assert detect_methodology("  /methodology bmad  ") == "bmad"

    def test_start_bmad_variant(self) -> None:
        assert detect_methodology("start bmad") == "bmad"

    def test_speckit_run_variant(self) -> None:
        assert detect_methodology("speckit run") == "speckit"


# ---------------------------------------------------------------------------
# collect_methodology_inputs
# ---------------------------------------------------------------------------


class TestCollectMethodologyInputs:
    def test_collects_all_answers(self) -> None:
        answers = iter(["MyProject", "Build a REST API", "Prototype only"])
        with patch("builtins.input", side_effect=answers):
            result = collect_methodology_inputs("bmad")
        assert isinstance(result, MethodologyInputs)
        assert result.methodology == "bmad"
        assert len(result.answers) == len(METHODOLOGY_QUESTIONS["bmad"])

    def test_answers_keyed_by_question(self) -> None:
        answers = iter(["Proj", "Build X", "Goal Y"])
        with patch("builtins.input", side_effect=answers):
            result = collect_methodology_inputs("bmad")
        assert isinstance(result, MethodologyInputs)
        # Every question should appear as a key
        for q in METHODOLOGY_QUESTIONS["bmad"]:
            assert q in result.answers

    def test_cancel_on_empty_answer(self) -> None:
        with patch("builtins.input", return_value=""):
            result = collect_methodology_inputs("bmad")
        assert isinstance(result, MethodologyCancelled)

    def test_cancel_command(self) -> None:
        with patch("builtins.input", return_value="/cancel"):
            result = collect_methodology_inputs("bmad")
        assert isinstance(result, MethodologyCancelled)

    def test_cancela_command(self) -> None:
        with patch("builtins.input", return_value="cancela"):
            result = collect_methodology_inputs("bmad")
        assert isinstance(result, MethodologyCancelled)

    def test_cancel_command_case_insensitive(self) -> None:
        with patch("builtins.input", return_value="CANCEL"):
            result = collect_methodology_inputs("bmad")
        assert isinstance(result, MethodologyCancelled)

    def test_speckit_questions_asked(self) -> None:
        answers = iter(["SpecProject", "API spec", "No auth"])
        with patch("builtins.input", side_effect=answers):
            result = collect_methodology_inputs("speckit")
        assert isinstance(result, MethodologyInputs)
        assert result.methodology == "speckit"
        assert len(result.answers) == len(METHODOLOGY_QUESTIONS["speckit"])

    def test_speak_fn_called_for_each_question(self) -> None:
        speak_fn = MagicMock()
        answers = iter(["A", "B", "C"])
        with patch("builtins.input", side_effect=answers):
            collect_methodology_inputs("bmad", speak_fn=speak_fn)
        assert speak_fn.call_count == len(METHODOLOGY_QUESTIONS["bmad"])

    def test_listen_fn_used_instead_of_input(self) -> None:
        listen_fn = MagicMock(return_value="some answer")
        result = collect_methodology_inputs("bmad", listen_fn=listen_fn)
        assert isinstance(result, MethodologyInputs)
        assert listen_fn.call_count == len(METHODOLOGY_QUESTIONS["bmad"])

    def test_unknown_methodology_returns_empty_inputs(self) -> None:
        # No questions defined — returns immediately with empty answers
        result = collect_methodology_inputs("unknown_method")
        assert isinstance(result, MethodologyInputs)
        assert result.methodology == "unknown_method"
        assert len(result.answers) == 0

    def test_eof_cancels(self) -> None:
        with patch("builtins.input", side_effect=EOFError):
            result = collect_methodology_inputs("bmad")
        assert isinstance(result, MethodologyCancelled)


# ---------------------------------------------------------------------------
# assemble_methodology_prompt
# ---------------------------------------------------------------------------


class TestAssembleMethodologyPrompt:
    def test_contains_methodology_name_uppercased(self) -> None:
        inputs = MethodologyInputs(methodology="bmad", answers={})
        prompt = assemble_methodology_prompt(inputs)
        assert "BMAD" in prompt

    def test_speckit_uppercased(self) -> None:
        inputs = MethodologyInputs(methodology="speckit", answers={})
        prompt = assemble_methodology_prompt(inputs)
        assert "SPECKIT" in prompt

    def test_contains_run_instruction(self) -> None:
        inputs = MethodologyInputs(methodology="bmad", answers={})
        prompt = assemble_methodology_prompt(inputs)
        assert "Run" in prompt

    def test_contains_answers(self) -> None:
        inputs = MethodologyInputs(
            methodology="bmad",
            answers={"What would you like to build?": "REST API"},
        )
        prompt = assemble_methodology_prompt(inputs)
        assert "REST API" in prompt

    def test_inputs_section_present(self) -> None:
        inputs = MethodologyInputs(
            methodology="bmad",
            answers={"Q1": "A1", "Q2": "A2"},
        )
        prompt = assemble_methodology_prompt(inputs)
        assert "## Inputs" in prompt
        assert "A1" in prompt
        assert "A2" in prompt

    def test_all_questions_included(self) -> None:
        answers = {"Q1": "answer1", "Q2": "answer2", "Q3": "answer3"}
        inputs = MethodologyInputs(methodology="bmad", answers=answers)
        prompt = assemble_methodology_prompt(inputs)
        for answer in answers.values():
            assert answer in prompt

    def test_empty_answers_still_valid_prompt(self) -> None:
        inputs = MethodologyInputs(methodology="speckit", answers={})
        prompt = assemble_methodology_prompt(inputs)
        assert "SPECKIT" in prompt
        assert "## Inputs" in prompt


# ---------------------------------------------------------------------------
# check_artifacts
# ---------------------------------------------------------------------------


class TestCheckArtifacts:
    def test_empty_directory_returns_false(self, tmp_path: Path) -> None:
        assert not check_artifacts(tmp_path)

    def test_file_in_worktree_returns_true(self, tmp_path: Path) -> None:
        (tmp_path / "SPEC.md").write_text("# Spec", encoding="utf-8")
        assert check_artifacts(tmp_path)

    def test_nonexistent_path_returns_false(self, tmp_path: Path) -> None:
        assert not check_artifacts(tmp_path / "nonexistent")

    def test_nested_file_counts(self, tmp_path: Path) -> None:
        subdir = tmp_path / "specs"
        subdir.mkdir()
        (subdir / "story.md").write_text("story", encoding="utf-8")
        assert check_artifacts(tmp_path)

    def test_multiple_files_returns_true(self, tmp_path: Path) -> None:
        for name in ("SPEC.md", "PRD.md", "stories.md"):
            (tmp_path / name).write_text("content", encoding="utf-8")
        assert check_artifacts(tmp_path)

    def test_directory_only_no_files_returns_false(self, tmp_path: Path) -> None:
        (tmp_path / "empty_subdir").mkdir()
        assert not check_artifacts(tmp_path)


# ---------------------------------------------------------------------------
# Dispatch integration — mock engine, verify dispatch called with methodology prompt
# ---------------------------------------------------------------------------


class TestDispatchIntegration:
    def test_methodology_prompt_dispatched_to_engine(self, tmp_path: Path) -> None:
        from programmer.dispatcher import DispatchResult, dispatch_request
        from programmer.engine import CodingEngine, CompletionSignal, EngineRequest, EngineSession
        from programmer.mode import SanctumContext

        class _FakeSession(EngineSession):
            pass

        class _FakeEngine(CodingEngine):
            def __init__(self) -> None:
                self.dispatched: list[EngineRequest] = []

            def dispatch(self, request: EngineRequest) -> EngineSession:
                self.dispatched.append(request)
                return _FakeSession()

            def send(self, session: EngineSession, message: str) -> None:
                pass

            def events(self, session: EngineSession):  # type: ignore[override]
                yield CompletionSignal(summary="done")

        (tmp_path / "BOND.md").write_text("Fred is a dev", encoding="utf-8")
        (tmp_path / "MEMORY.md").write_text("", encoding="utf-8")
        (tmp_path / "PERSONA.md").write_text("", encoding="utf-8")
        sanctum = SanctumContext.load(tmp_path)

        inputs = MethodologyInputs(
            methodology="bmad",
            answers={"What to build?": "REST API"},
        )
        prompt = assemble_methodology_prompt(inputs)
        engine = _FakeEngine()

        with patch("programmer.dispatcher.detect_repo_root", return_value=tmp_path):
            with patch("programmer.worktree.create_worktree", return_value=tmp_path / "wt"):
                result = dispatch_request(
                    enriched_prompt=prompt,
                    sanctum=sanctum,
                    session_id="meth-001",
                    engine=engine,
                    repo_root=tmp_path,
                )

        assert isinstance(result, DispatchResult)
        assert len(engine.dispatched) == 1
        assert "BMAD" in engine.dispatched[0].prompt
        assert "REST API" in engine.dispatched[0].prompt

    def test_methodology_does_not_use_clarification_gate(self) -> None:
        """Methodology module must not import or call clarification gate."""
        import inspect

        from programmer import methodology

        src = inspect.getsource(methodology)
        # Must not import or call the clarification gate
        assert "run_clarification_gate" not in src
        assert "from programmer.clarification" not in src

    def test_methodology_does_not_call_bmad_directly(self) -> None:
        """YANA never calls BMAD scripts — the engine does (AC-2.2.6)."""
        import inspect

        from programmer import methodology

        src = inspect.getsource(methodology)
        # No subprocess or shell execution in methodology module
        assert "subprocess" not in src
        assert "os.system" not in src
        assert "os.popen" not in src
