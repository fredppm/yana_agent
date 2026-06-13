"""
dispatcher.py — Engine dispatch logic for YANA programmer mode (Story 1.3).

Assembles an EngineRequest from the clarified prompt + sanctum context,
creates the git worktree, and dispatches to the coding engine.

Invariant: worktree is ALWAYS created immediately before engine.dispatch().
It never exists during the clarification phase (Story 1.2 AC-1.2.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from programmer.engine import CodingEngine, EngineRequest, EngineSession, load_engine
from programmer.mode import SanctumContext
from programmer.worktree import WorktreeError, WorktreeManager, detect_repo_root

# ---------------------------------------------------------------------------
# Dispatch result
# ---------------------------------------------------------------------------


@dataclass
class DispatchResult:
    """Returned by dispatch_request() on success."""

    session: EngineSession
    worktree_path: Path
    session_id: str
    engine: CodingEngine  # same instance that created the session — needed for events() and send()
    worktree_manager: WorktreeManager  # lifecycle manager — used for cleanup after filter.run()


@dataclass
class DispatchFailed:
    """Returned by dispatch_request() when worktree creation or dispatch fails."""

    reason: str


DispatchOutcome = DispatchResult | DispatchFailed


# ---------------------------------------------------------------------------
# Session ID generation
# ---------------------------------------------------------------------------


def new_session_id() -> str:
    """Generate a unique programmer session ID."""
    return datetime.now().strftime("prog-%Y%m%d-%H%M%S")


# ---------------------------------------------------------------------------
# Main dispatch entry point
# ---------------------------------------------------------------------------


def dispatch_request(
    enriched_prompt: str,
    sanctum: SanctumContext,
    session_id: str,
    engine: CodingEngine | None = None,
    repo_root: Path | None = None,
    config: dict | None = None,
) -> DispatchOutcome:
    """
    Create worktree, assemble EngineRequest, dispatch to engine.

    Arguments:
      enriched_prompt: clarified request (original + all Q&A from clarification gate)
      sanctum:         sanctum context loaded at programmer mode activation
      session_id:      unique ID for this session (from new_session_id())
      engine:          coding engine instance (loaded from config if None)
      repo_root:       path to target git repo (auto-detected from cwd if None)
      config:          providers config dict (loaded from yaml if None)

    Returns DispatchResult on success, DispatchFailed on worktree or engine error.
    """
    # --- Resolve engine ---
    if engine is None:
        engine = load_engine(config)

    # --- Detect repo root ---
    try:
        if repo_root is None:
            repo_root = detect_repo_root()
    except WorktreeError as exc:
        return DispatchFailed(reason=str(exc))

    # --- Create worktree immediately before dispatch (AC-1.3.1) ---
    wm = WorktreeManager(repo_root=repo_root, session_id=session_id)
    try:
        worktree_path = wm.create()
    except WorktreeError as exc:
        return DispatchFailed(reason=f"Could not create worktree: {exc}")

    # --- Assemble EngineRequest (AC-1.3.2) ---
    request = EngineRequest(
        prompt=enriched_prompt,
        context=sanctum.as_context_string(),
        worktree_path=worktree_path,
        session_id=session_id,
    )

    # --- Dispatch via abstraction — never call engine APIs directly (AC-1.3.3) ---
    try:
        session = engine.dispatch(request)
    except Exception as exc:
        # Engine dispatch failure — worktree was created but dispatch failed
        # Leave worktree intact (Fred may want to inspect); Story 2.1 handles cleanup
        return DispatchFailed(reason=f"Engine dispatch failed: {exc}")

    return DispatchResult(
        session=session,
        worktree_path=worktree_path,
        session_id=session_id,
        engine=engine,
        worktree_manager=wm,
    )
