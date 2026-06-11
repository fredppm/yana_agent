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

import core
import providers as prov
import sanctum_writer as sw
import voice as v


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="YANA — You Are Not Alone",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--text", action="store_true", help="Text mode (no voice I/O)")
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
    print(f"[PULSE] task={task}")
    reply = prov.call_llm(
        messages, system_prompt, task="pulse_scheduled", stream=True, config=providers_config
    )

    # Save headless session log
    messages.append({"role": "assistant", "content": reply})
    core.save_session_log(messages, session_id=f"pulse-{task}-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}")


# ---------------------------------------------------------------------------
# Conversation loop
# ---------------------------------------------------------------------------

def run_conversation(text_mode: bool) -> None:
    providers_config = prov.load_providers()
    voice_cfg = v.load_voice_config(providers_config)

    if not core.sanctum_exists():
        print()
        print("=" * 60)
        print("  Sanctum não encontrado.")
        print("  Execute `python main.py --init` para inicializar.")
        print("  Depois, YANA conduzirá o First Breath por voz.")
        print("=" * 60)
        print()

    system_prompt = core.load_system_prompt()
    session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    messages: list[dict] = []

    # Determine task type for routing
    task = "first_breath" if not core.sanctum_exists() else "conversation"

    # Greeting
    greeting = "Oi, estou ouvindo." if not text_mode else ""
    if greeting and not text_mode:
        print(f"\nYANA: {greeting}")
        v.speak(greeting, **_tts_kwargs(voice_cfg))

    print("\n--- YANA (Ctrl+C para sair) ---\n")

    try:
        while True:
            # --- Input ---
            if text_mode:
                try:
                    user_input = input("Você: ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
            else:
                print("Você: ", end="", flush=True)
                try:
                    user_input = v.listen(
                        provider=voice_cfg["stt_provider"],
                        model_name=voice_cfg["stt_model"],
                        language=voice_cfg["stt_language"],
                    )
                except KeyboardInterrupt:
                    break
                print(user_input)

            if not user_input:
                continue

            messages.append({"role": "user", "content": user_input})

            # --- LLM call ---
            print("YANA: [pensando...]", end="\r", flush=True)
            print("YANA: " + " " * 14, end="\r", flush=True)  # clear thinking indicator
            print("YANA: ", end="", flush=True)
            reply = prov.call_llm(
                messages, system_prompt, task=task, stream=True, config=providers_config
            )
            messages.append({"role": "assistant", "content": reply})

            # After first exchange, task becomes regular conversation
            task = "conversation"

            # --- TTS ---
            if not text_mode:
                v.speak(reply, **_tts_kwargs(voice_cfg))

            print()

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
    print(f"[sessão: {session_id}]")


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

    if args.init:
        run_init()
        return

    if args.headless is not None:
        task = args.headless if args.headless != "trigger" else "trigger"
        run_pulse(task, source=args.source, event=args.event, payload=args.payload)
        return

    run_conversation(text_mode=args.text)


if __name__ == "__main__":
    main()
