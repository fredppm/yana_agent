"""
test_methodology_routing.py -- Story 2.2: methodology routing tests.

Methodology logic lives in mode.py (private helpers). Tests cover YAML
loading, trigger detection, and artifact checking.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from programmer.mode import (
    _load_methodology_defs,
    _match_methodology,
    _MethodologyDef,
    _worktree_has_files,
)


def _make(name: str, triggers: list[str], prompt: str = "") -> _MethodologyDef:
    return _MethodologyDef(
        name=name,
        display_name=name.upper(),
        triggers=[t.lower() for t in triggers],
        prompt=prompt or f"Run {name.upper()}.",
    )


# ---------------------------------------------------------------------------
# _load_methodology_defs
# ---------------------------------------------------------------------------


class TestLoadMethodologyDefs:
    def test_bundled_defs_loaded(self) -> None:
        names = [d.name for d in _load_methodology_defs()]
        assert "bmad" in names
        assert "speckit" in names

    def test_bundled_def_has_triggers(self) -> None:
        bmad = next(d for d in _load_methodology_defs() if d.name == "bmad")
        assert len(bmad.triggers) > 0

    def test_bundled_def_has_prompt(self) -> None:
        bmad = next(d for d in _load_methodology_defs() if d.name == "bmad")
        assert bmad.prompt

    def test_project_override_wins(self, tmp_path: Path) -> None:
        proj = tmp_path / ".yana" / "methodologies"
        proj.mkdir(parents=True)
        (proj / "bmad.yaml").write_text(
            "name: bmad\ndisplay_name: MY_BMAD\ntriggers: []\nprompt: custom\n",
            encoding="utf-8",
        )
        bmad = next(d for d in _load_methodology_defs(tmp_path) if d.name == "bmad")
        assert bmad.display_name == "MY_BMAD"

    def test_project_adds_new_methodology(self, tmp_path: Path) -> None:
        proj = tmp_path / ".yana" / "methodologies"
        proj.mkdir(parents=True)
        (proj / "openspec.yaml").write_text(
            "name: openspec\ndisplay_name: OpenSpec\ntriggers:\n  - start openspec\nprompt: Run it.\n",
            encoding="utf-8",
        )
        names = [d.name for d in _load_methodology_defs(tmp_path)]
        assert "openspec" in names
        assert "bmad" in names

    def test_malformed_yaml_skipped(self, tmp_path: Path) -> None:
        proj = tmp_path / ".yana" / "methodologies"
        proj.mkdir(parents=True)
        (proj / "bad.yaml").write_text("}{{{", encoding="utf-8")
        assert "bad" not in [d.name for d in _load_methodology_defs(tmp_path)]

    def test_triggers_lowercase(self) -> None:
        for d in _load_methodology_defs():
            for t in d.triggers:
                assert t == t.lower()

    def test_no_questions_field(self) -> None:
        for d in _load_methodology_defs():
            assert not hasattr(d, "questions")


# ---------------------------------------------------------------------------
# _match_methodology
# ---------------------------------------------------------------------------


class TestMatchMethodology:
    def test_matches_trigger(self) -> None:
        defs = [_make("bmad", ["start bmad", "/methodology bmad"])]
        assert _match_methodology("start bmad", defs).name == "bmad"

    def test_returns_def_with_prompt(self) -> None:
        defs = [_make("bmad", ["start bmad"], prompt="Run BMAD.")]
        assert _match_methodology("start bmad", defs).prompt == "Run BMAD."

    def test_case_insensitive(self) -> None:
        defs = [_make("bmad", ["start bmad"])]
        assert _match_methodology("START BMAD", defs) is not None

    def test_strips_whitespace(self) -> None:
        defs = [_make("bmad", ["/methodology bmad"])]
        assert _match_methodology("  /methodology bmad  ", defs) is not None

    def test_no_match_returns_none(self) -> None:
        defs = [_make("bmad", ["start bmad"])]
        assert _match_methodology("add a function", defs) is None

    def test_partial_phrase_not_matched(self) -> None:
        defs = [_make("bmad", ["start bmad"])]
        assert _match_methodology("do bmad stuff later", defs) is None

    def test_empty_string_returns_none(self) -> None:
        assert _match_methodology("", [_make("bmad", ["start bmad"])]) is None

    def test_empty_defs_returns_none(self) -> None:
        assert _match_methodology("start bmad", []) is None

    def test_project_yaml_methodology(self, tmp_path: Path) -> None:
        proj = tmp_path / ".yana" / "methodologies"
        proj.mkdir(parents=True)
        (proj / "openspec.yaml").write_text(
            "name: openspec\ndisplay_name: OpenSpec\ntriggers:\n  - start openspec\nprompt: Run it.\n",
            encoding="utf-8",
        )
        defs = _load_methodology_defs(tmp_path)
        assert _match_methodology("start openspec", defs) is not None


# ---------------------------------------------------------------------------
# _worktree_has_files
# ---------------------------------------------------------------------------


class TestWorktreeHasFiles:
    def test_empty_dir(self, tmp_path: Path) -> None:
        assert not _worktree_has_files(tmp_path)

    def test_file_present(self, tmp_path: Path) -> None:
        (tmp_path / "SPEC.md").write_text("x", encoding="utf-8")
        assert _worktree_has_files(tmp_path)

    def test_nonexistent(self, tmp_path: Path) -> None:
        assert not _worktree_has_files(tmp_path / "gone")

    def test_nested_file(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "f.md").write_text("x", encoding="utf-8")
        assert _worktree_has_files(tmp_path)

    def test_dir_only(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        assert not _worktree_has_files(tmp_path)
