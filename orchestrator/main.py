"""
main.py — YANA Orchestrator entry point.

Usage:
  python main.py           # voice mode (default)
  python main.py --text    # text mode (no mic/speaker)
  python main.py --pulse   # PULSE run (autonomous tasks)
"""

from __future__ import annotations

import argparse
from datetime import datetime
import io
from pathlib import Path
import sys
import time

# Force UTF-8 I/O on Windows to handle accented characters
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    if sys.stdin and hasattr(sys.stdin, "buffer"):
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Bootstrap — ensure project root is on sys.path
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))


# ---------------------------------------------------------------------------
# Imports (after path fix)
# ---------------------------------------------------------------------------

import core  # noqa: E402
import output  # noqa: E402
import providers as prov  # noqa: E402
import sanctum_writer as sw  # noqa: E402
from strings import t  # noqa: E402
import voice as v  # noqa: E402


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YANA — You Are Not Alone")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--text",  action="store_true", help="Text mode (no voice I/O)")
    mode.add_argument("--pulse", action="store_true", help="PULSE run (autonomous tasks)")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# PULSE
# ---------------------------------------------------------------------------

def run_pulse() -> None:
    output.configure(voice_mode=False)

    if core.is_quiet_hours():
        output.status("PULSE — quiet hours, skipping.")
        return

    system_prompt = core.load_system_prompt()
    providers_config = prov.load_providers()

    msg = "Execute all enabled scheduled PULSE tasks in priority order."
    messages = [{"role": "user", "content": msg}]

    output.status("PULSE starting...")
    reply = prov.call_llm(
        messages, system_prompt, task="pulse_scheduled", stream=True,
        on_token=output.stream_token, config=providers_config,
    )
    print()  # newline after stream
    messages.append({"role": "assistant", "content": reply})
    session_id = f"pulse-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    core.save_session_log(messages, session_id)
    output.status(f"PULSE done — log: {session_id}")


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

def run_conversation(text_mode: bool) -> None:
    providers_config = prov.load_providers()
    voice_cfg = v.load_voice_config(providers_config)

    # Configure the output channel for this session
    speak_fn = None
    if not text_mode:
        _cfg = voice_cfg
        def _speak(text: str) -> None:
            v.speak(text, voice=_cfg["tts_voice"], rate=_cfg["tts_rate"], volume=_cfg["tts_volume"])
        speak_fn = _speak
    output.configure(voice_mode=not text_mode, speak_fn=speak_fn)

    if not core.sanctum_exists():
        output.setup_warning(
            t("sanctum_missing"),
            hint="Execute: python ../skills/agent-yana/scripts/init-sanctum.py . ../skills/agent-yana",
        )

    system_prompt = core.load_system_prompt()
    session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    messages: list[dict] = []
    task = "first_breath" if not core.sanctum_exists() else "conversation"

    if not text_mode:
        greeting = t("greeting")
        print(f"{output.yana_label()}{greeting}")
        output.say(greeting)

    output.announce(t("banner"))

    try:
        while True:
            if text_mode:
                try:
                    user_input = input(f"{t('user_label')}: ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
            else:
                print(output.user_label(), end="", flush=True)
                try:
                    _t0 = time.monotonic()
                    user_input = v.listen(
                        provider=voice_cfg["stt_provider"],
                        model_name=voice_cfg["stt_model"],
                        language=voice_cfg["stt_language"],
                    )
                    _stt_ms = int((time.monotonic() - _t0) * 1000)
                    print(f"{user_input}  [{_stt_ms}ms STT]")
                except KeyboardInterrupt:
                    break

            if not user_input:
                continue

            messages.append({"role": "user", "content": user_input})

            print(output.yana_label(), end="", flush=True)
            _t0 = time.monotonic()
            reply = prov.call_llm(
                messages, system_prompt, task=task, stream=True,
                on_token=output.stream_token, config=providers_config,
            )
            _llm_ms = int((time.monotonic() - _t0) * 1000)
            messages.append({"role": "assistant", "content": reply})
            task = "conversation"

            _tts_ms = output.after_stream(reply)
            if not text_mode:
                output.timing(f"LLM {_llm_ms}ms | TTS {_tts_ms}ms" + " " * 10)

            print()

    except KeyboardInterrupt:
        pass

    if not messages:
        return

    session_date = session_id[:10]
    core.save_session_log(messages, session_id)

    bond = core.sanctum_path() / "BOND.md"
    is_first_breath = (
        not core.sanctum_exists()
        or (bond.exists() and "{" in bond.read_text(encoding="utf-8"))
    )

    try:
        sw.write_sanctum(
            messages, system_prompt,
            is_first_breath=is_first_breath,
            config=providers_config,
            session_date=session_date,
        )
    except KeyboardInterrupt:
        output.warn("sanctum not updated — raw log saved.")

    output.status(f"session: {session_id}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    if args.pulse:
        run_pulse()
    else:
        run_conversation(text_mode=args.text)


if __name__ == "__main__":
    main()
