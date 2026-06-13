"""
engine.py — Coding engine abstraction for YANA programmer mode.

Defines the CodingEngine interface, the EngineRequest/EngineSession/EngineEvent
data types, and the factory function that instantiates an engine from config.

Handoff contract
----------------
YANA → engine (EngineRequest):
  - prompt:         clarified request text + all clarification answers, as a single string
  - context:        sanctum summary (BOND.md + MEMORY.md condensed to ≤500 tokens) +
                    active session summary
  - worktree_path:  absolute path to the git worktree YANA created for this session
  - session_id:     unique ID for this programmer session (used for logging + --resume)

engine → YANA (stream of EngineEvent):
  - DecisionPoint:    something requires Fred's input — YANA surfaces this
  - ProgressUpdate:   technical status update — YANA suppresses this (technical noise)
  - CompletionSignal: task finished — YANA surfaces this as "Engine finished. What's next?"
  - EngineError:      unrecoverable failure — YANA surfaces this for Fred to decide

What engine never returns to YANA:
  Raw build logs, compiler output, stack traces, test runner stdout/stderr.
  These stay buffered in the engine layer and are only exposed if Fred asks (/show-output).
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Union

if TYPE_CHECKING:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from programmer.decision_points import DecisionPointKind  # noqa: E402

# ---------------------------------------------------------------------------
# Request / Session / Event types
# ---------------------------------------------------------------------------


@dataclass
class EngineRequest:
    """Everything YANA sends to the engine when dispatching a request."""

    prompt: str
    context: str
    worktree_path: Path
    session_id: str


class EngineSession:
    """
    Opaque handle to an active engine session.

    Concrete engines subclass this to carry their session state
    (e.g. subprocess handle, SDK session ID, message history).
    Callers treat it as an opaque token — pass it to send() and events().
    """


@dataclass
class DecisionPoint:
    """An event that surfaces to Fred — requires his input."""

    kind: DecisionPointKind
    message: str
    options: list[str] = field(default_factory=list)
    # options: suggested choices to present to Fred (may be empty for open-ended decisions)


@dataclass
class ProgressUpdate:
    """Technical status from the engine. YANA suppresses this (technical noise)."""

    message: str


@dataclass
class CompletionSignal:
    """Engine finished the task. YANA surfaces this as a completion notice."""

    summary: str


@dataclass
class EngineError:
    """Unrecoverable engine error. YANA surfaces this — Fred decides what to do."""

    kind: DecisionPointKind  # always DecisionPointKind.ENGINE_FAILURE
    message: str


# The union type that engine.events() yields
EngineEvent = Union[DecisionPoint, ProgressUpdate, CompletionSignal, EngineError]


# ---------------------------------------------------------------------------
# Abstract engine interface
# ---------------------------------------------------------------------------


class CodingEngine(ABC):
    """
    Abstract coding engine.

    YANA interacts with any concrete engine only through these three methods.
    Swapping engines (Claude Code → Aider → OpenCode) requires no changes
    to YANA's interaction layer — only a new CodingEngine implementation.
    """

    @abstractmethod
    def dispatch(self, request: EngineRequest) -> EngineSession:
        """
        Send a clarified request to the engine.

        Called once per programmer session, after clarification is complete
        and the git worktree has been created. Returns an EngineSession handle
        that is passed to send() and events().
        """

    @abstractmethod
    def send(self, session: EngineSession, message: str) -> None:
        """
        Send a follow-up message to an active engine session.

        Used to forward Fred's answers to DecisionPoint events back to the engine.
        The message is forwarded verbatim — YANA does not interpret or modify it.
        """

    @abstractmethod
    def events(self, session: EngineSession) -> Iterator[EngineEvent]:
        """
        Yield structured events from an active engine session.

        YANA's filter (Story 1.4) reads from this iterator:
          - DecisionPoint and CompletionSignal → surface to Fred
          - EngineError → surface to Fred
          - ProgressUpdate → buffer as technical noise, never surface proactively
        """


# ---------------------------------------------------------------------------
# Factory — instantiate engine from providers.yaml config
# ---------------------------------------------------------------------------


def load_engine(config: dict | None = None) -> CodingEngine:
    """
    Instantiate and return the configured coding engine.

    Reads the engines: section from providers.yaml (same file as LLM providers).
    The engine is declared by name under engines.default — not hardcoded.

    providers.yaml engines section format:
        engines:
          default: claude_code
          claude_code:
            sdk: anthropic_agent   # or subprocess
            model: claude-sonnet-4-6

    Raises ValueError if the engine name is not recognised.
    Raises FileNotFoundError if providers.yaml is missing (via load_providers).
    """
    if config is None:
        # Import here to avoid circular imports at module load time
        import providers as prov  # noqa: PLC0415

        config = prov.load_providers()

    engines_cfg = config.get("engines", {})
    engine_name = engines_cfg.get("default", "claude_code")
    engine_cfg = engines_cfg.get(engine_name, {})

    if engine_name == "claude_code":
        from programmer.engines.claude_code import ClaudeCodeEngine

        return ClaudeCodeEngine(engine_cfg)

    raise ValueError(
        f"Unknown engine: {engine_name!r}. "
        f"Available: claude_code. Add a new engines/ implementation to extend."
    )
