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
from collections.abc import Callable
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
import memory as mem  # noqa: E402
import output  # noqa: E402
import providers as prov  # noqa: E402
import sanctum_writer as sw  # noqa: E402
import store  # noqa: E402
import voice as v  # noqa: E402

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YANA — You Are Not Alone")

    # Operation mode — mutually exclusive
    op = parser.add_mutually_exclusive_group()
    op.add_argument("--init", action="store_true", help="Initialise sanctum and exit")
    op.add_argument(
        "--programmer",
        action="store_true",
        help="Programmer mode — YANA as coding co-pilot.",
    )

    # I/O mode — combinable with any operation
    parser.add_argument(
        "--text",
        nargs="?",
        const=True,
        default=False,
        metavar="MESSAGE",
        help="Text mode. Without MESSAGE: interactive loop. With MESSAGE: single-shot query and exit.",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Voice interaction (spoken input/output).",
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
    mem.store_session_background(messages, session_id)
    output.status(f"PULSE done — session: {session_id}")


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
    silent: bool = False,
) -> str:
    """
    Run one conversation turn handling any connector tool calls.

    *messages* must already include the latest user message.
    Returns the final text reply after all tool calls are resolved.

    silent=True: skip all terminal output (used by TUI mode — the caller
    renders the reply itself).
    """
    work = list(messages)
    _text_mode = text_mode

    while True:
        text, tool_uses, raw_content = prov.call_llm_with_tools(
            work, system_prompt, tools, task=task, config=providers_config
        )

        if not tool_uses:
            if not silent:
                # Final text response — optionally clear a pending "thinking" line
                if clear_line:
                    log.console.print(" " * 60, end="\r")
                    clear_line = False  # only clear once
                log.yana_prefix(v.ts())
                if text:
                    log.yana_response(text, markdown=_text_mode)
            return text or ""

        # Print any thinking text that preceded the tool calls
        if text and not silent:
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
            if not silent:
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


def _run_tui_conversation(
    system_prompt: str,
    providers_config: dict,
    registry,
    tools: list[dict],
    initial_task: str,
    voice_mode: bool = False,
    listen_fn: Callable[[], str] | None = None,
    speak_fn: Callable[[str], None] | None = None,
    greeting: str | None = None,
    profiles: list[dict] | None = None,
    active_profile: str = "",
    sessions: list | None = None,
) -> None:
    """Run the Textual TUI conversation loop (text or voice mode)."""
    from tui import run_tui

    _sessions = sessions if sessions is not None else []
    task_ref = [initial_task]

    def on_turn(msgs: list[dict]) -> str:
        reply = _call_with_tool_loop(
            msgs,
            system_prompt,
            tools,
            registry,
            providers_config,
            task=task_ref[0],
            text_mode=True,
            silent=True,
        )
        task_ref[0] = "conversation"
        return reply

    def on_exit(final_messages: list[dict], chosen_session: str | None) -> None:
        session_id = chosen_session or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        session_date = session_id[:10]

        is_first_breath = not core.sanctum_exists()

        if is_first_breath:
            # First Breath: write sanctum files synchronously, then register profile
            try:
                sw.write_sanctum(
                    final_messages,
                    system_prompt,
                    is_first_breath=True,
                    config=providers_config,
                    session_date=session_date,
                    silent=True,
                )
            except KeyboardInterrupt:
                pass
            # Register the new profile in providers.yaml (CAP-4)
            _register_first_profile()
        else:
            # Regular session: store in Graphiti in background — TUI closes immediately
            mem.store_session_background(final_messages, session_id)

    run_tui(
        _sessions,
        on_turn=on_turn,
        on_exit=on_exit,
        voice_mode=voice_mode,
        listen_fn=listen_fn,
        speak_fn=speak_fn,
        greeting=greeting,
        profiles=profiles,
        active_profile_id=active_profile,
    )


def _register_first_profile() -> None:
    """
    After a successful First Breath, register the owner profile in providers.yaml.
    Called from on_exit when is_first_breath is True and no profiles existed.
    """
    if core.profiles_exist():
        return  # Already registered

    import re

    active = core.get_active_profile()
    owner_id: str | None = None
    if active:
        candidate = core.owner_id_from_profile(active)
        fields = store.load_sanctum_fields_sync(candidate, active)
        persona = fields.get("persona", "")
        if persona:
            m = re.search(
                r"(?:#|YANA)[^\n\S]*(?:YANA[^\n—]*)?[—\-]\s*([A-Za-záéíóúàèìòùãõâêîôûñç]+)",
                persona,
            )
            if m:
                owner_id = m.group(1).lower().strip()
    if not owner_id:
        import getpass

        try:
            owner_id = getpass.getuser().lower()
        except Exception:
            owner_id = "user"

    profile_id = f"{owner_id}::pessoal"
    label = f"{owner_id.capitalize()} — Pessoal"
    core.add_profile(profile_id, label)


def run_conversation() -> None:
    providers_config = prov.load_providers()
    voice_cfg = v.load_voice_config(providers_config)

    registry = connectors_setup.build_registry()
    tools = prov.CONNECTOR_TOOLS

    output.configure(voice_mode=False)

    # State detection (CAP-6): route based on identity state, not CLI flags.
    # Load sanctum fields once — shared by state detection and system prompt assembly.
    active_profile = core.get_active_profile()
    sanctum_fields: dict = {}
    if active_profile:
        owner_id = core.owner_id_from_profile(active_profile)
        sanctum_fields = store.load_sanctum_fields_sync(owner_id, active_profile)

    profiles = core.list_profiles()
    has_sanctum = bool(sanctum_fields.get("persona"))
    is_first_breath = not profiles and not has_sanctum

    sessions = core.list_sessions() if (profiles or has_sanctum) else []

    system_prompt = core.load_system_prompt(registry=registry, _sanctum_fields=sanctum_fields)
    task = "first_breath" if is_first_breath else "conversation"

    # Voice closures — passed to TUI so ctrl+v can activate them at any time
    _cfg = voice_cfg

    def _listen() -> str:
        return v.listen(
            provider=_cfg["stt_provider"],
            model_name=_cfg["stt_model"],
            language=_cfg["stt_language"],
        )

    def _speak(text: str) -> None:
        v.speak(
            text,
            voice=_cfg["tts_voice"],
            rate=_cfg["tts_rate"],
            volume=_cfg["tts_volume"],
        )

    _run_tui_conversation(
        system_prompt,
        providers_config,
        registry,
        tools,
        task,
        voice_mode=False,  # TUI starts in text mode; user toggles with ctrl+v
        listen_fn=_listen,
        speak_fn=_speak,
        profiles=profiles,
        active_profile=active_profile,
        sessions=sessions,
    )


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
    # Neo4j emits schema warnings for properties that don't exist yet (empty graph).
    # These are expected on first run and add no signal — suppress unless verbose.
    if not args.verbose:
        logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    if args.init:
        run_init()
        return

    # Initialize PostgreSQL schema on every startup (idempotent — CREATE TABLE IF NOT EXISTS)
    store.init_schema_sync()

    if args.programmer:
        from programmer.mode import run_programmer_mode

        providers_config = prov.load_providers()
        voice_cfg = v.load_voice_config(providers_config)

        speak_fn = None
        if args.voice:
            _cfg = voice_cfg

            def _speak(text: str) -> None:
                v.speak(
                    text, voice=_cfg["tts_voice"], rate=_cfg["tts_rate"], volume=_cfg["tts_volume"]
                )

            speak_fn = _speak

        run_programmer_mode(
            text_flag=bool(args.text),
            voice_flag=args.voice,
            speak_fn=speak_fn,
            providers_config=providers_config,
        )
        return

    if args.headless is not None:
        task = args.headless if args.headless != "trigger" else "trigger"
        run_pulse(task, source=args.source, event=args.event, payload=args.payload)
        return

    if isinstance(args.text, str):
        run_single_shot(args.text)
        return

    run_conversation()


if __name__ == "__main__":
    main()
