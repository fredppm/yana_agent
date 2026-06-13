"""
test_methodology_routing.py -- Story 2.2: methodology routing tests.

Covers: YAML loading, trigger detection, dispatch verification, artifact check.
YANA collects no methodology-specific inputs -- that is the engine's job.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from programmer.methodology import (
    MethodologyDef,
    check_artifacts,
    detect_methodology,
    load_methodology_defs,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_def(name: str, triggers: list[str], prompt: str = "") -> MethodologyDef:
    return MethodologyDef(
        name=name,
        display_name=name.upper(),
        triggers=[t.lower() for t in triggers],
        prompt=prompt or f"Run {name.upper()} in the worktree.",
    )


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

    def test_bundled_def_has_prompt(self) -> None:
        defs = load_methodology_defs()
        bmad = next(d for d in defs if d.name == "bmad")
        assert bmad.prompt

    def test_project_override_wins(self, tmp_path: Path) -> None:
        project_dir = tmp_path / ".yana" / "methodologies"
        project_dir.mkdir(parents=True)
        (project_dir / "bmad.yaml").write_text(
            "name: bmad\ndisplay_name: MY_BMAD\ntriggers: []\nprompt: custom\n",
            encoding="utf-8",
        )
        defs = load_methodology_defs(repo_root=tmp_path)
        bmad = next(d for d in defs if d.name == "bmad")
        assert bmad.display_name == "MY_BMAD"
        assert bmad.prompt == "custom"

    def test_project_adds_new_methodology(self, tmp_path: Path) -> None:
        project_dir = tmp_path / ".yana" / "methodologies"
        project_dir.mkdir(parents=True)
        (project_dir / "openspec.yaml").write_text(
            "name: openspec\ndisplay_name: OpenSpec\ntriggers:\n  - start openspec\nprompt: Run OpenSpec.\n",
            encoding="utf-8",
        )
        defs = load_methodology_defs(repo_root=tmp_path)
        names = [d.name for d in defs]
        assert "openspec" in names
        assert "bmad" in names  # bundled still present

    def test_no_repo_root_loads_bundled_only(self) -> None:
        assert len(load_methodology_defs(repo_root=None)) >= 2

    def test_malformed_yaml_skipped(self, tmp_path: Path) -> None:
        project_dir = tmp_path / ".yana" / "methodologies"
        project_dir.mkdir(parents=True)
        (project_dir / "bad.yaml").write_text("}{{{not yaml", encoding="utf-8")
        defs = load_methodology_defs(repo_root=tmp_path)
        assert "bad" not in [d.name for d in defs]

    def test_triggers_stored_lowercase(self) -> None:
        for defn in load_methodology_defs():
            for trigger in defn.triggers:
                assert trigger == trigger.lower()

    def test_no_questions_field(self) -> None:
        """Methodology defs have no questions -- engine owns input collection."""
        for defn in load_methodology_defs():
            assert not hasattr(defn, "questions")


# ---------------------------------------------------------------------------
# detect_methodology
# ---------------------------------------------------------------------------


class TestDetectMethodology:
    def test_bmad_slash_command(self) -> None:
        defs = [_make_def("bmad", ["/methodology bmad", "start bmad"])]
        result = detect_methodology("/methodology bmad", defs)
        assert result is not None
        assert result.name == "bmad"

    def test_returns_def_not_just_name(self) -> None:
        defs = [_make_def("bmad", ["start bmad"], prompt="Run BMAD.")]
        result = detect_methodology("start bmad", defs)
        assert isinstance(result, MethodologyDef)
        assert result.prompt == "Run BMAD."

    def test_case_insensitive(self) -> None:
        defs = [_make_def("bmad", ["start bmad"])]
        assert detect_methodology("START BMAD", defs) is not None

    def test_whitespace_stripped(self) -> None:
        defs = [_make_def("bmad", ["/methodology bmad"])]
        assert detect_methodology("  /methodology bmad  ", defs) is not None

    def test_no_match_returns_none(self) -> None:
        defs = [_make_def("bmad", ["start bmad"])]
        assert detect_methodology("add a function", defs) is None

    def test_partial_phrase_not_triggered(self) -> None:
        defs = [_make_def("bmad", ["start bmad"])]
        assert detect_methodology("do bmad stuff later", defs) is None

    def test_empty_string_returns_none(self) -> None:
        defs = [_make_def("bmad", ["start bmad"])]
        assert detect_methodology("", defs) is None

    def test_empty_defs_returns_none(self) -> None:
        assert detect_methodology("start bmad", []) is None

    def test_project_yaml_methodology_detected(self, tmp_path: Path) -> None:
        project_dir = tmp_path / ".yana" / "methodologies"
        project_dir.mkdir(parents=True)
        (project_dir / "openspec.yaml").write_text(
            "name: openspec\ndisplay_name: OpenSpec\ntriggers:\n  - start openspec\nprompt: Run OpenSpec.\n",
            encoding="utf-8",
        )
        defs = load_methodology_defs(repo_root=tmp_path)
        result = detect_methodology("start openspec", defs)
        assert result is not None
        assert result.name == "openspec"


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
# Dispatch integration -- engine receives the prompt from the YAML
# ---------------------------------------------------------------------------


class TestDispatchIntegration:
    def test_yaml_prompt_sent_to_engine(self, tmp_path: Path) -> None:
        from programmer.dispatcher import DispatchResult, dispatch_request
        from programmer.engine import CodingEngine, CompletionSignal, EngineRequest, EngineSession
        from programmer.mode import SanctumContext

        class _S(EngineSession):
            pass

        class _E(CodingEngine):
            def __init__(self) -> None:
                self.dispatched: list[EngineRequest] = []

            def dispatch(self, r: EngineRequest) -> EngineSession:
                self.dispatched.append(r)
                return _S()

            def send(self, s: EngineSession, m: str) -> None:
                pass

            def events(self, s: EngineSession):  # type: ignore[override]
                yield CompletionSignal(summary="done")

        (tmp_path / "BOND.md").write_text("Fred is a dev", encoding="utf-8")
        (tmp_path / "MEMORY.md").write_text("", encoding="utf-8")
        (tmp_path / "PERSONA.md").write_text("", encoding="utf-8")
        sanctum = SanctumContext.load(tmp_path)

        defn = _make_def("bmad", ["start bmad"], prompt="Run BMAD in the worktree.")
        engine = _E()

        with patch("programmer.dispatcher.detect_repo_root", return_value=tmp_path):
            with patch("programmer.worktree.create_worktree", return_value=tmp_path / "wt"):
                result = dispatch_request(
                    enriched_prompt=defn.prompt,
                    sanctum=sanctum,
                    session_id="meth-001",
                    engine=engine,
                    repo_root=tmp_path,
                )

        assert isinstance(result, DispatchResult)
        assert engine.dispatched[0].prompt == "Run BMAD in the worktree."

    def test_methodology_module_has_no_input_collection(self) -> None:
        """YANA never collects methodology-specific inputs (Design Principle 1)."""
        import inspect

        from programmer import methodology

        src = inspect.getsource(methodology)
        assert "collect_methodology_inputs" not in src
        assert "questions" not in src

    def test_methodology_module_has_no_subprocess(self) -> None:
        import inspect

        from programmer import methodology

        src = inspect.getsource(methodology)
        assert "subprocess" not in src
        assert "os.system" not in src
