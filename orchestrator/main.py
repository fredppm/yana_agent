"""
main.py — YANA Orchestrator entry point.

Usage:
  python main.py                    # voice mode (default)
  python main.py --text             # text mode (no mic/speaker)
  python main.py --init             # initialise sanctum and exit
  python main.py --headless         # full PULSE run (no interaction)
  python main.py --headless:memory  # PULSE memory curation only
  python main.py --headless:price-watch
  python main.py --headless:email-digest
  python main.py --headless:agenda-review
  python main.py --headless:trigger --source garmin --event stress_high
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import subprocess
import sys
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
import providers as prov  # noqa: E402
import sanctum_writer as sw  # noqa: E402
import voice as v  # noqa: E402

# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="YANA — You Are Not Alone",
        formatter_class=argparse.RawTextHelpFormatter,
    )

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
# Sanctum init
# ---------------------------------------------------------------------------


def run_init() -> None:
    script = _HERE.parent / "skills" / "agent-yana" / "scripts" / "init-sanctum.py"
    if not script.exists():
        print(f"[erro] Script não encontrado: {script}")
        sys.exit(1)
    result = subprocess.run([sys.executable, str(script), "--json"], capture_output=False)
    sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# PULSE headless mode
# ---------------------------------------------------------------------------


def run_pulse(task: str, source: str = "", event: str = "", payload: str = "{}") -> None:
    pulse_cfg = core.load_pulse_config()

    if core.is_quiet_hours(pulse_cfg):
        # Triggered tasks may ignore quiet hours based on config
        if task == "trigger":
            src_cfg = pulse_cfg.get("triggers", {}).get(source, {})
            if src_cfg.get("respect_quiet_hours", True):
                print("[PULSE] Quiet hours — skipping.")
                return
        else:
            print("[PULSE] Quiet hours — skipping.")
            return

    system_prompt = core.load_system_prompt()
    providers_config = prov.load_providers()

    if task == "trigger":
        user_msg = (
            f"[PULSE TRIGGER] source={source} event={event} payload={payload}\n"
            "Execute the matching trigger handler from your PULSE instructions."
        )
    else:
        task_map = {
            "full": "Execute all enabled scheduled PULSE tasks in priority order.",
            "memory": "Execute the Memory Curation PULSE task only.",
            "price-watch": "Execute the Price Watch PULSE task only.",
            "email-digest": "Execute the Email Digest PULSE task only.",
            "agenda-review": "Execute the Agenda Review PULSE task only.",
        }
        user_msg = task_map.get(task, f"Execute PULSE task: {task}")

    messages = [{"role": "user", "content": user_msg}]
    log.pulse_start(task)
    reply = prov.call_llm(
        messages, system_prompt, task="pulse_scheduled", stream=True, config=providers_config
    )

    # Save headless session log
    messages.append({"role": "assistant", "content": reply})
    core.save_session_log(
        messages, session_id=f"pulse-{task}-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    )


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
        return json.dumps({"ok": False, "error": result.error})

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
# Conversation loop
# ---------------------------------------------------------------------------


def run_conversation(text_mode: bool) -> None:
    providers_config = prov.load_providers()
    voice_cfg = v.load_voice_config(providers_config)

    # Build connector registry and inject manifest into system prompt
    registry = connectors_setup.build_registry()
    tools = prov.CONNECTOR_TOOLS

    if not core.sanctum_exists():
        log.warn("\nSanctum não encontrado.")
        log.warn("Execute `python main.py --init` para inicializar.")
        log.warn("Depois, YANA conduzirá o First Breath por voz.\n")

    system_prompt = core.load_system_prompt(voice_mode=not text_mode, registry=registry)
    session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    messages: list[dict] = []

    # Determine task type for routing
    task = "first_breath" if not core.sanctum_exists() else "conversation"

    # Greeting
    greeting = "Oi, estou ouvindo." if not text_mode else ""
    if greeting and not text_mode:
        log.yana_prefix(v.ts())
        log.console.print(greeting)
        v.speak(greeting, **_tts_kwargs(voice_cfg))

    log.separator()

    try:
        while True:
            # --- Input ---
            if text_mode:
                try:
                    log.user_prompt(v.ts())
                    user_input = input("").strip()
                except (EOFError, KeyboardInterrupt):
                    break
            else:
                log.user_prompt(v.ts())
                try:
                    user_input = v.listen(
                        provider=voice_cfg["stt_provider"],
                        model_name=voice_cfg["stt_model"],
                        language=voice_cfg["stt_language"],
                    )
                except KeyboardInterrupt:
                    break
                log.console.print(user_input)

            if not user_input:
                continue

            messages.append({"role": "user", "content": user_input})

            # --- LLM call (with connector tool loop) ---
            log.yana_thinking(v.ts())
            reply = _call_with_tool_loop(
                messages, system_prompt, tools, registry, providers_config,
                task=task, text_mode=text_mode, clear_line=True,
            )
            messages.append({"role": "assistant", "content": reply})

            # After first exchange, task becomes regular conversation
            task = "conversation"

            # --- TTS ---
            if not text_mode:
                v.speak(reply, **_tts_kwargs(voice_cfg))

            log.console.print()

    except KeyboardInterrupt:
        pass

    if not messages:
        return

    # Save raw session log
    session_date = session_id[:10]  # YYYY-MM-DD
    core.save_session_log(messages, session_id)

    # Write sanctum files
    is_first_breath = task == "first_breath" or not core.sanctum_exists()
    # If first exchange was first_breath and we flipped task, detect via session length
    # heuristic: if sanctum BOND.md is still a template (has placeholders), it's first breath
    bond = core.sanctum_path() / "BOND.md"
    if bond.exists() and "{" in bond.read_text(encoding="utf-8"):
        is_first_breath = True

    sw.write_sanctum(
        messages,
        system_prompt,
        is_first_breath=is_first_breath,
        config=providers_config,
        session_date=session_date,
    )
    log.session_end(session_id)


def run_single_shot(message: str) -> None:
    """Send one message, print the reply, exit — no session log, no sanctum write."""
    providers_config = prov.load_providers()
    registry = connectors_setup.build_registry()
    tools = prov.CONNECTOR_TOOLS
    system_prompt = core.load_system_prompt(voice_mode=False, registry=registry)

    messages = [{"role": "user", "content": message}]
    _call_with_tool_loop(
        messages, system_prompt, tools, registry, providers_config,
        task="conversation", text_mode=True,
    )
    log.console.print()


def _tts_kwargs(cfg: dict) -> dict:
    return {
        "voice": cfg["tts_voice"],
        "rate": cfg["tts_rate"],
        "volume": cfg["tts_volume"],
    }


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
