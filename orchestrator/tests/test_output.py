"""
tests/test_output.py — unit tests for output.py.

No TTS, no audio. speak_fn is mocked via configure().
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import output


def _reset():
    """Reset output state between tests."""
    output.configure(voice_mode=False, speak_fn=None, level="info", color=False)


# ---------------------------------------------------------------------------
# configure + say
# ---------------------------------------------------------------------------


class TestConfigure:
    def setup_method(self):
        _reset()

    def test_say_calls_speak_fn_in_voice_mode(self):
        mock_speak = MagicMock()
        output.configure(voice_mode=True, speak_fn=mock_speak, color=False)
        output.say("hello")
        mock_speak.assert_called_once_with("hello")

    def test_say_does_not_call_speak_in_text_mode(self):
        mock_speak = MagicMock()
        output.configure(voice_mode=False, speak_fn=mock_speak, color=False)
        output.say("hello")
        mock_speak.assert_not_called()

    def test_say_returns_zero_in_text_mode(self):
        output.configure(voice_mode=False, color=False)
        assert output.say("hello") == 0

    def test_say_returns_positive_ms_in_voice_mode(self):
        import time

        def slow_speak(text):
            time.sleep(0.05)  # 50ms — safely above Windows timer tick (~15.6ms)

        output.configure(voice_mode=True, speak_fn=slow_speak, color=False)
        ms = output.say("hello")
        assert ms > 0  # TTS ran, so some time elapsed

    def test_reconfigure_replaces_speak_fn(self):
        mock1 = MagicMock()
        mock2 = MagicMock()
        output.configure(voice_mode=True, speak_fn=mock1, color=False)
        output.say("first")
        output.configure(voice_mode=True, speak_fn=mock2, color=False)
        output.say("second")
        mock1.assert_called_once()
        mock2.assert_called_once()


# ---------------------------------------------------------------------------
# after_stream
# ---------------------------------------------------------------------------


class TestAfterStream:
    def setup_method(self):
        _reset()

    def test_calls_tts_in_voice_mode(self, capsys):
        mock_speak = MagicMock()
        output.configure(voice_mode=True, speak_fn=mock_speak, color=False)
        output.after_stream("full reply")
        mock_speak.assert_called_once_with("full reply")

    def test_prints_newline(self, capsys):
        output.configure(voice_mode=False, color=False)
        output.after_stream("text")
        captured = capsys.readouterr()
        assert "\n" in captured.out

    def test_returns_zero_in_text_mode(self):
        output.configure(voice_mode=False, color=False)
        assert output.after_stream("text") == 0


# ---------------------------------------------------------------------------
# status / debug / warn / error — level filtering
# ---------------------------------------------------------------------------


class TestLevels:
    def setup_method(self):
        _reset()

    def test_status_shown_at_info(self, capsys):
        output.configure(voice_mode=False, level="info", color=False)
        output.status("test message")
        assert "test message" in capsys.readouterr().out

    def test_status_hidden_at_quiet(self, capsys):
        output.configure(voice_mode=False, level="quiet", color=False)
        output.status("test message")
        assert capsys.readouterr().out == ""

    def test_debug_hidden_at_info(self, capsys):
        output.configure(voice_mode=False, level="info", color=False)
        output.debug("debug message")
        assert capsys.readouterr().out == ""

    def test_debug_shown_at_debug(self, capsys):
        output.configure(voice_mode=False, level="debug", color=False)
        output.debug("debug message")
        assert "debug message" in capsys.readouterr().out

    def test_warn_always_shown_at_quiet(self, capsys):
        output.configure(voice_mode=False, level="quiet", color=False)
        output.warn("something wrong")
        assert "something wrong" in capsys.readouterr().out

    def test_warn_always_shown_at_info(self, capsys):
        output.configure(voice_mode=False, level="info", color=False)
        output.warn("something wrong")
        assert "something wrong" in capsys.readouterr().out

    def test_error_always_shown_at_quiet(self, capsys):
        output.configure(voice_mode=False, level="quiet", color=False)
        output.error("fatal error")
        assert "fatal error" in capsys.readouterr().out

    def test_timing_hidden_at_quiet(self, capsys):
        output.configure(voice_mode=False, level="quiet", color=False)
        output.timing("LLM 100ms | TTS 200ms")
        assert capsys.readouterr().out == ""

    def test_timing_shown_at_info(self, capsys):
        output.configure(voice_mode=False, level="info", color=False)
        output.timing("LLM 100ms | TTS 200ms")
        assert "LLM 100ms" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# stream_token
# ---------------------------------------------------------------------------


class TestStreamToken:
    def test_prints_without_newline(self, capsys):
        output.stream_token("a")
        output.stream_token("b")
        output.stream_token("c")
        captured = capsys.readouterr()
        assert captured.out == "abc"


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


class TestLabels:
    def setup_method(self):
        _reset()

    def test_yana_label_contains_yana(self):
        output.configure(voice_mode=False, color=False)
        assert "YANA" in output.yana_label()

    def test_user_label_contains_user_string(self):
        import strings

        output.configure(voice_mode=False, color=False)
        assert strings.t("user_label") in output.user_label()

    def test_labels_contain_timestamp(self):
        output.configure(voice_mode=False, color=False)
        # Timestamp format: HH:MM:SS.mmm — check for colons
        assert ":" in output.yana_label()
        assert ":" in output.user_label()
