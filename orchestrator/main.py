"""
main.py — YANA Orchestrator entry point.

Usage:
  python main.py           # voice mode (default)
  python main.py --text    # text mode (no mic/speaker)
  python main.py --pulse   # PULSE run (autonomous tasks)
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

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

import connectors_setup  # noqa: E402
import core  # noqa: E402
import log  # noqa: E402
import output  # noqa: E402
import providers as prov  # noqa: E402
import sanctum_writer as sw  # noqa: E402
import voice as v  # noqa: E402
from strings import t  # noqa: E402

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YANA — You Are Not Alone")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--text",
        nargs="?",
        const=True,
        default=False,
        metavar="MESSAGE",
        help="Text mode. Without MESSAGE: interactive loop. With MESSAGE: single-shot query and exit.",
    )
    mode.add_argument("--init", action="store_true", help="Initialise sanctum and exit")
    mode.add_argument(
        "--programmer",
        action="store_true",
        help="Programmer mode — YANA as coding co-pilot. Use with --text or --voice.",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Voice interaction for programmer mode (spoken input/output).",
    )

    # Headless / PULSE modes
    parser.add_argument(
        "--headless",
        nargs="?",
        const="full",
        metavar="TASK",
        help="PULSE run. TASK: full | memory | price-watch | email-digest | agenda-review",
    )
    parser.add_argument("--source", default="", help="Trigger source (with --headless:trigger)")
    parser.add_argument("--event", default="", help="Trigger event (with --headless:trigger)")
    parser.add_argument("--payload", default="{}", help="JSON payload for trigger events")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose debug logging")

    return parser.parse_args()


# ---------------------------------------------------------------------------
# PULSE
# ---------------------------------------------------------------------------


def run_init() -> None:
    script = _HERE.parent / "skills" / "agent-yana" / "scripts" / "init-sanctum.py"
    if not script.exists():
        print(f"[erro] Script não encontrado: {script}")
        sys.exit(1)
    result = subprocess.run([sys.executable, str(script), "--json"], capture_output=False)
    sys.exit(result.returncode)


def run_pulse(task: str = "full", source: str = "", event: str = "", payload: str = "{}") -> None:
    output.configure(voice_mode=False)

    pulse_cfg = core.load_pulse_config()

    if core.is_quiet_hours(pulse_cfg):
        # Triggered tasks may ignore quiet hours based on config
        if task == "trigger":
            src_cfg = pulse_cfg.get("triggers", {}).get(source, {})
            if src_cfg.get("respect_quiet_hours", True):
                output.status("PULSE — quiet hours, skipping.")
                return
        else:
            output.status("PULSE — quiet hours, skipping.")
            return

    system_prompt = core.load_system_prompt()
    providers_config = prov.load_providers()

    msg = "Execute all enabled scheduled PULSE tasks in priority order."
    messages = [{"role": "user", "content": msg}]

    output.status("PULSE starting...")
    reply = prov.call_llm(
        messages,
        system_prompt,
        task="pulse_scheduled",
        stream=True,
        on_token=output.stream_token,
        config=providers_config,
    )
    print()  # newline after stream
    messages.append({"role": "assistant", "content": reply})
    session_id = f"pulse-{task}-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    core.save_session_log(messages, session_id=session_id)
    output.status(f"PULSE done — log: {session_id}")


# ---------------------------------------------------------------------------
# Connector tool execution
# ---------------------------------------------------------------------------


def _execute_tool(tool_call: dict, registry) -> str:
    """Execute a single connector tool call and return the result as a JSON string."""
    name = tool_call["name"]
    inp = tool_call["input"]

    if name == "call_connector":
        result = registry.call(
            inp["instance_id"],
            inp["operation"],
            inp.get("params") or {},
        )
        if result.ok:
            return json.dumps({"ok": True, "data": result.data})
        payload: dict = {"ok": False, "error": result.error}
        if result.detail:
            payload["detail"] = result.detail
        return json.dumps(payload)

    if name == "get_connector_contract":
        try:
            contract = registry.load_contract(inp["instance_id"])
            return json.dumps(contract)
        except KeyError as exc:
            return json.dumps({"error": str(exc)})

    return json.dumps({"error": f"unknown tool: {name}"})


def _call_with_tool_loop(
    messages: list[dict],
    system_prompt: str,
    tools: list[dict],
    registry,
    providers_config: dict,
    task: str,
    text_mode: bool = True,
    clear_line: bool = False,
) -> str:
    """
    Run one conversation turn handling any connector tool calls.

    *messages* must already include the latest user message.
    Returns the final text reply after all tool calls are resolved.
    """
    work = list(messages)
    _text_mode = text_mode

    while True:
        text, tool_uses, raw_content = prov.call_llm_with_tools(
            work, system_prompt, tools, task=task, config=providers_config
        )

        if not tool_uses:
            # Final text response — optionally clear a pending "pensando" line, then reply
            if clear_line:
                log.console.print(" " * 60, end="\r")
                clear_line = False  # only clear once
            log.yana_prefix(v.ts())
            if text:
                log.yana_response(text, markdown=_text_mode)
            return text or ""

        # Print any thinking text that preceded the tool calls
        if text:
            log.console.print(text, end="")

        # Add assistant message (with tool_use blocks) to working history
        work.append({"role": "assistant", "content": raw_content})

        # Execute each tool and collect results
        tool_results = []
        for tc in tool_uses:
            result_str = _execute_tool(tc, registry)
            instance = tc["input"].get("instance_id", "")
            op = tc["input"].get("operation", tc["name"])
            try:
                _r = json.loads(result_str)
                _err = _r.get("error") if not _r.get("ok", True) else None
            except Exception:
                _err = None
            if _err:
                log.connector_err(v.ts(), instance, op, _err)
            else:
                log.connector_ok(v.ts(), instance, op)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": result_str,
                }
            )

        # Feed results back as a user message and loop
        work.append({"role": "user", "content": tool_results})


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


def run_conversation(text_mode: bool) -> None:
    providers_config = prov.load_providers()
    voice_cfg = v.load_voice_config(providers_config)

    # Build connector registry and inject manifest into system prompt
    registry = connectors_setup.build_registry()
    tools = prov.CONNECTOR_TOOLS

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
            hint="Execute: python main.py --init",
        )

    system_prompt = core.load_system_prompt(voice_mode=not text_mode, registry=registry)
    session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    messages: list[dict] = []
    task = "first_breath" if not core.sanctum_exists() else "conversation"

    # Greeting
    if not text_mode:
        greeting = t("greeting")
        log.yana_prefix(v.ts())
        log.console.print(greeting)
        v.speak(
            greeting,
            voice=voice_cfg["tts_voice"],
            rate=voice_cfg["tts_rate"],
            volume=voice_cfg["tts_volume"],
        )

    output.announce(t("banner"))

    try:
        while True:
            if text_mode:
                try:
                    log.user_prompt(v.ts())
                    user_input = input("").strip()
                except (EOFError, KeyboardInterrupt):
                    break
            else:
                log.user_prompt(v.ts())
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

            # --- LLM call (with connector tool loop) ---
            log.yana_thinking(v.ts())
            _t0 = time.monotonic()
            reply = _call_with_tool_loop(
                messages,
                system_prompt,
                tools,
                registry,
                providers_config,
                task=task,
                text_mode=text_mode,
                clear_line=True,
            )
            _llm_ms = int((time.monotonic() - _t0) * 1000)
            messages.append({"role": "assistant", "content": reply})
            task = "conversation"

            _tts_ms = output.after_stream(reply) if not text_mode else 0
            if not text_mode:
                output.timing(f"LLM {_llm_ms}ms | TTS {_tts_ms}ms" + " " * 10)

    except KeyboardInterrupt:
        pass

    if not messages:
        return

    session_date = session_id[:10]
    core.save_session_log(messages, session_id)

    bond = core.sanctum_path() / "BOND.md"
    is_first_breath = not core.sanctum_exists() or (
        bond.exists() and "{" in bond.read_text(encoding="utf-8")
    )
    log.session_end(session_id)

    try:
        sw.write_sanctum(
            messages,
            system_prompt,
            is_first_breath=is_first_breath,
            config=providers_config,
            session_date=session_date,
        )
    except KeyboardInterrupt:
        output.warn("sanctum not updated — raw log saved.")

    output.status(f"session: {session_id}")


def run_single_shot(message: str) -> None:
    """Send one message, print the reply, exit — no session log, no sanctum write."""
    providers_config = prov.load_providers()
    registry = connectors_setup.build_registry()
    tools = prov.CONNECTOR_TOOLS
    system_prompt = core.load_system_prompt(voice_mode=False, registry=registry)

    messages = [{"role": "user", "content": message}]
    _call_with_tool_loop(
        messages,
        system_prompt,
        tools,
        registry,
        providers_config,
        task="conversation",
        text_mode=True,
    )
    log.console.print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="[%(levelname)s] %(name)s: %(message)s",
    )

    if args.init:
        run_init()
        return

    if args.programmer:
        import core
        from programmer.mode import run_programmer_mode

        providers_config = prov.load_providers()
        voice_cfg = v.load_voice_config(providers_config)

        speak_fn = None
        if args.voice:
            _cfg = voice_cfg

            def _speak(text: str) -> None:
                v.speak(text, voice=_cfg["tts_voice"], rate=_cfg["tts_rate"], volume=_cfg["tts_volume"])

            speak_fn = _speak

        run_programmer_mode(
            text_flag=bool(args.text),
            voice_flag=args.voice,
            sanctum_path=core.sanctum_path(),
            speak_fn=speak_fn,
        )
        return

    if args.headless is not None:
        task = args.headless if args.headless != "trigger" else "trigger"
        run_pulse(task, source=args.source, event=args.event, payload=args.payload)
        return

    if isinstance(args.text, str):
        run_single_shot(args.text)
        return

    run_conversation(text_mode=bool(args.text))


if __name__ == "__main__":
    main()
