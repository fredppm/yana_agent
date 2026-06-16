"""
tests/test_llm.py — unit tests for llm.py pure logic.

No network, no API keys. Config is built from env vars via monkeypatch.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import llm as providers


def _env(**kwargs):
    """Context manager: set env vars for the duration of the test."""
    return patch.dict("os.environ", kwargs)


# ---------------------------------------------------------------------------
# load_providers
# ---------------------------------------------------------------------------


class TestLoadProviders:
    def test_reads_litellm_url_from_env(self):
        with _env(LITELLM_URL="http://myhost:9000"):
            cfg = providers.load_providers()
        assert cfg["litellm_url"] == "http://myhost:9000"

    def test_defaults_litellm_url(self):
        with patch.dict("os.environ", {}, clear=False):
            cfg = providers.load_providers()
        assert cfg["litellm_url"] == "http://127.0.0.1:4000"

    def test_reads_model_from_env(self):
        with _env(YANA_MODEL_CONVERSATION="bedrock-claude-sonnet"):
            cfg = providers.load_providers()
        assert cfg["models"]["conversation"] == "bedrock-claude-sonnet"

    def test_model_falls_back_to_default(self):
        with patch.dict("os.environ", {"YANA_MODEL_CONVERSATION": ""}, clear=False):
            cfg = providers.load_providers()
        # Empty string → env var present but empty; os.environ.get returns ""
        # which is falsy, so the fallback kicks in during resolve_model, not load_providers
        assert "conversation" in cfg["models"]

    def test_stt_config_from_env(self):
        with _env(STT_PROVIDER="openai-whisper", STT_MODEL="base", STT_LANGUAGE="en"):
            cfg = providers.load_providers()
        assert cfg["stt"]["provider"] == "openai-whisper"
        assert cfg["stt"]["model"] == "base"
        assert cfg["stt"]["language"] == "en"

    def test_tts_config_from_env(self):
        with _env(TTS_VOICE="en-US-JennyNeural", TTS_RATE="+10%"):
            cfg = providers.load_providers()
        assert cfg["tts"]["voice"] == "en-US-JennyNeural"
        assert cfg["tts"]["rate"] == "+10%"


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------


class TestResolveModel:
    def test_returns_litellm_provider(self):
        with _env(YANA_MODEL_CONVERSATION="bedrock-claude-sonnet"):
            provider, model = providers.resolve_model("conversation")
        assert provider == "litellm"
        assert model == "bedrock-claude-sonnet"

    def test_conversation_fast_uses_own_env(self):
        with _env(YANA_MODEL_CONVERSATION_FAST="bedrock-claude-haiku"):
            _, model = providers.resolve_model("conversation_fast")
        assert model == "bedrock-claude-haiku"

    def test_first_breath_uses_own_env(self):
        with _env(YANA_MODEL_FIRST_BREATH="bedrock-claude-opus"):
            _, model = providers.resolve_model("first_breath")
        assert model == "bedrock-claude-opus"

    def test_unknown_task_falls_back_to_conversation(self):
        with _env(YANA_MODEL_CONVERSATION="bedrock-claude-sonnet"):
            _, model = providers.resolve_model("nonexistent_task")
        assert model == "bedrock-claude-sonnet"

    def test_config_dict_takes_precedence_over_env(self):
        cfg = {"models": {"conversation": "explicit-model"}}
        with _env(YANA_MODEL_CONVERSATION="env-model"):
            _, model = providers.resolve_model("conversation", cfg)
        assert model == "explicit-model"

    def test_empty_models_falls_back_to_hardcoded_default(self):
        _, model = providers.resolve_model("conversation", {"models": {}})
        assert model == providers._FALLBACK_MODEL


# ---------------------------------------------------------------------------
# _auto_task
# ---------------------------------------------------------------------------


class TestAutoTask:
    def _msgs(self, last: str, count: int = 1) -> list:
        msgs = [{"role": "user", "content": f"msg {i}"} for i in range(count - 1)]
        msgs.append({"role": "user", "content": last})
        return msgs

    def test_short_message_short_history_downgrades(self):
        msgs = self._msgs("oi", count=2)
        assert providers._auto_task(msgs, "conversation") == "conversation_fast"

    def test_long_message_stays_conversation(self):
        msgs = self._msgs("x" * 200, count=2)
        assert providers._auto_task(msgs, "conversation") == "conversation"

    def test_short_message_long_history_stays_conversation(self):
        msgs = self._msgs("oi", count=8)
        assert providers._auto_task(msgs, "conversation") == "conversation"

    def test_boundary_120_chars_stays_conversation(self):
        msgs = self._msgs("x" * 120, count=2)
        assert providers._auto_task(msgs, "conversation") == "conversation"

    def test_boundary_119_chars_downgrades(self):
        msgs = self._msgs("x" * 119, count=2)
        assert providers._auto_task(msgs, "conversation") == "conversation_fast"

    def test_boundary_6_turns_downgrades(self):
        msgs = self._msgs("oi", count=6)
        assert providers._auto_task(msgs, "conversation") == "conversation_fast"

    def test_boundary_7_turns_stays_conversation(self):
        msgs = self._msgs("oi", count=7)
        assert providers._auto_task(msgs, "conversation") == "conversation"

    def test_non_conversation_task_unchanged(self):
        msgs = self._msgs("oi", count=1)
        assert providers._auto_task(msgs, "pulse_scheduled") == "pulse_scheduled"
        assert providers._auto_task(msgs, "first_breath") == "first_breath"

    def test_empty_messages_does_not_raise(self):
        assert providers._auto_task([], "conversation") == "conversation_fast"
