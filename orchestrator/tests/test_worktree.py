"""
test_worktree.py — Story 2.1: worktree lifecycle management tests.

Uses subprocess mocks — no real git operations.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from programmer.worktree import (
    WorktreeError,
    WorktreeManager,
    remove_worktree,
)

# ---------------------------------------------------------------------------
# WorktreeManager.create()
# ---------------------------------------------------------------------------


class TestWorktreeManagerCreate:
    def test_create_returns_path(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            path = wm.create()
        assert path == tmp_path / ".yana" / "worktrees" / "programmer-s1"

    def test_create_raises_on_git_failure(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="fatal: branch exists"
            )
            with pytest.raises(WorktreeError, match="branch exists"):
                wm.create()

    def test_path_property(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        assert wm.path == tmp_path / ".yana" / "worktrees" / "programmer-s1"

    def test_branch_property(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        assert wm.branch == "programmer/s1"

    def test_exists_false_when_not_created(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        assert not wm.exists()

    def test_exists_true_when_dir_present(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        wm.path.mkdir(parents=True)
        assert wm.exists()


# ---------------------------------------------------------------------------
# WorktreeManager.cleanup()
# ---------------------------------------------------------------------------


class TestWorktreeManagerCleanup:
    def test_cleanup_returns_success_message(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        with patch("programmer.worktree.remove_worktree") as mock_rm:
            msg = wm.cleanup()
        assert "cleaned up" in msg.lower()
        mock_rm.assert_called_once_with(tmp_path, "s1", force=False)

    def test_cleanup_force(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        with patch("programmer.worktree.remove_worktree") as mock_rm:
            wm.cleanup(force=True)
        mock_rm.assert_called_once_with(tmp_path, "s1", force=True)

    def test_cleanup_does_not_raise_on_git_error(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        with patch(
            "programmer.worktree.remove_worktree",
            side_effect=WorktreeError("disk full"),
        ):
            msg = wm.cleanup()
        assert "cleanup failed" in msg.lower() or "preserved" in msg.lower()

    def test_cleanup_failure_includes_path(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        with patch(
            "programmer.worktree.remove_worktree",
            side_effect=WorktreeError("error"),
        ):
            msg = wm.cleanup()
        assert str(wm.path) in msg


# ---------------------------------------------------------------------------
# WorktreeManager.stop_and_cleanup()
# ---------------------------------------------------------------------------


class TestStopAndCleanup:
    def test_calls_session_stop_before_cleanup(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        session = MagicMock()
        session.stop = MagicMock()

        with patch("programmer.worktree.remove_worktree"):
            wm.stop_and_cleanup(session)

        session.stop.assert_called_once()

    def test_cleanup_called_with_force(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        with patch("programmer.worktree.remove_worktree") as mock_rm:
            wm.stop_and_cleanup(engine_session=None)
        mock_rm.assert_called_once_with(tmp_path, "s1", force=True)

    def test_session_stop_failure_does_not_prevent_cleanup(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        session = MagicMock()
        session.stop.side_effect = RuntimeError("process already dead")

        with patch("programmer.worktree.remove_worktree") as mock_rm:
            msg = wm.stop_and_cleanup(session)

        # Cleanup still ran despite stop() raising
        mock_rm.assert_called_once()
        assert msg  # returned some message

    def test_none_session_skips_stop(self, tmp_path: Path) -> None:
        wm = WorktreeManager(repo_root=tmp_path, session_id="s1")
        with patch("programmer.worktree.remove_worktree"):
            msg = wm.stop_and_cleanup(engine_session=None)
        assert msg


# ---------------------------------------------------------------------------
# remove_worktree — branch deletion logic
# ---------------------------------------------------------------------------


class TestBranchDeletionLogic:
    def test_branch_not_deleted_if_pushed(self, tmp_path: Path) -> None:
        """If branch has an upstream (was pushed), it is NOT deleted."""

        def fake_run(cmd, **kwargs):
            if "upstream" in " ".join(cmd):
                return MagicMock(returncode=0, stdout="origin/programmer/s1", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run) as mock_run:
            remove_worktree(tmp_path, "s1")

        # git branch -d should NOT have been called
        calls = [" ".join(c[0][0]) for c in mock_run.call_args_list]
        branch_delete_calls = [c for c in calls if "branch" in c and "-d" in c]
        assert len(branch_delete_calls) == 0

    def test_branch_deleted_if_not_pushed(self, tmp_path: Path) -> None:
        """If branch has no upstream (not pushed), it IS deleted."""

        def fake_run(cmd, **kwargs):
            if "upstream" in " ".join(cmd):
                return MagicMock(returncode=128, stdout="", stderr="no upstream")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run) as mock_run:
            remove_worktree(tmp_path, "s1")

        calls = [" ".join(c[0][0]) for c in mock_run.call_args_list]
        branch_delete_calls = [c for c in calls if "branch" in c and "-d" in c]
        assert len(branch_delete_calls) == 1

    def test_remove_worktree_failure_raises(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="no such worktree")
            with pytest.raises(WorktreeError, match="no such worktree"):
                remove_worktree(tmp_path, "s1")
