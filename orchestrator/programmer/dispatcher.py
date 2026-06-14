"""
dispatcher.py — Engine dispatch logic for YANA programmer mode.

Assembles an EngineRequest from the prompt + sanctum context,
creates the git worktree, and dispatches to the coding engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from programmer.engine import EngineRequest, load_engine
from programmer.mode import SanctumContext
from programmer.worktree import WorktreeError, WorktreeManager, detect_repo_root


@dataclass
class DispatchResult:
    """Returned by dispatch_request() on success."""

    worktree_path: Path
    session_id: str
    worktree_manager: WorktreeManager
    exit_code: int


@dataclass
class DispatchFailed:
    """Returned by dispatch_request() when worktree creation or dispatch fails."""

    reason: str


DispatchOutcome = DispatchResult | DispatchFailed


def new_session_id() -> str:
    """Generate a unique programmer session ID."""
    return datetime.now().strftime("prog-%Y%m%d-%H%M%S")


def dispatch_request(
    enriched_prompt: str,
    sanctum: SanctumContext,
    session_id: str,
    engine=None,
    repo_root: Path | None = None,
    config: dict | None = None,
) -> DispatchOutcome:
    """
    Create worktree, assemble EngineRequest, run engine interactively.

    Blocks until the engine session ends (Fred exits or task completes).
    Returns DispatchResult on success, DispatchFailed on error.
    """
    if engine is None:
        engine = load_engine(config)

    try:
        if repo_root is None:
            repo_root = detect_repo_root()
    except WorktreeError as exc:
        return DispatchFailed(reason=str(exc))

    wm = WorktreeManager(repo_root=repo_root, session_id=session_id)
    try:
        worktree_path = wm.create()
    except WorktreeError as exc:
        return DispatchFailed(reason=f"Could not create worktree: {exc}")

    request = EngineRequest(
        prompt=enriched_prompt,
        context=sanctum.as_context_string(),
        worktree_path=worktree_path,
        session_id=session_id,
    )

    try:
        exit_code = engine.dispatch(request)
    except Exception as exc:
        wm.cleanup(force=True)
        return DispatchFailed(reason=f"Engine dispatch failed: {exc}")

    return DispatchResult(
        worktree_path=worktree_path,
        session_id=session_id,
        worktree_manager=wm,
        exit_code=exit_code,
    )
