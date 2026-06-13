"""
clarification.py — Clarification gate for YANA programmer mode (Story 1.2).

Before routing any request to the engine, YANA detects gaps and asks Fred to
fill them — one question at a time, sequentially, with a hard stop on no answer.

Design Principle 3: YANA exposes gaps; never fills them.
Design Principle 5: YANA does not act without input.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class Clarified:
    """Clarification succeeded. enriched_prompt is ready to dispatch."""

    enriched_prompt: str  # original request + all Q&A pairs, assembled


@dataclass
class Cancelled:
    """Fred did not answer a required question. Request is stopped."""

    reason: str = "no_clarification_provided"


ClarificationResult = Clarified | Cancelled

# ---------------------------------------------------------------------------
# Gap detection prompt
# ---------------------------------------------------------------------------

_GAP_DETECTION_SYSTEM = (
    "You are a senior software engineer reviewing a development request before it is "
    "handed to a coding engine. Your job is to identify questions that, if left unanswered, "
    "would force the coding engine to make a material assumption — one that could "
    "significantly change what gets built.\n\n"
    "Rules:\n"
    "- Ask only about gaps that would materially change the implementation "
    "(different API, different data model, different scope, different target file).\n"
    "- Do NOT ask about style preferences, naming conventions, or minor details.\n"
    "- Do NOT ask questions the request has already answered.\n"
    "- Maximum 3 questions.\n"
    "- Return ONLY a JSON array of strings. No explanation, no markdown, no prefix.\n"
    "- If the request is complete and unambiguous enough to proceed, return []."
)

_GAP_DETECTION_TEMPLATE = (
    "Context about Fred and the current project:\n{context}\n\nDevelopment request:\n{request}"
)


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------


def detect_gaps(
    request: str,
    context: str,
    config: dict | None = None,
) -> list[str]:
    """
    Use an LLM to identify clarifying questions for this request.

    Returns a list of question strings. Empty list = request is complete.
    Falls back to [] on any parse or LLM error (so the process is not blocked
    by a transient LLM failure — in that case YANA proceeds without clarification).
    """
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import providers as prov

    if config is None:
        config = prov.load_providers()

    prompt = _GAP_DETECTION_TEMPLATE.format(context=context or "(no context)", request=request)
    messages = [{"role": "user", "content": prompt}]

    try:
        response = prov.call_llm(
            messages,
            system_prompt=_GAP_DETECTION_SYSTEM,
            task="conversation",
            stream=False,
            config=config,
        )
        return _parse_questions(response)
    except Exception:
        # LLM failure must not block the workflow — treat as no gaps
        return []


def _parse_questions(response: str) -> list[str]:
    """
    Parse the LLM response into a list of question strings.

    Handles responses wrapped in markdown code fences.
    Returns [] on any parse failure.
    """
    text = response.strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        inner = [ln for ln in lines if not ln.startswith("```")]
        text = "\n".join(inner).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(q).strip() for q in parsed if str(q).strip()]
        return []
    except json.JSONDecodeError:
        return []


# ---------------------------------------------------------------------------
# Clarification gate — main entry point
# ---------------------------------------------------------------------------


def run_clarification_gate(
    request: str,
    context: str,
    speak_fn: Callable[[str], None] | None = None,
    listen_fn: Callable[[], str] | None = None,
    config: dict | None = None,
) -> ClarificationResult:
    """
    Run the full clarification loop for a development request.

    1. Detect gaps via LLM
    2. If no gaps, return Clarified(enriched_prompt=request) immediately
    3. For each gap question, ask Fred and collect his answer
    4. If Fred provides no answer (empty / /skip / "skip"), return Cancelled
    5. Return Clarified(enriched_prompt) with all Q&A appended

    speak_fn:  TTS callable for voice mode (None = text mode)
    listen_fn: STT callable returning transcribed text (None = use input())
    config:    providers config dict (loads from yaml if None)
    """
    questions = detect_gaps(request, context, config)

    if not questions:
        return Clarified(enriched_prompt=request)

    answers: list[tuple[str, str]] = []  # (question, answer) pairs

    for question in questions:
        answer = _ask_one(question, speak_fn=speak_fn, listen_fn=listen_fn)

        if _is_skip(answer):
            return Cancelled(reason="no_clarification_provided")

        answers.append((question, answer))

    enriched = _assemble_enriched_prompt(request, answers)
    return Clarified(enriched_prompt=enriched)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ask_one(
    question: str,
    speak_fn: Callable[[str], None] | None,
    listen_fn: Callable[[], str] | None,
) -> str:
    """
    Present one clarifying question to Fred and return his answer.

    Voice mode: speak the question, listen for the answer.
    Text mode: print the question, read from stdin.
    """
    print(f"\n[clarification] {question}", flush=True)
    if speak_fn:
        speak_fn(question)

    if listen_fn:
        return listen_fn().strip()

    try:
        return input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def _is_skip(answer: str) -> bool:
    """Return True if Fred's answer signals he is skipping (hard stop)."""
    return answer.strip().lower() in ("", "/skip", "skip")


def _assemble_enriched_prompt(
    original_request: str,
    answers: list[tuple[str, str]],
) -> str:
    """
    Assemble the original request + all Q&A pairs into a single enriched prompt.

    The engine receives this as a single string — it does not see the
    clarification exchange as separate messages.
    """
    if not answers:
        return original_request

    parts = [original_request, "\n\n## Clarifications\n"]
    for question, answer in answers:
        parts.append(f"Q: {question}\nA: {answer}")

    return "\n".join(parts)
