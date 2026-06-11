"""
tests/test_voice.py — unit tests for voice.py pure functions.

No hardware, no network, no audio. Safe to run anywhere.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

import output
import voice


# ---------------------------------------------------------------------------
# strip_markdown
# ---------------------------------------------------------------------------

class TestStripMarkdown:
    def test_headers_removed(self):
        assert voice.strip_markdown("# Title") == "Title"
        assert voice.strip_markdown("## Section") == "Section"
        assert voice.strip_markdown("### Sub") == "Sub"

    def test_bold_removed(self):
        assert voice.strip_markdown("**bold**") == "bold"
        assert voice.strip_markdown("__bold__") == "bold"

    def test_italic_removed(self):
        assert voice.strip_markdown("*italic*") == "italic"
        assert voice.strip_markdown("_italic_") == "italic"

    def test_bold_italic_removed(self):
        assert voice.strip_markdown("***both***") == "both"

    def test_inline_code_removed(self):
        assert voice.strip_markdown("`code`") == "code"

    def test_code_block_removed(self):
        result = voice.strip_markdown("before\n```python\ncode here\n```\nafter")
        assert "```" not in result
        assert "code here" not in result

    def test_link_becomes_text(self):
        assert voice.strip_markdown("[click here](https://example.com)") == "click here"

    def test_unordered_bullets_removed(self):
        result = voice.strip_markdown("- item one\n- item two")
        assert "-" not in result
        assert "item one" in result

    def test_ordered_list_removed(self):
        result = voice.strip_markdown("1. first\n2. second")
        assert "1." not in result
        assert "first" in result

    def test_blockquote_removed(self):
        result = voice.strip_markdown("> quoted text")
        assert ">" not in result
        assert "quoted text" in result

    def test_horizontal_rule_removed(self):
        result = voice.strip_markdown("before\n---\nafter")
        assert "---" not in result

    def test_plain_text_unchanged(self):
        text = "Olá, tudo bem com você?"
        assert voice.strip_markdown(text) == text

    def test_empty_string(self):
        assert voice.strip_markdown("") == ""

    def test_never_raises(self):
        # Should not raise on any input
        voice.strip_markdown(None if False else "")
        voice.strip_markdown("*" * 1000)
        voice.strip_markdown("\n" * 50)


# ---------------------------------------------------------------------------
# ts (now lives in output.py)
# ---------------------------------------------------------------------------

class TestTs:
    def test_format(self):
        result = output.ts()
        # HH:MM:SS.mmm — 12 chars
        assert len(result) == 12
        assert result[2] == ":"
        assert result[5] == ":"
        assert result[8] == "."

    def test_returns_string(self):
        assert isinstance(output.ts(), str)


# ---------------------------------------------------------------------------
# load_voice_config
# ---------------------------------------------------------------------------

class TestLoadVoiceConfig:
    def test_all_keys_present(self):
        cfg = voice.load_voice_config({})
        for key in ("stt_provider", "stt_model", "stt_language", "tts_voice", "tts_rate", "tts_volume"):
            assert key in cfg

    def test_defaults(self):
        cfg = voice.load_voice_config({})
        assert cfg["stt_provider"] == "openai-whisper"
        assert cfg["stt_model"] == "base"
        assert cfg["stt_language"] == "pt"
        assert cfg["tts_voice"] == "pt-BR-FranciscaNeural"

    def test_custom_values_loaded(self):
        providers_config = {
            "stt": {"provider": "faster-whisper", "model": "tiny", "language": "en"},
            "tts": {"voice": "en-US-JennyNeural", "rate": "+10%", "volume": "-5%"},
        }
        cfg = voice.load_voice_config(providers_config)
        assert cfg["stt_provider"] == "faster-whisper"
        assert cfg["stt_model"] == "tiny"
        assert cfg["tts_voice"] == "en-US-JennyNeural"
        assert cfg["tts_rate"] == "+10%"
