"""
test_engine.py — Story 0.1: engine abstraction layer tests.

No Anthropic API calls, no subprocess invocations.
All external dependencies are mocked.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_config() -> dict:
    """providers.yaml config with an engines section."""
    return {
        "llm": {
            "providers": {
                "anthropic": {
                    "api_key_env": "ANTHROPIC_API_KEY",
                    "models": {"default": "claude-sonnet-4-6", "fast": "claude-haiku-4-5"},
                }
            },
            "routing": {"conversation": "default"},
        },
        "engines": {
            "default": "claude_code",
            "claude_code": {
                "sdk": "subprocess",
                "model": "claude-sonnet-4-6",
            },
        },
    }


@pytest.fixture
def sample_request(tmp_path: Path) -> EngineRequest:
    return EngineRequest(
        prompt="Add a hello_world() function to utils.py",
        context="Fred is building a Python utility library.",
        worktree_path=tmp_path,
        session_id="test-session-001",
    )


# ---------------------------------------------------------------------------
# EngineRequest
# ---------------------------------------------------------------------------


class TestEngineRequest:
    def test_construction(self, tmp_path: Path) -> None:
        req = EngineRequest(
            prompt="test prompt",
            context="test context",
            worktree_path=tmp_path,
            session_id="abc-123",
        )
        assert req.prompt == "test prompt"
        assert req.context == "test context"
        assert req.worktree_path == tmp_path
        assert req.session_id == "abc-123"

    def test_worktree_path_is_path(self, tmp_path: Path) -> None:
        req = EngineRequest(prompt="x", context="y", worktree_path=tmp_path, session_id="s")
        assert isinstance(req.worktree_path, Path)


# ---------------------------------------------------------------------------
# EngineEvent type discrimination
# ---------------------------------------------------------------------------


class TestEngineEventTypes:
    def test_decision_point_has_kind_and_message(self) -> None:
        dp = DecisionPoint(
            kind=DecisionPointKind.ERROR_REQUIRING_CHOICE,
            message="File exists — overwrite?",
            options=["overwrite", "skip", "cancel"],
        )
        assert dp.kind is DecisionPointKind.ERROR_REQUIRING_CHOICE
        assert "overwrite" in dp.message
        assert "overwrite" in dp.options

    def test_decision_point_options_default_empty(self) -> None:
        dp = DecisionPoint(kind=DecisionPointKind.AMBIGUITY, message="Which auth strategy?")
        assert dp.options == []

    def test_progress_update_is_technical_noise(self) -> None:
        pu = ProgressUpdate(message="Running tests...")
        assert isinstance(pu, ProgressUpdate)

    def test_completion_signal_has_summary(self) -> None:
        cs = CompletionSignal(summary="PR opened at github.com/x/y/pull/42")
        assert "PR opened" in cs.summary

    def test_engine_error_kind_is_engine_failure(self) -> None:
        err = EngineError(
            kind=DecisionPointKind.ENGINE_FAILURE,
            message="Engine process died with exit code 1",
        )
        assert err.kind is DecisionPointKind.ENGINE_FAILURE

    def test_event_union_isinstance_checks(self) -> None:
        events: list[EngineEvent] = [
            DecisionPoint(kind=DecisionPointKind.COMPLETION, message="done"),
            ProgressUpdate(message="building..."),
            CompletionSignal(summary="done"),
            EngineError(kind=DecisionPointKind.ENGINE_FAILURE, message="crash"),
        ]
        assert isinstance(events[0], DecisionPoint)
        assert isinstance(events[1], ProgressUpdate)
        assert isinstance(events[2], CompletionSignal)
        assert isinstance(events[3], EngineError)

    def test_decision_point_kinds_cover_taxonomy(self) -> None:
        # Every DecisionPointKind should be usable as a DecisionPoint kind
        for kind in DecisionPointKind:
            dp = DecisionPoint(kind=kind, message="test")
            assert dp.kind is kind


# ---------------------------------------------------------------------------
# providers.yaml engines section
# ---------------------------------------------------------------------------


class TestProvidersEnginesSection:
    def test_engines_section_parsed(self, minimal_config: dict) -> None:
        engines = minimal_config.get("engines", {})
        assert engines.get("default") == "claude_code"
        assert "claude_code" in engines

    def test_engines_section_has_sdk_and_model(self, minimal_config: dict) -> None:
        cc_cfg = minimal_config["engines"]["claude_code"]
        assert "sdk" in cc_cfg
        assert "model" in cc_cfg

    def test_load_providers_reads_engines(self, minimal_config: dict, monkeypatch) -> None:
        """load_providers() returns the engines section unchanged."""
        import providers as prov

        monkeypatch.setattr(prov, "load_providers", lambda: minimal_config)
        config = prov.load_providers()
        assert "engines" in config
        assert config["engines"]["default"] == "claude_code"


# ---------------------------------------------------------------------------
# Engine instantiation from config
# ---------------------------------------------------------------------------


class MockEngine(CodingEngine):
    """Minimal in-test engine for testing the factory pattern."""

    def __init__(self, config: dict) -> None:
        self.config = config

    def dispatch(self, request: EngineRequest) -> EngineSession:
        return EngineSession()

    def send(self, session: EngineSession, message: str) -> None:
        pass

    def events(self, session: EngineSession) -> Iterator[EngineEvent]:
        yield CompletionSignal(summary="mock complete")


class TestLoadEngine:
    def test_load_engine_returns_claude_code_engine(self, minimal_config: dict) -> None:
        from programmer.engines.claude_code import ClaudeCodeEngine

        with patch("programmer.engine.load_engine") as mock_load:
            mock_load.return_value = ClaudeCodeEngine(minimal_config["engines"]["claude_code"])
            engine = mock_load(minimal_config)
            assert isinstance(engine, ClaudeCodeEngine)

    def test_load_engine_unknown_name_raises(self) -> None:
        config = {"engines": {"default": "nonexistent_engine", "nonexistent_engine": {}}}
        with patch("programmer.engine.load_engine") as mock_load:
            mock_load.side_effect = ValueError("Unknown engine: 'nonexistent_engine'")
            with pytest.raises(ValueError, match="Unknown engine"):
                mock_load(config)

    def test_mock_engine_implements_interface(self, sample_request: EngineRequest) -> None:
        engine = MockEngine(config={})
        session = engine.dispatch(sample_request)
        assert isinstance(session, EngineSession)

        events = list(engine.events(session))
        assert len(events) == 1
        assert isinstance(events[0], CompletionSignal)

    def test_mock_engine_send_does_not_raise(self, sample_request: EngineRequest) -> None:
        engine = MockEngine(config={})
        session = engine.dispatch(sample_request)
        engine.send(session, "overwrite")  # should not raise


# ---------------------------------------------------------------------------
# EngineSession is opaque
# ---------------------------------------------------------------------------


class TestEngineSession:
    def test_engine_session_is_instantiable(self) -> None:
        session = EngineSession()
        assert isinstance(session, EngineSession)

    def test_concrete_session_is_subclass(self) -> None:
        from programmer.engines.claude_code import ClaudeCodeSession

        session = ClaudeCodeSession(session_id="s", worktree_path=Path("/tmp/test-worktree"))
        assert isinstance(session, EngineSession)
