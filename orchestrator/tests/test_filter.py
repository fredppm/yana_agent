"""
test_filter.py — Story 1.4: decision-point filter tests.

No real engine calls — engine.events() is mocked to yield controlled sequences.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from programmer.decision_points import DecisionPointKind
from programmer.engine import (
    CodingEngine,
    CompletionSignal,
    DecisionPoint,
    EngineError,
    EngineSession,
    ProgressUpdate,
)
from programmer.filter import _SHOW_OUTPUT_COMMANDS, EventFilter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_filter(
    events: list,
    speak_fn=None,
    listen_fn=None,
    input_answers: list[str] | None = None,
) -> EventFilter:
    """Build an EventFilter with a mocked engine yielding the given events."""
    engine = MagicMock(spec=CodingEngine)
    session = MagicMock(spec=EngineSession)
    engine.events.return_value = iter(events)

    f = EventFilter(engine=engine, session=session, speak_fn=speak_fn, listen_fn=listen_fn)

    if input_answers is not None:
        # Patch input() for text-mode answer collection
        f._input_answers = iter(input_answers)

    return f


# ---------------------------------------------------------------------------
# DecisionPoint surfaces to Fred
# ---------------------------------------------------------------------------


class TestDecisionPointSurfaces:
    def test_decision_point_printed(self, capsys) -> None:
        f = _make_filter(
            events=[
                DecisionPoint(kind=DecisionPointKind.ERROR_REQUIRING_CHOICE, message="Overwrite?"),
                CompletionSignal(summary="done"),
            ],
        )
        with patch("builtins.input", return_value="yes"):
            f.run()

        out = capsys.readouterr().out
        assert "Overwrite?" in out

    def test_decision_point_with_options_shows_options(self, capsys) -> None:
        f = _make_filter(
            events=[
                DecisionPoint(
                    kind=DecisionPointKind.ERROR_REQUIRING_CHOICE,
                    message="Overwrite?",
                    options=["yes", "no", "skip"],
                ),
                CompletionSignal(summary="done"),
            ],
        )
        with patch("builtins.input", return_value="yes"):
            f.run()

        out = capsys.readouterr().out
        assert "yes" in out
        assert "no" in out
        assert "skip" in out

    def test_decision_point_spoken_in_voice_mode(self) -> None:
        speak = MagicMock()
        f = _make_filter(
            events=[
                DecisionPoint(kind=DecisionPointKind.AMBIGUITY, message="Which auth strategy?"),
                CompletionSignal(summary="done"),
            ],
            speak_fn=speak,
        )
        with patch("builtins.input", return_value="JWT"):
            f.run()

        speak.assert_any_call("Which auth strategy?")

    def test_fred_answer_forwarded_verbatim(self) -> None:
        engine = MagicMock(spec=CodingEngine)
        session = MagicMock(spec=EngineSession)
        engine.events.return_value = iter(
            [
                DecisionPoint(kind=DecisionPointKind.PERMISSION_REQUEST, message="Push branch?"),
                CompletionSignal(summary="done"),
            ]
        )
        f = EventFilter(engine=engine, session=session)

        with patch("builtins.input", return_value="yes, push it"):
            f.run()

        engine.send.assert_called_once_with(session, "yes, push it")

    def test_yana_does_not_modify_answer(self) -> None:
        engine = MagicMock(spec=CodingEngine)
        session = MagicMock(spec=EngineSession)
        engine.events.return_value = iter(
            [
                DecisionPoint(kind=DecisionPointKind.AMBIGUITY, message="Which file?"),
                CompletionSignal(summary="done"),
            ]
        )
        f = EventFilter(engine=engine, session=session)

        original_answer = "  utils.py  "  # has leading/trailing spaces
        with patch("builtins.input", return_value=original_answer):
            f.run()

        # send() is called with .strip() of the input (consistent with _collect_answer)
        engine.send.assert_called_once_with(session, original_answer.strip())

    def test_multiple_decision_points_all_answered(self) -> None:
        engine = MagicMock(spec=CodingEngine)
        session = MagicMock(spec=EngineSession)
        engine.events.return_value = iter(
            [
                DecisionPoint(kind=DecisionPointKind.AMBIGUITY, message="Which file?"),
                DecisionPoint(kind=DecisionPointKind.PERMISSION_REQUEST, message="Confirm push?"),
                CompletionSignal(summary="done"),
            ]
        )
        f = EventFilter(engine=engine, session=session)

        with patch("builtins.input", side_effect=["utils.py", "yes"]):
            f.run()

        assert engine.send.call_count == 2
        engine.send.assert_any_call(session, "utils.py")
        engine.send.assert_any_call(session, "yes")

    def test_listen_fn_used_in_voice_mode(self) -> None:
        engine = MagicMock(spec=CodingEngine)
        session = MagicMock(spec=EngineSession)
        engine.events.return_value = iter(
            [
                DecisionPoint(kind=DecisionPointKind.AMBIGUITY, message="Which file?"),
                CompletionSignal(summary="done"),
            ]
        )
        listen = MagicMock(return_value="utils.py")
        f = EventFilter(engine=engine, session=session, listen_fn=listen)

        f.run()  # no input() needed — listen_fn is used

        listen.assert_called_once()
        engine.send.assert_called_once_with(session, "utils.py")


# ---------------------------------------------------------------------------
# ProgressUpdate suppressed
# ---------------------------------------------------------------------------


class TestProgressUpdateSuppressed:
    def test_progress_not_printed(self, capsys) -> None:
        f = _make_filter(
            events=[
                ProgressUpdate(message="Running tests..."),
                ProgressUpdate(message="Compiling..."),
                CompletionSignal(summary="done"),
            ],
        )
        f.run()

        out = capsys.readouterr().out
        assert "Running tests" not in out
        assert "Compiling" not in out

    def test_progress_buffered(self) -> None:
        f = _make_filter(
            events=[
                ProgressUpdate(message="Running tests..."),
                ProgressUpdate(message="All tests passed."),
                CompletionSignal(summary="done"),
            ],
        )
        f.run()

        buffered = f.get_buffered_output()
        assert "Running tests" in buffered
        assert "All tests passed" in buffered

    def test_engine_send_not_called_for_progress(self) -> None:
        engine = MagicMock(spec=CodingEngine)
        session = MagicMock(spec=EngineSession)
        engine.events.return_value = iter(
            [
                ProgressUpdate(message="build log line 1"),
                ProgressUpdate(message="build log line 2"),
                CompletionSignal(summary="done"),
            ]
        )
        f = EventFilter(engine=engine, session=session)
        f.run()

        engine.send.assert_not_called()


# ---------------------------------------------------------------------------
# CompletionSignal formatted
# ---------------------------------------------------------------------------


class TestCompletionSignalFormatted:
    def test_completion_surfaced_with_summary(self, capsys) -> None:
        f = _make_filter(
            events=[CompletionSignal(summary="PR opened at github.com/x/y/pull/42")],
        )
        f.run()

        out = capsys.readouterr().out
        assert "Engine finished" in out
        assert "PR opened" in out

    def test_completion_asks_whats_next(self, capsys) -> None:
        f = _make_filter(
            events=[CompletionSignal(summary="Task complete.")],
        )
        f.run()

        out = capsys.readouterr().out
        assert "What's next?" in out

    def test_completion_spoken_in_voice_mode(self) -> None:
        speak = MagicMock()
        f = _make_filter(
            events=[CompletionSignal(summary="PR opened.")],
            speak_fn=speak,
        )
        f.run()

        spoken = " ".join(str(c) for c in speak.call_args_list)
        assert "finished" in spoken.lower() or "PR opened" in spoken

    def test_loop_stops_after_completion(self) -> None:
        engine = MagicMock(spec=CodingEngine)
        session = MagicMock(spec=EngineSession)
        # events after CompletionSignal should never be consumed
        engine.events.return_value = iter(
            [
                CompletionSignal(summary="done"),
                DecisionPoint(kind=DecisionPointKind.AMBIGUITY, message="SHOULD NOT APPEAR"),
            ]
        )
        f = EventFilter(engine=engine, session=session)
        f.run()

        # send() was never called — the DecisionPoint after completion was ignored
        engine.send.assert_not_called()


# ---------------------------------------------------------------------------
# EngineError surfaces
# ---------------------------------------------------------------------------


class TestEngineErrorSurfaces:
    def test_engine_error_printed(self, capsys) -> None:
        f = _make_filter(
            events=[
                EngineError(
                    kind=DecisionPointKind.ENGINE_FAILURE,
                    message="Engine process died with exit code 1",
                )
            ],
        )
        f.run()

        out = capsys.readouterr().out
        assert "Engine process died" in out

    def test_engine_error_spoken(self) -> None:
        speak = MagicMock()
        f = _make_filter(
            events=[EngineError(kind=DecisionPointKind.ENGINE_FAILURE, message="SDK timeout")],
            speak_fn=speak,
        )
        f.run()

        speak.assert_called()
        spoken = " ".join(str(c) for c in speak.call_args_list)
        assert "SDK timeout" in spoken

    def test_loop_stops_after_error(self) -> None:
        engine = MagicMock(spec=CodingEngine)
        session = MagicMock(spec=EngineSession)
        engine.events.return_value = iter(
            [
                EngineError(kind=DecisionPointKind.ENGINE_FAILURE, message="crash"),
                DecisionPoint(kind=DecisionPointKind.AMBIGUITY, message="SHOULD NOT APPEAR"),
            ]
        )
        f = EventFilter(engine=engine, session=session)
        f.run()

        engine.send.assert_not_called()


# ---------------------------------------------------------------------------
# /show-output retrieves buffer
# ---------------------------------------------------------------------------


class TestShowOutput:
    def test_show_output_command_dumps_buffer(self, capsys) -> None:
        engine = MagicMock(spec=CodingEngine)
        session = MagicMock(spec=EngineSession)
        engine.events.return_value = iter(
            [
                ProgressUpdate(message="test line 1"),
                ProgressUpdate(message="test line 2"),
                DecisionPoint(kind=DecisionPointKind.AMBIGUITY, message="Which auth?"),
                CompletionSignal(summary="done"),
            ]
        )
        f = EventFilter(engine=engine, session=session)

        # First answer: /show-output → re-asks → second answer: JWT
        with patch("builtins.input", side_effect=["/show-output", "JWT"]):
            f.run()

        out = capsys.readouterr().out
        assert "test line 1" in out
        assert "test line 2" in out

    def test_after_show_output_question_is_re_asked(self, capsys) -> None:
        engine = MagicMock(spec=CodingEngine)
        session = MagicMock(spec=EngineSession)
        engine.events.return_value = iter(
            [
                DecisionPoint(kind=DecisionPointKind.AMBIGUITY, message="Which auth strategy?"),
                CompletionSignal(summary="done"),
            ]
        )
        f = EventFilter(engine=engine, session=session)

        with patch("builtins.input", side_effect=["/show-output", "JWT"]):
            f.run()

        out = capsys.readouterr().out
        # Question should appear twice (once before show-output, once after)
        assert out.count("Which auth strategy?") == 2

    def test_answer_after_show_output_forwarded_to_engine(self) -> None:
        engine = MagicMock(spec=CodingEngine)
        session = MagicMock(spec=EngineSession)
        engine.events.return_value = iter(
            [
                DecisionPoint(kind=DecisionPointKind.PERMISSION_REQUEST, message="Push?"),
                CompletionSignal(summary="done"),
            ]
        )
        f = EventFilter(engine=engine, session=session)

        with patch("builtins.input", side_effect=["/show-output", "yes"]):
            f.run()

        # Engine.send() called once with "yes", not with "/show-output"
        engine.send.assert_called_once_with(session, "yes")

    def test_get_buffered_output_returns_all_progress(self) -> None:
        f = _make_filter(
            events=[
                ProgressUpdate(message="line A"),
                ProgressUpdate(message="line B"),
                CompletionSignal(summary="done"),
            ],
        )
        f.run()

        buffered = f.get_buffered_output()
        assert "line A" in buffered
        assert "line B" in buffered

    def test_empty_buffer_message(self, capsys) -> None:
        engine = MagicMock(spec=CodingEngine)
        session = MagicMock(spec=EngineSession)
        engine.events.return_value = iter(
            [
                DecisionPoint(kind=DecisionPointKind.AMBIGUITY, message="Which auth?"),
                CompletionSignal(summary="done"),
            ]
        )
        f = EventFilter(engine=engine, session=session)

        with patch("builtins.input", side_effect=["/show-output", "JWT"]):
            f.run()

        out = capsys.readouterr().out
        # Buffer was empty when /show-output was issued
        assert "No engine output buffered yet" in out

    def test_all_show_output_command_variants_recognized(self, capsys) -> None:
        for cmd in _SHOW_OUTPUT_COMMANDS:
            engine = MagicMock(spec=CodingEngine)
            session = MagicMock(spec=EngineSession)
            engine.events.return_value = iter(
                [
                    DecisionPoint(kind=DecisionPointKind.AMBIGUITY, message="Q?"),
                    CompletionSignal(summary="done"),
                ]
            )
            f = EventFilter(engine=engine, session=session)

            with patch("builtins.input", side_effect=[cmd, "answer"]):
                f.run()

            # Question appeared twice — command was intercepted (not forwarded)
            out = capsys.readouterr().out
            assert out.count("Q?") == 2, f"Command {cmd!r} was not intercepted"
