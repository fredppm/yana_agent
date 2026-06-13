"""
engines/claude_code.py — Claude Code engine implementation.

Implements CodingEngine using the Claude Code CLI subprocess interface.
The CLI is invoked with --output-format stream-json so events arrive as
newline-delimited JSON — each line is one EngineEvent mapped to our types.

Upgrade path to Agent SDK:
  When the Anthropic Python Agent SDK is available (anthropic[claude-code]),
  replace _run_process() with the SDK's async session. The EngineSession,
  dispatch(), send(), and events() signatures stay identical — only this
  file changes.

Claude Code event mapping:
  {"type": "assistant", ...}           → ProgressUpdate (technical noise)
  {"type": "result", subtype: "success"} → CompletionSignal
  {"type": "result", subtype: "error"}   → EngineError(ENGINE_FAILURE)
  {"type": "system", subtype: "init"}    → ProgressUpdate
  Lines containing decision markers      → DecisionPoint (heuristic detection)
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue

from programmer.decision_points import DecisionPointKind
from programmer.engine import (
    CodingEngine,
    CompletionSignal,
    DecisionPoint,
    EngineError,
    EngineEvent,
    EngineRequest,
    EngineSession,
    ProgressUpdate,
)

# ---------------------------------------------------------------------------
# Claude Code session handle
# ---------------------------------------------------------------------------


@dataclass
class ClaudeCodeSession(EngineSession):
    """Session state for a Claude Code subprocess session."""

    session_id: str
    worktree_path: Path
    process: subprocess.Popen | None = None
    event_queue: Queue = field(default_factory=Queue)
    output_buffer: list[str] = field(default_factory=list)  # raw technical output
    _reader_thread: threading.Thread | None = field(default=None, repr=False)

    def stop(self) -> None:
        """Signal the engine process to stop."""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


# ---------------------------------------------------------------------------
# Decision-point heuristics
# ---------------------------------------------------------------------------

# Phrases in Claude Code output that indicate a decision is needed.
# These are heuristic — the Agent SDK will provide structured events instead.
_DECISION_MARKERS: list[tuple[str, DecisionPointKind]] = [
    ("overwrite?", DecisionPointKind.ERROR_REQUIRING_CHOICE),
    ("replace?", DecisionPointKind.ERROR_REQUIRING_CHOICE),
    ("confirm?", DecisionPointKind.PERMISSION_REQUEST),
    ("proceed?", DecisionPointKind.PERMISSION_REQUEST),
    ("push", DecisionPointKind.PERMISSION_REQUEST),
    ("open pr", DecisionPointKind.PERMISSION_REQUEST),
    ("which", DecisionPointKind.AMBIGUITY),
    ("clarif", DecisionPointKind.AMBIGUITY),
]


def _detect_decision(text: str) -> DecisionPoint | None:
    """
    Heuristically detect whether a text line contains a decision point.
    Returns None if this is technical noise.
    """
    lower = text.lower()
    for marker, kind in _DECISION_MARKERS:
        if marker in lower:
            return DecisionPoint(kind=kind, message=text.strip())
    return None


# ---------------------------------------------------------------------------
# Claude Code engine
# ---------------------------------------------------------------------------


class ClaudeCodeEngine(CodingEngine):
    """
    Coding engine backed by the Claude Code CLI.

    Config keys (from providers.yaml engines.claude_code):
      sdk:   "subprocess" (default) | "anthropic_agent" (future)
      model: model ID to pass via --model (optional, defaults to Claude Code's default)
      flags: list of extra CLI flags (optional)
    """

    def __init__(self, config: dict) -> None:
        self._model: str | None = config.get("model")
        self._extra_flags: list[str] = config.get("flags", [])

    # ------------------------------------------------------------------
    # CodingEngine interface
    # ------------------------------------------------------------------

    def dispatch(self, request: EngineRequest) -> ClaudeCodeSession:
        """
        Start a Claude Code session for the given request.

        Launches `claude -p <prompt> --output-format stream-json` in the
        worktree directory. A background thread drains stdout into the
        session's event queue.
        """
        session = ClaudeCodeSession(
            session_id=request.session_id,
            worktree_path=request.worktree_path,
        )

        # Build the full prompt: context + request
        full_prompt = f"{request.context}\n\n---\n\n{request.prompt}"

        cmd = self._build_command(full_prompt, resume_id=None)

        session.process = subprocess.Popen(
            cmd,
            cwd=str(request.worktree_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        # Start background reader thread
        session._reader_thread = threading.Thread(
            target=self._drain_stdout,
            args=(session,),
            daemon=True,
        )
        session._reader_thread.start()

        return session

    def send(self, session: EngineSession, message: str) -> None:
        """
        Send a follow-up message to an active session.

        For subprocess sessions: re-invokes claude with --resume to continue
        the same session. The message (Fred's answer) is passed as the prompt.
        """
        assert isinstance(session, ClaudeCodeSession)

        # Stop the current process if still running
        if session.process and session.process.poll() is None:
            session.process.terminate()
            session.process.wait(timeout=5)

        cmd = self._build_command(message, resume_id=session.session_id)

        session.process = subprocess.Popen(
            cmd,
            cwd=str(session.worktree_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        # Restart reader thread for the resumed process
        session._reader_thread = threading.Thread(
            target=self._drain_stdout,
            args=(session,),
            daemon=True,
        )
        session._reader_thread.start()

    def events(self, session: EngineSession) -> Iterator[EngineEvent]:
        """
        Yield EngineEvents from the session's event queue.

        Blocks until an event arrives or the process ends.
        Yields until a CompletionSignal or EngineError is yielded.
        """
        assert isinstance(session, ClaudeCodeSession)

        while True:
            try:
                event: EngineEvent = session.event_queue.get(timeout=1.0)
                yield event
                if isinstance(event, (CompletionSignal, EngineError)):
                    break
            except Empty:
                # Check if the process ended without sending a completion event
                if session.process and session.process.poll() is not None:
                    if session._reader_thread and not session._reader_thread.is_alive():
                        # Process ended; drain any remaining queued events
                        while not session.event_queue.empty():
                            yield session.event_queue.get_nowait()
                        # If no CompletionSignal was received, synthesize an EngineError
                        yield EngineError(
                            kind=DecisionPointKind.ENGINE_FAILURE,
                            message="Engine process ended without a completion signal.",
                        )
                        break

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_command(self, prompt: str, resume_id: str | None) -> list[str]:
        """Build the claude CLI command."""
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json"]
        if self._model:
            cmd += ["--model", self._model]
        if resume_id:
            cmd += ["--resume", resume_id]
        cmd += self._extra_flags
        return cmd

    def _drain_stdout(self, session: ClaudeCodeSession) -> None:
        """
        Background thread: reads stdout line by line, parses JSON events,
        and puts EngineEvent objects into the session queue.
        """
        assert session.process is not None
        assert session.process.stdout is not None

        for line in session.process.stdout:
            line = line.rstrip("\n")
            if not line:
                continue

            # Buffer all raw output (available via /show-output)
            session.output_buffer.append(line)

            event = self._parse_line(line)
            if event is not None:
                session.event_queue.put(event)

        # Ensure process is reaped
        session.process.wait()

    def _parse_line(self, line: str) -> EngineEvent | None:
        """
        Parse one line of Claude Code stream-json output into an EngineEvent.
        Returns None for lines that should be silently buffered.
        """
        # Try JSON first (stream-json format)
        if line.startswith("{"):
            try:
                data = json.loads(line)
                return self._parse_json_event(data)
            except json.JSONDecodeError:
                pass

        # Plain text fallback — check for decision-point heuristics
        dp = _detect_decision(line)
        if dp:
            return dp

        # Everything else is technical noise
        return ProgressUpdate(message=line)

    def _parse_json_event(self, data: dict) -> EngineEvent:
        """Map a Claude Code stream-json object to an EngineEvent."""
        event_type = data.get("type", "")
        subtype = data.get("subtype", "")

        if event_type == "result":
            if subtype == "success":
                result_text = data.get("result", "") or data.get("message", "Task complete.")
                return CompletionSignal(summary=str(result_text))
            else:
                error_msg = data.get("error", data.get("message", "Engine returned an error."))
                return EngineError(
                    kind=DecisionPointKind.ENGINE_FAILURE,
                    message=str(error_msg),
                )

        if event_type == "assistant":
            # Extract text content from assistant message
            message = data.get("message", {})
            content = message.get("content", []) if isinstance(message, dict) else []
            text = " ".join(block.get("text", "") for block in content if isinstance(block, dict))
            # Check for decision heuristics in assistant text
            if text:
                dp = _detect_decision(text)
                if dp:
                    return dp
            return ProgressUpdate(message=text or str(data))

        # system, init, and anything else = progress/noise
        return ProgressUpdate(message=str(data))
