"""
filter.py — Decision-point filter for YANA programmer mode (Stories 1.4, 2.1).

Reads EngineEvent objects from engine.events(session) and routes them:
  DecisionPoint   → surface to Fred, collect answer, forward to engine
  ProgressUpdate  → buffer silently (technical noise)
  CompletionSignal → surface to Fred as completion notice, stop loop
  EngineError     → surface to Fred, stop loop

Story 2.1 additions:
  - FilterStatus returned by run() — caller uses it for lifecycle management
  - /cancel command recognised at any decision point → FilterStatus.CANCELLED
  - Events stream ending without CompletionSignal → FilterStatus.ENGINE_ERROR (crash)

Design Principle 5: YANA does not surface output that does not require Fred's action.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import Enum

from programmer.engine import (
    CodingEngine,
    CompletionSignal,
    DecisionPoint,
    EngineError,
    EngineSession,
    ProgressUpdate,
)

# After this many seconds without any event surfaced to Fred, say "still running" once.
_STILL_RUNNING_THRESHOLD_SECS = 60.0

# Commands Fred can type to request raw engine output
_SHOW_OUTPUT_COMMANDS = {"/show-output", "mostra o output", "show output"}

# Commands Fred can type to cancel the current engine session
_CANCEL_COMMANDS = {"/cancel", "cancela", "cancel"}


class FilterStatus(Enum):
    """Result of EventFilter.run() — used by the caller for lifecycle decisions."""

    COMPLETED = "completed"  # CompletionSignal received — task finished normally
    ENGINE_ERROR = "engine_error"  # EngineError received, or events stream ended without signal
    CANCELLED = "cancelled"  # Fred issued /cancel at a decision point


class EventFilter:
    """
    Reads events from engine.events(session) and routes them per the taxonomy.

    Instantiate once per dispatch, then call run().
    """

    def __init__(
        self,
        engine: CodingEngine,
        session: EngineSession,
        speak_fn: Callable[[str], None] | None = None,
        listen_fn: Callable[[], str] | None = None,
    ) -> None:
        self.engine = engine
        self.session = session
        self.speak_fn = speak_fn
        self.listen_fn = listen_fn
        self.output_buffer: list[str] = []  # buffered technical noise
        self._notified_still_running = False
        self._last_surface_time = time.monotonic()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> FilterStatus:
        """
        Consume engine events until CompletionSignal, EngineError, or cancel.

        Returns FilterStatus so the caller can decide lifecycle actions
        (cleanup worktree, offer resume, etc.).
        """
        for event in self.engine.events(self.session):
            if isinstance(event, ProgressUpdate):
                self._handle_progress(event)
            elif isinstance(event, DecisionPoint):
                cancelled = self._handle_decision_point(event)
                if cancelled:
                    return FilterStatus.CANCELLED
            elif isinstance(event, CompletionSignal):
                self._handle_completion(event)
                return FilterStatus.COMPLETED
            elif isinstance(event, EngineError):
                self._handle_error(event)
                return FilterStatus.ENGINE_ERROR

        # Events stream ended without a terminal signal — treat as crash
        return FilterStatus.ENGINE_ERROR

    def get_buffered_output(self) -> str:
        """Return all buffered technical output as a single string."""
        return "\n".join(self.output_buffer)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_progress(self, event: ProgressUpdate) -> None:
        """Buffer technical noise. Never surface unless Fred asks."""
        self.output_buffer.append(event.message)

        # AC-1.4.5: after 60s of silence, say "still running" once
        elapsed = time.monotonic() - self._last_surface_time
        if elapsed > _STILL_RUNNING_THRESHOLD_SECS and not self._notified_still_running:
            msg = "Engine is still running."
            print(msg, flush=True)
            if self.speak_fn:
                self.speak_fn(msg)
            self._notified_still_running = True

    def _handle_decision_point(self, event: DecisionPoint) -> bool:
        """
        Surface the decision point to Fred, collect his answer, forward to engine.

        Returns True if Fred cancelled (/cancel), False otherwise.
        If Fred types /show-output, dump the buffer and re-ask the question.
        """
        self._last_surface_time = time.monotonic()
        self._notified_still_running = False

        self._present_decision_point(event)
        answer = self._collect_answer()

        # Special case: Fred wants to see raw output before deciding
        if answer.strip().lower() in _SHOW_OUTPUT_COMMANDS:
            self._print_output_buffer()
            self._present_decision_point(event)
            answer = self._collect_answer()

        # Cancel at decision point
        if answer.strip().lower() in _CANCEL_COMMANDS:
            return True  # signal cancelled to run()

        # Forward verbatim — YANA never modifies Fred's answer (AC-1.4.3)
        self.engine.send(self.session, answer)
        return False

    def _handle_completion(self, event: CompletionSignal) -> None:
        """Surface completion signal — formatted for Fred, not raw."""
        self._last_surface_time = time.monotonic()
        msg = f"Engine finished. {event.summary} What's next?"
        print(f"\n{msg}", flush=True)
        if self.speak_fn:
            self.speak_fn(msg)

    def _handle_error(self, event: EngineError) -> None:
        """Surface engine error — Fred decides what to do next."""
        self._last_surface_time = time.monotonic()
        msg = f"Engine error: {event.message}"
        print(f"\n[erro] {msg}", flush=True)
        if self.speak_fn:
            self.speak_fn(msg)

    # ------------------------------------------------------------------
    # Presentation helpers
    # ------------------------------------------------------------------

    def _present_decision_point(self, event: DecisionPoint) -> None:
        """Print (and speak) a decision point with its options."""
        display = event.message
        if event.options:
            display += f"  [{' / '.join(event.options)}]"
        print(f"\n[decision] {display}", flush=True)
        if self.speak_fn:
            self.speak_fn(event.message)  # speak message only, not options

    def _collect_answer(self) -> str:
        """Read Fred's response — STT or stdin."""
        if self.listen_fn:
            return self.listen_fn().strip()
        try:
            return input("[your answer] ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    def _print_output_buffer(self) -> None:
        """Print buffered technical output on Fred's request."""
        output = self.get_buffered_output()
        if output:
            print(f"\n--- Engine output ---\n{output}\n--- End output ---", flush=True)
        else:
            print("\n[No engine output buffered yet]", flush=True)
