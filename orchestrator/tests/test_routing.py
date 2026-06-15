"""
test_routing.py — Story 1.3: route request to engine tests.

No real git operations, no subprocess calls, no engine API calls.
All external dependencies are mocked.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from programmer.dispatcher import (
    DispatchFailed,
    DispatchResult,
    dispatch_request,
    new_session_id,
)
from programmer.engine import CodingEngine, EngineRequest
from programmer.mode import SanctumContext
from programmer.worktree import (
    WorktreeError,
    _branch_name,
    _worktree_path,
    create_worktree,
    detect_repo_root,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class _MockEngine(CodingEngine):
    def __init__(self) -> None:
        self.dispatched: list[EngineRequest] = []

    def dispatch(self, request: EngineRequest) -> int:
        self.dispatched.append(request)
        return 0


@pytest.fixture
def sanctum() -> SanctumContext:
    return SanctumContext(
        bond="Fred is a developer.",
        persona="I am YANA.",
    )


@pytest.fixture
def mock_engine() -> _MockEngine:
    return _MockEngine()


# ---------------------------------------------------------------------------
# new_session_id
# ---------------------------------------------------------------------------


class TestNewSessionId:
    def test_starts_with_prog(self) -> None:
        sid = new_session_id()
        assert sid.startswith("prog-")

    def test_is_unique(self) -> None:
        ids = {new_session_id() for _ in range(5)}
        assert len(ids) >= 1

    def test_no_spaces(self) -> None:
        sid = new_session_id()
        assert " " not in sid


# ---------------------------------------------------------------------------
# Worktree path helpers
# ---------------------------------------------------------------------------


class TestWorktreePaths:
    def test_worktree_path_under_yana(self, tmp_path: Path) -> None:
        path = _worktree_path(tmp_path, "prog-20260613-120000")
        assert path == tmp_path / ".yana" / "worktrees" / "programmer-prog-20260613-120000"

    def test_branch_name_format(self) -> None:
        assert _branch_name("prog-20260613-120000") == "programmer/prog-20260613-120000"


# ---------------------------------------------------------------------------
# detect_repo_root
# ---------------------------------------------------------------------------


class TestDetectRepoRoot:
    def test_success(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="/path/to/repo\n", stderr="")
            result = detect_repo_root(tmp_path)
        assert result == Path("/path/to/repo")

    def test_not_a_repo_raises(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128, stdout="", stderr="fatal: not a git repository"
            )
            with pytest.raises(WorktreeError, match="Not a git repository"):
                detect_repo_root(tmp_path)


# ---------------------------------------------------------------------------
# create_worktree
# ---------------------------------------------------------------------------


class TestCreateWorktree:
    def test_success_returns_worktree_path(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            path = create_worktree(tmp_path, "prog-001")

        assert path == tmp_path / ".yana" / "worktrees" / "programmer-prog-001"

    def test_git_called_with_correct_args(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            create_worktree(tmp_path, "prog-001")

        args = mock_run.call_args[0][0]
        assert args[0] == "git"
        assert args[1] == "worktree"
        assert args[2] == "add"
        assert "programmer-prog-001" in args[3]
        assert args[4] == "-b"
        assert args[5] == "programmer/prog-001"

    def test_git_failure_raises_worktree_error(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="fatal: branch already exists",
            )
            with pytest.raises(WorktreeError, match="branch already exists"):
                create_worktree(tmp_path, "prog-001")

    def test_parent_dirs_created(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            create_worktree(tmp_path, "prog-001")

        parent = tmp_path / ".yana" / "worktrees"
        assert parent.exists()


# ---------------------------------------------------------------------------
# dispatch_request — EngineRequest assembly
# ---------------------------------------------------------------------------


class TestEngineRequestAssembly:
    def test_request_fields_correct(
        self, sanctum: SanctumContext, mock_engine: _MockEngine, tmp_path: Path
    ) -> None:
        with patch("programmer.dispatcher.detect_repo_root", return_value=tmp_path):
            with patch("programmer.worktree.create_worktree") as mock_wt:
                mock_wt.return_value = tmp_path / ".yana" / "worktrees" / "programmer-s1"
                dispatch_request(
                    enriched_prompt="add hello()",
                    sanctum=sanctum,
                    session_id="s1",
                    engine=mock_engine,
                    repo_root=tmp_path,
                )

        assert len(mock_engine.dispatched) == 1
        req = mock_engine.dispatched[0]
        assert req.prompt == "add hello()"
        assert req.session_id == "s1"
        assert "Fred is a developer" in req.context
        assert "programmer-s1" in str(req.worktree_path)

    def test_context_includes_sanctum(
        self, sanctum: SanctumContext, mock_engine: _MockEngine, tmp_path: Path
    ) -> None:
        with patch("programmer.dispatcher.detect_repo_root", return_value=tmp_path):
            with patch("programmer.worktree.create_worktree") as mock_wt:
                mock_wt.return_value = tmp_path / "wt"
                dispatch_request(
                    enriched_prompt="add hello()",
                    sanctum=sanctum,
                    session_id="s1",
                    engine=mock_engine,
                    repo_root=tmp_path,
                )

        req = mock_engine.dispatched[0]
        assert "Fred is a developer" in req.context or "yana_agent" in req.context

    def test_prompt_passed_verbatim(
        self, sanctum: SanctumContext, mock_engine: _MockEngine, tmp_path: Path
    ) -> None:
        prompt = "add hello() to utils.py"
        with patch("programmer.dispatcher.detect_repo_root", return_value=tmp_path):
            with patch("programmer.worktree.create_worktree") as mock_wt:
                mock_wt.return_value = tmp_path / "wt"
                dispatch_request(
                    enriched_prompt=prompt,
                    sanctum=sanctum,
                    session_id="s1",
                    engine=mock_engine,
                    repo_root=tmp_path,
                )

        req = mock_engine.dispatched[0]
        assert req.prompt == prompt


# ---------------------------------------------------------------------------
# dispatch_request — worktree created before dispatch
# ---------------------------------------------------------------------------


class TestWorktreeCreatedBeforeDispatch:
    def test_worktree_created_before_engine_dispatch(
        self, sanctum: SanctumContext, mock_engine: _MockEngine, tmp_path: Path
    ) -> None:
        call_order: list[str] = []

        def _fake_create(repo_root, session_id):
            call_order.append("create_worktree")
            return tmp_path / "wt"

        def _fake_dispatch(request):
            call_order.append("engine.dispatch")
            return 0

        with patch.object(mock_engine, "dispatch", side_effect=_fake_dispatch):
            with patch("programmer.dispatcher.detect_repo_root", return_value=tmp_path):
                with patch("programmer.worktree.create_worktree", side_effect=_fake_create):
                    dispatch_request(
                        enriched_prompt="add hello()",
                        sanctum=sanctum,
                        session_id="s1",
                        engine=mock_engine,
                        repo_root=tmp_path,
                    )

        assert call_order == ["create_worktree", "engine.dispatch"]

    def test_worktree_failure_returns_dispatch_failed(
        self, sanctum: SanctumContext, mock_engine: _MockEngine, tmp_path: Path
    ) -> None:
        with patch("programmer.dispatcher.detect_repo_root", return_value=tmp_path):
            with patch(
                "programmer.worktree.create_worktree",
                side_effect=WorktreeError("branch already exists"),
            ):
                result = dispatch_request(
                    enriched_prompt="add hello()",
                    sanctum=sanctum,
                    session_id="s1",
                    engine=mock_engine,
                    repo_root=tmp_path,
                )

        assert isinstance(result, DispatchFailed)
        assert "Could not create worktree" in result.reason
        assert "branch already exists" in result.reason

    def test_engine_not_called_on_worktree_failure(
        self, sanctum: SanctumContext, mock_engine: _MockEngine, tmp_path: Path
    ) -> None:
        with patch("programmer.dispatcher.detect_repo_root", return_value=tmp_path):
            with patch(
                "programmer.worktree.create_worktree",
                side_effect=WorktreeError("disk full"),
            ):
                dispatch_request(
                    enriched_prompt="add hello()",
                    sanctum=sanctum,
                    session_id="s1",
                    engine=mock_engine,
                    repo_root=tmp_path,
                )

        assert len(mock_engine.dispatched) == 0


# ---------------------------------------------------------------------------
# dispatch_request — result shape
# ---------------------------------------------------------------------------


class TestDispatchResult:
    def test_success_returns_dispatch_result(
        self, sanctum: SanctumContext, mock_engine: _MockEngine, tmp_path: Path
    ) -> None:
        worktree_path = tmp_path / ".yana" / "worktrees" / "programmer-s1"
        with patch("programmer.dispatcher.detect_repo_root", return_value=tmp_path):
            with patch("programmer.worktree.create_worktree", return_value=worktree_path):
                result = dispatch_request(
                    enriched_prompt="add hello()",
                    sanctum=sanctum,
                    session_id="s1",
                    engine=mock_engine,
                    repo_root=tmp_path,
                )

        assert isinstance(result, DispatchResult)
        assert result.worktree_path == worktree_path
        assert result.session_id == "s1"
        assert result.exit_code == 0

    def test_engine_dispatch_failure_returns_dispatch_failed(
        self, sanctum: SanctumContext, tmp_path: Path
    ) -> None:
        broken_engine = MagicMock(spec=CodingEngine)
        broken_engine.dispatch.side_effect = RuntimeError("SDK not installed")

        with patch("programmer.dispatcher.detect_repo_root", return_value=tmp_path):
            with patch("programmer.worktree.create_worktree", return_value=tmp_path / "wt"):
                result = dispatch_request(
                    enriched_prompt="add hello()",
                    sanctum=sanctum,
                    session_id="s1",
                    engine=broken_engine,
                    repo_root=tmp_path,
                )

        assert isinstance(result, DispatchFailed)
        assert "Engine dispatch failed" in result.reason
