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

import agent  # noqa: E402
import connectors_setup  # noqa: E402
import core  # noqa: E402
import llm as prov  # noqa: E402
import log  # noqa: E402
import memory as mem  # noqa: E402
import output  # noqa: E402
import profiles  # noqa: E402
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
    parser.add_argument(
        "--session-id",
        default=None,
        metavar="SESSION_ID",
        help="Load a previous session as context for --text single-shot queries.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# PULSE
# ---------------------------------------------------------------------------


def run_init() -> None:
    script = _HERE.parent / "skills" / "agent-yana" / "scripts" / "init-sanctum.py"
    if not script.exists():
        print(f"[error] Script not found: {script}")
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


# _execute_tool and _call_with_tool_loop live in agent.py


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
    auto_greet: bool = False,
    profile_list: list[dict] | None = None,
    active_profile: str = "",
    sessions: list | None = None,
) -> None:
    """Run the Textual TUI conversation loop (text or voice mode)."""
    import threading

    from tui import run_tui

    _sessions = sessions if sessions is not None else []
    task_ref = [initial_task]

    # Graphiti context loads in the background — doesn't block TUI startup.
    # Injected into the system prompt on the FIRST turn where context is available.
    # _graphiti_injected is only set True when context was actually used — this way
    # early turns that fire before Graphiti finishes will retry on subsequent turns.
    _graphiti_ctx: list[str] = [""]
    _graphiti_injected = [False]

    if active_profile:

        def _load_graphiti() -> None:
            _graphiti_ctx[0] = mem.load_context_sync(timeout=30.0)

        threading.Thread(target=_load_graphiti, daemon=True, name="graphiti-ctx").start()

    def on_turn(msgs: list[dict]) -> str:
        # Inject Graphiti context once — on the first turn where it is available.
        # If Graphiti hasn't finished loading yet, skip silently and retry next turn.
        _sp = system_prompt
        if not _graphiti_injected[0] and active_profile:
            ctx = _graphiti_ctx[0]
            if ctx:
                _graphiti_injected[0] = True  # only mark injected when ctx is actually used
                _sp = system_prompt + "\n\n" + ctx
        reply = agent.call_with_tool_loop(
            msgs,
            _sp,
            tools,
            registry,
            providers_config,
            task=task_ref[0],
            text_mode=True,
            silent=True,
        )
        task_ref[0] = "conversation"
        return reply

    def make_tool_event_cb(tool_event_fn):
        """Return an on_turn variant that fires tool_event_fn for each tool call."""

        def _on_turn_with_events(msgs: list[dict]) -> str:
            _sp = system_prompt
            if not _graphiti_injected[0] and active_profile:
                ctx = _graphiti_ctx[0]
                if ctx:
                    _graphiti_injected[0] = True
                    _sp = system_prompt + "\n\n" + ctx
            reply = agent.call_with_tool_loop(
                msgs,
                _sp,
                tools,
                registry,
                providers_config,
                task=task_ref[0],
                text_mode=True,
                silent=True,
                on_tool_event=tool_event_fn,
            )
            task_ref[0] = "conversation"
            return reply

        return _on_turn_with_events

    def on_exit(final_messages: list[dict], chosen_session: str | None) -> None:
        session_id = chosen_session or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        session_date = session_id[:10]

        # Use the startup-time value — not sanctum_exists() which can falsely
        # trigger if PERSONA wasn't saved, causing duplicate profile creation.
        if initial_task == "first_breath":
            # First Breath: write sanctum first to extract the owner name from
            # OWNER_NAME, then register the owner + profile, then persist.
            try:
                written = sw.write_sanctum(
                    final_messages,
                    system_prompt,
                    is_first_breath=True,
                    config=providers_config,
                    session_date=session_date,
                    silent=True,
                )
            except KeyboardInterrupt:
                written = {}
            owner_id, profile_id = profiles.create_first_owner_and_profile(written)
            profiles.set_runtime_profile(profile_id)
            if written:
                store.save_sanctum_fields_sync(owner_id, profile_id, written)
            # Store the First Breath conversation — makes it visible in session browser
            mem.store_session_background(final_messages, session_id)
        else:
            # Regular session: store in Graphiti in background — TUI closes immediately
            mem.store_session_background(final_messages, session_id)

        # Generate session title + summary.
        # NOTE: store_session_background creates the DB record in a background thread,
        # so we must ensure the record exists before calling update_session_title_sync.
        # We call create_session_sync here first (idempotent — safe to call twice).
        if final_messages:
            import json as _json

            _profile_id = profiles.get_active_profile()
            if _profile_id:
                # Derive a plain-text fallback title from the last assistant message
                # so sessions always have visible text even when LLM title gen fails.
                _fallback_title = ""
                for _m in reversed(final_messages):
                    if _m.get("role") == "assistant":
                        _text = _m.get("content", "")
                        if isinstance(_text, list):
                            _text = " ".join(
                                b.get("text", "") for b in _text if isinstance(b, dict)
                            )
                        _fallback_title = str(_text).strip()[:120]
                        break

                store.create_session_sync(
                    session_id,
                    _profile_id,
                    datetime.now().isoformat(),
                    _fallback_title,
                    _json.dumps(final_messages, ensure_ascii=False),
                )
            try:
                title_data = sw.write_session_title(final_messages, config=providers_config)
                if title_data:
                    store.update_session_title_sync(
                        session_id,
                        title_data.get("title", ""),
                        title_data.get("summary"),
                    )
            except Exception:
                pass  # best-effort — LLM failure leaves fallback_title in place

    run_tui(
        _sessions,
        on_turn=on_turn,
        on_exit=on_exit,
        voice_mode=voice_mode,
        listen_fn=listen_fn,
        speak_fn=speak_fn,
        auto_greet=auto_greet,
        profiles=profile_list,
        active_profile_id=active_profile,
        make_tool_event_cb=make_tool_event_cb,
    )


def run_conversation() -> None:
    providers_config = prov.load_providers()
    voice_cfg = v.load_voice_config()
    tools = [*prov.CONNECTOR_TOOLS, prov.RUN_CODE_TOOL]

    output.configure(voice_mode=False)

    # Profile selection — runtime, not persisted.
    # 0 profiles → First Breath. 1 profile → auto-select. N → pick first (future: selection UI).
    profile_list = profiles.list_profiles()
    if profile_list:
        profiles.set_runtime_profile(profile_list[0]["id"])

    # Build registry after profile is set — connectors are profile-scoped
    registry = connectors_setup.build_registry()

    # State detection: route based on identity state, not CLI flags.
    active_profile = profiles.get_active_profile()
    sanctum_fields: dict = {}
    if active_profile:
        owner_id = profiles.owner_id_from_profile(active_profile)
        sanctum_fields = store.load_sanctum_fields_sync(owner_id, active_profile)

    has_sanctum = bool(sanctum_fields.get("persona"))
    is_first_breath = not profile_list and not has_sanctum

    sessions = core.list_sessions() if (profile_list or has_sanctum) else []

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
        auto_greet=is_first_breath,
        profile_list=profile_list,
        active_profile=active_profile,
        sessions=sessions,
    )


def run_single_shot(message: str, session_id: str | None = None) -> None:
    """Send one message, print the reply, exit — no session log, no sanctum write.

    Loads the active profile and sanctum fields so YANA has full identity context.
    If session_id is given, prepends that session's messages as conversation history.
    """
    providers_config = prov.load_providers()

    # Profile loading — same as run_conversation so YANA has identity context
    profile_list = profiles.list_profiles()
    if profile_list:
        profiles.set_runtime_profile(profile_list[0]["id"])

    registry = connectors_setup.build_registry()
    tools = [*prov.CONNECTOR_TOOLS, prov.RUN_CODE_TOOL]

    active_profile = profiles.get_active_profile()
    sanctum_fields: dict = {}
    if active_profile:
        owner_id = profiles.owner_id_from_profile(active_profile)
        sanctum_fields = store.load_sanctum_fields_sync(owner_id, active_profile)

    system_prompt = core.load_system_prompt(
        voice_mode=False, registry=registry, _sanctum_fields=sanctum_fields
    )

    # Optionally seed conversation history from a previous session
    messages: list[dict] = []
    if session_id:
        messages = core.load_session_messages(session_id)

    messages.append({"role": "user", "content": message})

    agent.call_with_tool_loop(
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

    # Always write DEBUG-level logs to yana-debug.log beside this script.
    # This captures Textual errors, exceptions, and TUI lifecycle events
    # even when the terminal clears them before they can be read.
    _log_path = _HERE / "yana-debug.log"
    try:
        from logging.handlers import RotatingFileHandler

        _fh = RotatingFileHandler(
            _log_path,
            maxBytes=2 * 1024 * 1024,  # 2 MB
            backupCount=2,
            encoding="utf-8",
        )
        _fh.setLevel(logging.DEBUG)
        _fh.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logging.getLogger().addHandler(_fh)
    except Exception:
        pass  # Never block startup over a log file

    # Suppress known shutdown-race noise on the console (still captured in yana-debug.log).
    # - neo4j.notifications: schema warnings for properties that don't exist yet (empty graph)
    # - graphiti_core: asyncio teardown tasks that fail after the event loop closes
    # - asyncio: 'Task exception was never retrieved' / 'Event loop is closed' from
    #   httpx connection-pool cleanup tasks spawned by Graphiti's client.close() —
    #   both variants are expected and carry no actionable signal for the user.
    if not args.verbose:
        logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
        logging.getLogger("graphiti_core").setLevel(logging.CRITICAL)
        logging.getLogger("asyncio").setLevel(logging.CRITICAL)

    if args.init:
        run_init()
        return

    if args.programmer:
        from programmer.mode import run_programmer_mode

        providers_config = prov.load_providers()
        voice_cfg = v.load_voice_config()

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
        run_single_shot(args.text, session_id=args.session_id)
        return

    run_conversation()


if __name__ == "__main__":
    main()
