"""
tests/test_providers.py — unit tests for providers.py pure logic.

No network, no API keys, no file I/O. Config is passed as dicts.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

import providers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _config(routing: dict | None = None, extra_providers: dict | None = None) -> dict:
    """Build a minimal providers config dict."""
    base_providers = {
        "anthropic": {
            "api_key_env": "ANTHROPIC_API_KEY",
            "models": {
                "fast": "claude-haiku-4-5",
                "default": "claude-sonnet-4-6",
                "powerful": "claude-opus-4-6",
            },
        },
        "bedrock": {
            "region": "us-east-1",
            "models": {
                "fast": "us.anthropic.claude-haiku",
                "default": "us.anthropic.claude-sonnet",
            },
        },
    }
    if extra_providers:
        base_providers.update(extra_providers)

    base_routing = {
        "conversation": "default",
        "conversation_fast": "fast",
        "pulse_scheduled": "fast",
        "first_breath": "powerful",
    }
    if routing:
        base_routing.update(routing)

    return {"llm": {"providers": base_providers, "routing": base_routing}}


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------

class TestResolveModel:
    def test_conversation_resolves_to_default(self):
        provider, model = providers.resolve_model("conversation", _config())
        assert provider == "anthropic"
        assert model == "claude-sonnet-4-6"

    def test_fast_task_resolves_to_fast_model(self):
        provider, model = providers.resolve_model("conversation_fast", _config())
        assert provider == "anthropic"
        assert model == "claude-haiku-4-5"

    def test_explicit_provider_routing(self):
        # routing: "conversation: bedrock:default" should pick bedrock's default model
        cfg = _config(routing={"conversation": "bedrock:default"})
        provider, model = providers.resolve_model("conversation", cfg)
        assert provider == "bedrock"
        assert model == "us.anthropic.claude-sonnet"

    def test_explicit_provider_fast_routing(self):
        cfg = _config(routing={"pulse_scheduled": "bedrock:fast"})
        provider, model = providers.resolve_model("pulse_scheduled", cfg)
        assert provider == "bedrock"
        assert model == "us.anthropic.claude-haiku"

    def test_unknown_task_falls_back_to_conversation(self):
        # Unknown task → falls back to "conversation" routing → default tier
        provider, model = providers.resolve_model("nonexistent_task", _config())
        assert provider == "anthropic"
        assert model == "claude-sonnet-4-6"

    def test_first_breath_resolves_to_powerful(self):
        provider, model = providers.resolve_model("first_breath", _config())
        assert provider == "anthropic"
        assert model == "claude-opus-4-6"

    def test_raises_if_unresolvable(self):
        import pytest
        # Config with no models at all
        empty_cfg = {"llm": {"providers": {}, "routing": {}}}
        with pytest.raises(ValueError):
            providers.resolve_model("conversation", empty_cfg)

    def test_provider_order_wins(self):
        # When two providers define the same tier, the first one in yaml order wins
        # (dicts are insertion-ordered in Python 3.7+)
        cfg = _config()
        provider, _ = providers.resolve_model("conversation_fast", cfg)
        # "anthropic" is listed before "bedrock" in our fixture → anthropic wins
        assert provider == "anthropic"


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
        long = "x" * 200
        msgs = self._msgs(long, count=2)
        assert providers._auto_task(msgs, "conversation") == "conversation"

    def test_short_message_long_history_stays_conversation(self):
        msgs = self._msgs("oi", count=8)  # > 6 turns
        assert providers._auto_task(msgs, "conversation") == "conversation"

    def test_boundary_120_chars_stays_conversation(self):
        # Exactly 120 chars — condition is < 120, so this should NOT downgrade
        msg = "x" * 120
        msgs = self._msgs(msg, count=2)
        assert providers._auto_task(msgs, "conversation") == "conversation"

    def test_boundary_119_chars_downgrades(self):
        msg = "x" * 119
        msgs = self._msgs(msg, count=2)
        assert providers._auto_task(msgs, "conversation") == "conversation_fast"

    def test_boundary_6_turns_stays(self):
        # Exactly 6 msgs — condition is <= 6, so this SHOULD downgrade
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
        result = providers._auto_task([], "conversation")
        # Empty history — last message is "" which is < 120, but count is 0 ≤ 6
        assert result == "conversation_fast"
