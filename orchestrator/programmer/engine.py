"""
engine.py — Coding engine abstraction for YANA programmer mode.

Defines the EngineRequest data type and the CodingEngine interface.

YANA creates a worktree, assembles an EngineRequest, and calls
engine.dispatch() — which runs the coding engine interactively in the
worktree. Fred talks to the engine directly; YANA steps aside until
the session ends.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class EngineRequest:
    """Everything YANA sends to the engine when dispatching a request."""

    prompt: str  # Fred's request
    context: str  # sanctum summary (BOND.md — episodic memory from Graphiti)
    worktree_path: Path
    session_id: str


class CodingEngine(ABC):
    """
    Abstract coding engine.

    dispatch() runs synchronously — it blocks until the session ends
    (Fred exits the engine or the task completes). Fred interacts with
    the engine directly; YANA does not intercept the I/O.
    """

    @abstractmethod
    def dispatch(self, request: EngineRequest) -> int:
        """
        Run the coding engine for this request.

        Returns the process exit code. Blocks until the session ends.
        """


def load_engine(config: dict | None = None) -> CodingEngine:
    """
    Instantiate and return the configured coding engine.

    providers.yaml engines section:
        engines:
          default: claude_code
          claude_code:
            model: claude-sonnet-4-6   # optional
            flags: []                  # optional extra CLI flags
    """
    if config is None:
        import providers as prov

        config = prov.load_providers()

    engines_cfg = config.get("engines", {})
    engine_name = engines_cfg.get("default", "claude_code")
    engine_cfg = engines_cfg.get(engine_name, {})

    if engine_name == "claude_code":
        from programmer.engines.claude_code import ClaudeCodeEngine

        return ClaudeCodeEngine(engine_cfg)

    raise ValueError(
        f"Unknown engine: {engine_name!r}. "
        "Available: claude_code. Add a new engines/ implementation to extend."
    )
