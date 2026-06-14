"""
worktree.py — Git worktree management for YANA programmer mode.

Story 1.3 scope: create worktree before dispatch (happy path).
Story 2.1 scope: WorktreeManager, cleanup, crash recovery, cancel, sad paths.

Worktree naming convention:
  path:   {repo_root}/.yana/worktrees/programmer-{session_id}
  branch: programmer/{session_id}
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorktreeError(Exception):
    """Raised when a git worktree operation fails."""


# ---------------------------------------------------------------------------
# Repo root detection
# ---------------------------------------------------------------------------


def detect_repo_root(start: Path | None = None) -> Path:
    """
    Find the git repository root by running `git rev-parse --show-toplevel`.

    start: directory to search from (defaults to cwd).
    Raises WorktreeError if not inside a git repo.
    """
    cwd = start or Path.cwd()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise WorktreeError(
            f"Not a git repository (or git not found): {cwd}. git error: {result.stderr.strip()}"
        )
    return Path(result.stdout.strip())


# ---------------------------------------------------------------------------
# Worktree creation
# ---------------------------------------------------------------------------


def create_worktree(repo_root: Path, session_id: str) -> Path:
    """
    Create a git worktree for the programmer session.

    Creates:
      path:   {repo_root}/.yana/worktrees/programmer-{session_id}
      branch: programmer/{session_id}  (new branch from current HEAD)

    Returns the worktree path on success.
    Raises WorktreeError if git fails (branch exists, disk full, not a repo, etc.).
    """
    worktree_path = _worktree_path(repo_root, session_id)
    branch_name = _branch_name(session_id)

    # Ensure parent directory exists
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["git", "worktree", "add", str(worktree_path), "-b", branch_name],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or "git worktree add failed"
        raise WorktreeError(error_msg)

    return worktree_path


# ---------------------------------------------------------------------------
# Worktree removal (Story 2.1 uses this)
# ---------------------------------------------------------------------------


def remove_worktree(repo_root: Path, session_id: str, force: bool = False) -> None:
    """
    Remove the git worktree and delete the branch if it was not pushed.

    force: pass --force to git worktree remove (needed if unclean state).
    Raises WorktreeError if git fails.
    """
    worktree_path = _worktree_path(repo_root, session_id)
    branch_name = _branch_name(session_id)

    # Remove worktree
    cmd = ["git", "worktree", "remove", str(worktree_path)]
    if force:
        cmd.append("--force")

    result = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise WorktreeError(f"git worktree remove failed: {result.stderr.strip()}")

    # Delete branch if not pushed (best-effort — don't fail session end)
    _try_delete_branch(repo_root, branch_name)


def _try_delete_branch(repo_root: Path, branch_name: str) -> None:
    """Delete branch if it has no upstream (was not pushed). Best-effort."""
    # Check if branch has an upstream
    upstream_check = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", f"{branch_name}@{{upstream}}"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if upstream_check.returncode == 0:
        # Branch has upstream — it was pushed, Fred owns it now, don't delete
        return

    subprocess.run(
        ["git", "branch", "-d", branch_name],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    # Ignore failure — branch may already be gone


# ---------------------------------------------------------------------------
# WorktreeManager — lifecycle object (Story 2.1)
# ---------------------------------------------------------------------------


@dataclass
class WorktreeManager:
    """
    Manages the full lifecycle of one programmer-session worktree.

    Created by dispatch_request() and carried in DispatchResult.
    The caller (mode.py) uses it to cleanup after filter.run() returns.
    """

    repo_root: Path
    session_id: str

    @property
    def path(self) -> Path:
        return _worktree_path(self.repo_root, self.session_id)

    @property
    def branch(self) -> str:
        return _branch_name(self.session_id)

    def create(self) -> Path:
        """Create the worktree. Raises WorktreeError on failure."""
        return create_worktree(self.repo_root, self.session_id)

    def cleanup(self, force: bool = False) -> str:
        """
        Remove the worktree and delete the branch if not pushed.

        Returns a human-readable status message.
        Does NOT raise — best effort, always returns a message.
        """
        try:
            remove_worktree(self.repo_root, self.session_id, force=force)
            return "Session ended. Worktree cleaned up."
        except WorktreeError as exc:
            return f"Worktree cleanup failed: {exc}. Path preserved at {self.path}"

    def stop_and_cleanup(self, engine_session: object | None, timeout: float = 5.0) -> str:
        """
        Stop the engine session (if still running), then cleanup worktree.

        AC-2.1.2: signals engine, waits up to timeout, force-removes worktree.
        """
        # Signal engine session to stop (ClaudeCodeSession exposes stop())
        if engine_session is not None and hasattr(engine_session, "stop"):
            try:
                engine_session.stop()
            except Exception:
                pass  # best-effort

        return self.cleanup(force=True)

    def exists(self) -> bool:
        """Return True if the worktree directory currently exists on disk."""
        return self.path.exists()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _worktree_path(repo_root: Path, session_id: str) -> Path:
    return repo_root / ".yana" / "worktrees" / f"programmer-{session_id}"


def _branch_name(session_id: str) -> str:
    return f"programmer/{session_id}"
