"""
test_methodology_routing.py -- Story 2.2: methodology routing tests.

Covers: YAML loading, trigger detection, conversational input collection,
prompt assembly, dispatch call verification (mock engine), artifact existence check.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from programmer.methodology import (
    MethodologyCancelled,
    MethodologyDef,
    MethodologyInputs,
    assemble_methodology_prompt,
    check_artifacts,
    collect_methodology_inputs,
    detect_methodology,
    load_methodology_defs,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _defs(*names: str) -> list[MethodologyDef]:
    """Build minimal MethodologyDef objects for testing -- no file I/O."""
    registry = {
        "bmad": MethodologyDef(
            name="bmad",
            display_name="BMAD",
            triggers=["/methodology bmad", "start bmad", "vamos fazer um bmad", "bmad run"],
            questions=["Project name?", "What to build?", "Session goals?"],
        ),
        "speckit": MethodologyDef(
            name="speckit",
            display_name="SpecKit",
            triggers=["/methodology speckit", "start speckit", "speckit run"],
            questions=["Project name?", "Describe what to specify.", "Any constraints?"],
        ),
    }
    return [registry[n] for n in names if n in registry]


# ---------------------------------------------------------------------------
# load_methodology_defs -- YAML loading
# ---------------------------------------------------------------------------


class TestLoadMethodologyDefs:
    def test_bundled_defs_loaded(self) -> None:
        defs = load_methodology_defs()
        names = [d.name for d in defs]
        assert "bmad" in names
        assert "speckit" in names

    def test_bundled_def_has_triggers(self) -> None:
        defs = load_methodology_defs()
        bmad = next(d for d in defs if d.name == "bmad")
        assert len(bmad.triggers) > 0

    def test_bundled_def_has_questions(self) -> None:
        defs = load_methodology_defs()
        bmad = next(d for d in defs if d.name == "bmad")
        assert len(bmad.questions) > 0

    def test_project_override_wins(self, tmp_path: Path) -> None:
        project_dir = tmp_path / ".yana" / "methodologies"
        project_dir.mkdir(parents=True)
        (project_dir / "bmad.yaml").write_text(
            "name: bmad\ndisplay_name: CUSTOM_BMAD\ntriggers: []\nquestions: []\n",
            encoding="utf-8",
        )
        defs = load_methodology_defs(repo_root=tmp_path)
        bmad = next(d for d in defs if d.name == "bmad")
        assert bmad.display_name == "CUSTOM_BMAD"

    def test_project_adds_new_methodology(self, tmp_path: Path) -> None:
        project_dir = tmp_path / ".yana" / "methodologies"
        project_dir.mkdir(parents=True)
        (project_dir / "openspec.yaml").write_text(
            "name: openspec\ndisplay_name: OpenSpec\ntriggers:\n  - start openspec\nquestions:\n  - What to spec?\n",
            encoding="utf-8",
        )
        defs = load_methodology_defs(repo_root=tmp_path)
        names = [d.name for d in defs]
        assert "openspec" in names
        assert "bmad" in names

    def test_no_repo_root_loads_bundled_only(self) -> None:
        defs = load_methodology_defs(repo_root=None)
        assert len(defs) >= 2

    def test_malformed_yaml_skipped_gracefully(self, tmp_path: Path) -> None:
        project_dir = tmp_path / ".yana" / "methodologies"
        project_dir.mkdir(parents=True)
        (project_dir / "bad.yaml").write_text("}{{{not yaml", encoding="utf-8")
        defs = load_methodology_defs(repo_root=tmp_path)
        assert "bad" not in [d.name for d in defs]

    def test_triggers_stored_lowercase(self) -> None:
        defs = load_methodology_defs()
        for defn in defs:
            for trigger in defn.triggers:
                assert trigger == trigger.lower()


# ---------------------------------------------------------------------------
# detect_methodology
# ---------------------------------------------------------------------------


class TestDetectMethodology:
    def test_bmad_slash_command(self) -> None:
        assert detect_methodology("/methodology bmad", _defs("bmad")) == "bmad"

    def test_speckit_slash_command(self) -> None:
        assert detect_methodology("/methodology speckit", _defs("speckit")) == "speckit"

    def test_portuguese_trigger(self) -> None:
        assert detect_methodology("vamos fazer um bmad", _defs("bmad")) == "bmad"

    def test_case_insensitive(self) -> None:
        assert detect_methodology("START BMAD", _defs("bmad")) == "bmad"
        assert detect_methodology("/METHODOLOGY SPECKIT", _defs("speckit")) == "speckit"

    def test_no_match_returns_none(self) -> None:
        assert detect_methodology("add a function to utils.py", _defs("bmad")) is None

    def test_partial_phrase_not_triggered(self) -> None:
        assert detect_methodology("do bmad stuff later", _defs("bmad")) is None

    def test_empty_string(self) -> None:
        assert detect_methodology("", _defs("bmad")) is None

    def test_whitespace_stripped(self) -> None:
        assert detect_methodology("  /methodology bmad  ", _defs("bmad")) == "bmad"

    def test_empty_defs_returns_none(self) -> None:
        assert detect_methodology("/methodology bmad", []) is None

    def test_project_defined_methodology_detected(self, tmp_path: Path) -> None:
        project_dir = tmp_path / ".yana" / "methodologies"
        project_dir.mkdir(parents=True)
        (project_dir / "openspec.yaml").write_text(
            "name: openspec\ndisplay_name: OpenSpec\ntriggers:\n  - start openspec\nquestions: []\n",
            encoding="utf-8",
        )
        defs = load_methodology_defs(repo_root=tmp_path)
        assert detect_methodology("start openspec", defs) == "openspec"


# ---------------------------------------------------------------------------
# collect_methodology_inputs
# ---------------------------------------------------------------------------


class TestCollectMethodologyInputs:
    def test_collects_all_answers(self) -> None:
        defs = _defs("bmad")
        n = len(defs[0].questions)
        with patch("builtins.input", side_effect=["A"] * n):
            result = collect_methodology_inputs("bmad", defs)
        assert isinstance(result, MethodologyInputs)
        assert len(result.answers) == n

    def test_answers_keyed_by_question(self) -> None:
        defs = _defs("bmad")
        with patch("builtins.input", side_effect=["A", "B", "C"]):
            result = collect_methodology_inputs("bmad", defs)
        assert isinstance(result, MethodologyInputs)
        for q in defs[0].questions:
            assert q in result.answers

    def test_cancel_on_empty_answer(self) -> None:
        with patch("builtins.input", return_value=""):
            result = collect_methodology_inputs("bmad", _defs("bmad"))
        assert isinstance(result, MethodologyCancelled)

    def test_cancel_command(self) -> None:
        with patch("builtins.input", return_value="/cancel"):
            result = collect_methodology_inputs("bmad", _defs("bmad"))
        assert isinstance(result, MethodologyCancelled)

    def test_cancela_command(self) -> None:
        with patch("builtins.input", return_value="cancela"):
            result = collect_methodology_inputs("bmad", _defs("bmad"))
        assert isinstance(result, MethodologyCancelled)

    def test_cancel_case_insensitive(self) -> None:
        with patch("builtins.input", return_value="CANCEL"):
            result = collect_methodology_inputs("bmad", _defs("bmad"))
        assert isinstance(result, MethodologyCancelled)

    def test_speak_fn_called_per_question(self) -> None:
        defs = _defs("bmad")
        speak_fn = MagicMock()
        with patch("builtins.input", side_effect=["A", "B", "C"]):
            collect_methodology_inputs("bmad", defs, speak_fn=speak_fn)
        assert speak_fn.call_count == len(defs[0].questions)

    def test_listen_fn_used_instead_of_input(self) -> None:
        defs = _defs("bmad")
        listen_fn = MagicMock(return_value="some answer")
        result = collect_methodology_inputs("bmad", defs, listen_fn=listen_fn)
        assert isinstance(result, MethodologyInputs)
        assert listen_fn.call_count == len(defs[0].questions)

    def test_unknown_methodology_returns_empty_inputs(self) -> None:
        result = collect_methodology_inputs("unknown", _defs("bmad"))
        assert isinstance(result, MethodologyInputs)
        assert len(result.answers) == 0

    def test_eof_cancels(self) -> None:
        with patch("builtins.input", side_effect=EOFError):
            result = collect_methodology_inputs("bmad", _defs("bmad"))
        assert isinstance(result, MethodologyCancelled)

    def test_result_carries_display_name(self) -> None:
        defs = _defs("bmad")
        with patch("builtins.input", side_effect=["A", "B", "C"]):
            result = collect_methodology_inputs("bmad", defs)
        assert isinstance(result, MethodologyInputs)
        assert result.display_name == "BMAD"


# ---------------------------------------------------------------------------
# assemble_methodology_prompt
# ---------------------------------------------------------------------------


class TestAssembleMethodologyPrompt:
    def test_contains_display_name(self) -> None:
        inputs = MethodologyInputs(methodology="bmad", display_name="BMAD", answers={})
        assert "BMAD" in assemble_methodology_prompt(inputs)

    def test_run_instruction_present(self) -> None:
        inputs = MethodologyInputs(methodology="bmad", display_name="BMAD", answers={})
        assert "Run" in assemble_methodology_prompt(inputs)

    def test_answers_in_prompt(self) -> None:
        inputs = MethodologyInputs(
            methodology="bmad",
            display_name="BMAD",
            answers={"What to build?": "REST API"},
        )
        assert "REST API" in assemble_methodology_prompt(inputs)

    def test_inputs_section_present(self) -> None:
        inputs = MethodologyInputs(
            methodology="bmad",
            display_name="BMAD",
            answers={"Q1": "A1", "Q2": "A2"},
        )
        prompt = assemble_methodology_prompt(inputs)
        assert "## Inputs" in prompt
        assert "A1" in prompt
        assert "A2" in prompt

    def test_custom_display_name_used(self) -> None:
        inputs = MethodologyInputs(
            methodology="openspec",
            display_name="OpenSpec",
            answers={"What?": "An API"},
        )
        assert "OpenSpec" in assemble_methodology_prompt(inputs)


# ---------------------------------------------------------------------------
# check_artifacts
# ---------------------------------------------------------------------------


class TestCheckArtifacts:
    def test_empty_dir_returns_false(self, tmp_path: Path) -> None:
        assert not check_artifacts(tmp_path)

    def test_file_present_returns_true(self, tmp_path: Path) -> None:
        (tmp_path / "SPEC.md").write_text("# Spec", encoding="utf-8")
        assert check_artifacts(tmp_path)

    def test_nonexistent_path_returns_false(self, tmp_path: Path) -> None:
        assert not check_artifacts(tmp_path / "nonexistent")

    def test_nested_file_counts(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "story.md").write_text("story", encoding="utf-8")
        assert check_artifacts(tmp_path)

    def test_directory_only_returns_false(self, tmp_path: Path) -> None:
        (tmp_path / "empty_dir").mkdir()
        assert not check_artifacts(tmp_path)


# ---------------------------------------------------------------------------
# Dispatch integration
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
            display_name="BMAD",
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

    def test_methodology_module_has_no_subprocess(self) -> None:
        import inspect

        from programmer import methodology

        src = inspect.getsource(methodology)
        assert "subprocess" not in src
        assert "os.system" not in src

    def test_methodology_module_has_no_clarification_gate(self) -> None:
        import inspect

        from programmer import methodology

        src = inspect.getsource(methodology)
        assert "run_clarification_gate" not in src
        assert "from programmer.clarification" not in src
