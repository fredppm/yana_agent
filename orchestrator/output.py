"""
output.py — communication layer.

Single place that knows the active mode (voice vs text) and log level.
All user-facing output and operational status go through here.

Levels (set via configure or YANA_LOG_LEVEL env var):
  debug  — everything: timing, model loading, internal steps
  info   — normal: status + warnings + errors  (default)
  quiet  — minimal: warnings + errors only
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Callable, Optional

import strings


# ---------------------------------------------------------------------------
# ANSI colours — subtle palette, easy on the eyes
# ---------------------------------------------------------------------------

_DIM    = "\033[2m"
_CYAN   = "\033[36m"
_BLUE   = "\033[94m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_RESET  = "\033[0m"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_voice_mode: bool = False
_speak_fn: Optional[Callable[[str], None]] = None
_level: str = "info"   # "debug" | "info" | "quiet"
_color: bool = True


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def configure(
    voice_mode: bool,
    speak_fn: Optional[Callable[[str], None]] = None,
    level: Optional[str] = None,
    color: Optional[bool] = None,
) -> None:
    """
    Call once at startup.

    speak_fn: callable(text) that synthesises and plays audio.
              None = text mode, no TTS.
    level:    "debug" | "info" | "quiet". Falls back to YANA_LOG_LEVEL env var,
              then "info".
    color:    True/False. Auto-detected from terminal if not set.
    """
    global _voice_mode, _speak_fn, _level, _color
    _voice_mode = voice_mode
    _speak_fn = speak_fn
    _level = (level or os.environ.get("YANA_LOG_LEVEL", "info")).lower()
    if color is not None:
        _color = color
    else:
        import sys
        _color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def ts() -> str:
    """Current timestamp with milliseconds: HH:MM:SS.mmm"""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _c(code: str, text: str) -> str:
    """Wrap text in ANSI code if colour is enabled."""
    if not _color:
        return text
    return f"{code}{text}{_RESET}"


# ---------------------------------------------------------------------------
# Output channels
# ---------------------------------------------------------------------------

def stream_token(char: str) -> None:
    """Print a single streamed LLM token — never spoken mid-stream."""
    print(char, end="", flush=True)


def say(text: str) -> int:
    """
    Speak text via TTS if voice mode.
    Does NOT print — caller handles display.
    Returns TTS duration in ms (0 in text mode).
    """
    return _do_tts(text)


def after_stream(full_text: str) -> int:
    """
    Called after streaming tokens complete.
    Adds the newline after the token stream, then TTS if voice mode.
    Returns TTS duration in ms.
    """
    print()
    return _do_tts(full_text)


def yana_label() -> str:
    """Return the coloured 'YANA: ' label for use before streaming begins."""
    return _c(_BLUE, f"[{ts()}] YANA: ")


def user_label() -> str:
    """Return the dimmed user input label for use before STT begins."""
    return _c(_DIM, f"[{ts()}] {strings.t('user_label')}: ")


def announce(msg: str) -> None:
    """Session-level banner — always shown regardless of log level."""
    print(f"\n{msg}\n", flush=True)


def setup_warning(msg: str, hint: str = "") -> None:
    """Framed setup/configuration warning — always shown."""
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  {msg}")
    if hint:
        print(f"  {hint}")
    print(f"{sep}\n")


def status(msg: str) -> None:
    """
    Operational info — timestamped, dim.
    Shown at 'info' level and above. Hidden in 'quiet' mode.
    """
    if _level == "quiet":
        return
    print(_c(_DIM, f"[{ts()}] {msg}"), flush=True)


def debug(msg: str) -> None:
    """
    Verbose/internal info — shown only at 'debug' level.
    Use for model loading, timing internals, parsing steps.
    """
    if _level != "debug":
        return
    print(_c(_DIM, f"[{ts()}] {msg}"), flush=True)


def timing(msg: str) -> None:
    """LLM/TTS timing line — shown at 'info' and 'debug', hidden in 'quiet'."""
    if _level == "quiet":
        return
    print(_c(_CYAN, f"[{ts()}] {msg}"), flush=True)


def warn(msg: str) -> None:
    """Warning or recoverable error — always shown, yellow."""
    print(_c(_YELLOW, f"  [{strings.t('warn_prefix')}: {msg}]"))


def error(msg: str) -> None:
    """Non-recoverable error — always shown, red."""
    print(_c(_RED, f"  [{strings.t('error_prefix')}: {msg}]"))


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _do_tts(text: str) -> int:
    """Run TTS and return elapsed ms, or 0 if voice mode is off."""
    if _voice_mode and _speak_fn:
        t0 = time.monotonic()
        _speak_fn(text)
        return int((time.monotonic() - t0) * 1000)
    return 0
