"""
engines/claude_code.py — Claude Code engine implementation.

Writes YANA context into the worktree as YANA_CONTEXT.md so Claude Code
picks it up, then launches `claude` interactively with inherited I/O.
Fred talks to Claude Code directly — YANA steps aside until the session ends.
"""

from __future__ import annotations

import subprocess

from programmer.engine import CodingEngine, EngineRequest

_CONTEXT_FILENAME = "YANA_CONTEXT.md"


class ClaudeCodeEngine(CodingEngine):
    """
    Coding engine backed by the Claude Code CLI.

    Config keys (from providers.yaml engines.claude_code):
      model: model ID to pass via --model (optional)
      flags: list of extra CLI flags (optional)
    """

    def __init__(self, config: dict) -> None:
        self._model: str | None = config.get("model")
        self._extra_flags: list[str] = config.get("flags", [])

    def dispatch(self, request: EngineRequest) -> int:
        """
        Write context to the worktree, then run Claude Code interactively.

        Context lands in YANA_CONTEXT.md so Claude Code reads it as project
        context on startup. Fred's request is the initial prompt passed via -p;
        after that Fred interacts with Claude Code directly.

        Returns the process exit code.
        """
        # Write context as CLAUDE.md so Claude Code picks it up as project instructions
        context_file = request.worktree_path / _CONTEXT_FILENAME
        context_file.write_text(request.context, encoding="utf-8")

        # Prepend context to prompt — Claude Code -p doesn't auto-read files
        full_prompt = (
            f"{request.context}\n\n---\n\n{request.prompt}" if request.context else request.prompt
        )

        cmd = ["claude", "-p", full_prompt]
        if self._model:
            cmd += ["--model", self._model]
        cmd += self._extra_flags

        result = subprocess.run(cmd, cwd=str(request.worktree_path))
        return result.returncode
