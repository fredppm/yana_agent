"""
methodology.py — Methodology routing for YANA programmer mode (Story 2.2).

Methodology definitions live in YAML files — YANA's code is agnostic about
which methodologies exist. Adding a new methodology requires only a YAML file,
not a code change.

Two sources of definitions (merged, project-specific wins on collision):
  1. Bundled:          programmer/methodologies/*.yaml  (shipped with YANA)
  2. Project-specific: {repo_root}/.yana/methodologies/*.yaml  (optional)

YANA never executes methodology herself — that is the engine's responsibility.
Design Principle 1: YANA is the interface; the engine is the executor.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Methodology definition — loaded from YAML
# ---------------------------------------------------------------------------


@dataclass
class MethodologyDef:
    """
    Defines one methodology: its trigger phrases and input questions.
    Loaded from a YAML file; never hardcoded in Python.
    """

    name: str           # machine name: "bmad", "speckit"
    display_name: str   # human label used in prompts and messages: "BMAD", "SpecKit"
    triggers: list[str] # exact-match trigger phrases (stored lowercased)
    questions: list[str]  # questions to ask Fred before dispatching


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class MethodologyInputs:
    """Successfully collected inputs for a methodology run."""

    methodology: str          # methodology name ("bmad", "speckit", ...)
    display_name: str         # human label for messages
    answers: dict[str, str] = field(default_factory=dict)  # question → answer


@dataclass
class MethodologyCancelled:
    """Fred cancelled or gave an empty answer during input collection."""

    reason: str


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_BUNDLED_DIR = Path(__file__).parent / "methodologies"

# Cancel phrases — mirror clarification gate and filter
_CANCEL_PHRASES = {"", "/cancel", "cancela", "cancel"}


def load_methodology_defs(repo_root: Path | None = None) -> list[MethodologyDef]:
    """
    Load methodology definitions from YAML files.

    Bundled definitions (shipped with YANA) are loaded first; project-specific
    definitions override them by name. repo_root=None loads bundled only.
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
            questions=[str(q) for q in data.get("questions", [])],
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_methodology(text: str, defs: list[MethodologyDef]) -> str | None:
    """
    Return the methodology name if text matches a trigger phrase.

    Comparison is case-insensitive and strips surrounding whitespace.
    Returns None if no match.
    """
    low = text.strip().lower()
    for defn in defs:
        if low in defn.triggers:
            return defn.name
    return None


def collect_methodology_inputs(
    methodology: str,
    defs: list[MethodologyDef],
    speak_fn: Callable[[str], None] | None = None,
    listen_fn: Callable[[], str] | None = None,
) -> MethodologyInputs | MethodologyCancelled:
    """
    Ask Fred the questions defined for this methodology, one at a time.

    An empty answer or /cancel cancels the run.
    Returns MethodologyInputs on success, MethodologyCancelled on cancel.
    """
    defn = _find_def(methodology, defs)
    questions = defn.questions if defn else []
    display_name = defn.display_name if defn else methodology.upper()
    answers: dict[str, str] = {}

    for question in questions:
        print(f"\n[methodology/{methodology}] {question}", flush=True)
        if speak_fn:
            speak_fn(question)

        if listen_fn:
            answer = listen_fn().strip()
        else:
            try:
                answer = input("[your answer] ").strip()
            except (EOFError, KeyboardInterrupt):
                answer = ""

        if answer.lower() in _CANCEL_PHRASES:
            return MethodologyCancelled(
                reason=f"Cancelled during input collection for {methodology}"
            )

        answers[question] = answer

    return MethodologyInputs(
        methodology=methodology,
        display_name=display_name,
        answers=answers,
    )


def assemble_methodology_prompt(inputs: MethodologyInputs) -> str:
    """
    Build the structured prompt for the engine.

    The engine receives: which methodology to run + Fred's answers.
    The engine resolves what to execute inside the worktree.
    """
    lines = [
        f"Run the {inputs.display_name} methodology inside the worktree.",
        "",
        "## Inputs",
    ]
    for question, answer in inputs.answers.items():
        lines.append(f"**{question}** {answer}")

    return "\n".join(lines)


def check_artifacts(worktree_path: Path) -> bool:
    """
    Return True if the worktree contains at least one file.

    Called after engine completion to verify the methodology produced output.
    Does not validate artifact content — that is the engine's responsibility.
    """
    if not worktree_path.exists():
        return False
    return any(f for f in worktree_path.rglob("*") if f.is_file())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_def(methodology: str, defs: list[MethodologyDef]) -> MethodologyDef | None:
    return next((d for d in defs if d.name == methodology), None)
