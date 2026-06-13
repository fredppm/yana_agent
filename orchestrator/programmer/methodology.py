"""
methodology.py -- Methodology routing for YANA programmer mode (Story 2.2).

YANA detects a methodology trigger, builds a dispatch prompt, and hands off
to the engine. The engine handles all input collection and execution via the
existing decision-point loop -- YANA never collects methodology-specific inputs.

Methodology definitions live in YAML files. Adding a new methodology requires
only a YAML file -- no Python changes.

Two sources of definitions (merged, project-specific wins on collision):
  1. Bundled:          programmer/methodologies/*.yaml  (shipped with YANA)
  2. Project-specific: {repo_root}/.yana/methodologies/*.yaml  (optional)

Design Principle 1: YANA is the interface; the engine is the executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_BUNDLED_DIR = Path(__file__).parent / "methodologies"


# ---------------------------------------------------------------------------
# Methodology definition -- loaded from YAML
# ---------------------------------------------------------------------------


@dataclass
class MethodologyDef:
    """
    Defines one methodology: trigger phrases and the dispatch prompt.
    Loaded from a YAML file; never hardcoded in Python.
    """

    name: str  # machine name: "bmad", "speckit"
    display_name: str  # human label: "BMAD", "SpecKit"
    triggers: list[str]  # exact-match trigger phrases (stored lowercased)
    prompt: str  # prompt sent to the engine to kick off the methodology


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_methodology_defs(repo_root: Path | None = None) -> list[MethodologyDef]:
    """
    Load methodology definitions from YAML files.

    Bundled definitions are loaded first; project-specific override by name.
    repo_root=None loads bundled only.
    """
    defs: dict[str, MethodologyDef] = {}

    for yaml_file in sorted(_BUNDLED_DIR.glob("*.yaml")):
        defn = _load_yaml_def(yaml_file)
        if defn:
            defs[defn.name] = defn

    if repo_root is not None:
        project_dir = repo_root / ".yana" / "methodologies"
        if project_dir.exists():
            for yaml_file in sorted(project_dir.glob("*.yaml")):
                defn = _load_yaml_def(yaml_file)
                if defn:
                    defs[defn.name] = defn  # project wins

    return list(defs.values())


def _load_yaml_def(yaml_file: Path) -> MethodologyDef | None:
    """Parse one YAML file into a MethodologyDef. Returns None on any error."""
    try:
        import yaml

        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        name = str(data.get("name", yaml_file.stem))
        return MethodologyDef(
            name=name,
            display_name=str(data.get("display_name", name.upper())),
            triggers=[str(t).strip().lower() for t in data.get("triggers", [])],
            prompt=str(data.get("prompt", f"Run the {name.upper()} methodology in the worktree.")),
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_methodology(text: str, defs: list[MethodologyDef]) -> MethodologyDef | None:
    """
    Return the MethodologyDef if text matches a trigger phrase, else None.
    Comparison is case-insensitive and strips surrounding whitespace.
    """
    low = text.strip().lower()
    for defn in defs:
        if low in defn.triggers:
            return defn
    return None


def check_artifacts(worktree_path: Path) -> bool:
    """
    Return True if the worktree contains at least one file.

    Called after engine completion to verify the methodology produced output.
    Content validation is the engine's responsibility.
    """
    if not worktree_path.exists():
        return False
    return any(f for f in worktree_path.rglob("*") if f.is_file())
