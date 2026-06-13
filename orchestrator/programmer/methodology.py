"""
methodology.py — Methodology routing for YANA programmer mode (Story 2.2).

YANA detects methodology intent (BMAD, SpecKit), collects inputs conversationally,
assembles a structured prompt for the engine, and verifies artifacts exist after
engine completion.

YANA never executes methodology herself — that is the engine's responsibility.
Design Principle 1: YANA is the interface; the engine is the executor.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Trigger phrases — map methodology name → set of recognised phrases
# ---------------------------------------------------------------------------

METHODOLOGY_TRIGGERS: dict[str, set[str]] = {
    "bmad": {
        "vamos fazer um bmad",
        "start a bmad run",
        "start bmad",
        "/methodology bmad",
        "bmad run",
        "fazer bmad",
    },
    "speckit": {
        "start a speckit run",
        "start speckit",
        "/methodology speckit",
        "speckit run",
        "fazer speckit",
    },
}

# ---------------------------------------------------------------------------
# Input questions per methodology
# ---------------------------------------------------------------------------

METHODOLOGY_QUESTIONS: dict[str, list[str]] = {
    "bmad": [
        "What is the project name?",
        "What would you like to build?",
        "What are your goals for this session?",
    ],
    "speckit": [
        "What is the project name?",
        "Describe what you want to specify.",
        "Any constraints or non-goals to capture now?",
    ],
}

# Phrases that cancel input collection (mirrors clarification gate)
_CANCEL_PHRASES = {"", "/cancel", "cancela", "cancel"}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class MethodologyInputs:
    """Successfully collected inputs for a methodology run."""

    methodology: str
    answers: dict[str, str] = field(default_factory=dict)  # question → answer


@dataclass
class MethodologyCancelled:
    """Fred cancelled or gave an empty answer during input collection."""

    reason: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_methodology(text: str) -> str | None:
    """
    Return the methodology name if text is a methodology activation trigger.

    Comparison is case-insensitive and strips surrounding whitespace.
    Returns None if not a recognised trigger.
    """
    low = text.strip().lower()
    for methodology, triggers in METHODOLOGY_TRIGGERS.items():
        if low in triggers:
            return methodology
    return None


def collect_methodology_inputs(
    methodology: str,
    speak_fn: Callable[[str], None] | None = None,
    listen_fn: Callable[[], str] | None = None,
) -> MethodologyInputs | MethodologyCancelled:
    """
    Ask Fred the methodology-specific questions one at a time.

    Questions are asked sequentially. An empty answer or /cancel cancels the run.
    Returns MethodologyInputs on success, MethodologyCancelled on cancel.
    """
    questions = METHODOLOGY_QUESTIONS.get(methodology, [])
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

    return MethodologyInputs(methodology=methodology, answers=answers)


def assemble_methodology_prompt(inputs: MethodologyInputs) -> str:
    """
    Build the structured prompt for the engine.

    The engine receives: which methodology to run + Fred's answers.
    The engine is responsible for resolving what to execute inside the worktree.
    """
    lines = [
        f"Run the {inputs.methodology.upper()} methodology inside the worktree.",
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
