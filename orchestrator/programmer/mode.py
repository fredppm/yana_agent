"""
mode.py — YANA programmer mode activation and session loop.

Entry point: run_programmer_mode(). Called from main.py when --programmer is passed.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Interaction mode
# ---------------------------------------------------------------------------


class InteractionMode(Enum):
    TEXT = "text"
    VOICE = "voice"

    def label(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Sanctum context — loaded once at activation, passed to each dispatch
# ---------------------------------------------------------------------------


@dataclass
class SanctumContext:
    bond: str  # enduring truths about the owner

    @classmethod
    def load(cls) -> SanctumContext:
        """Load from PostgreSQL. Raises FileNotFoundError if sanctum not initialised."""
        import profiles
        import store

        active = profiles.get_active_profile()
        if not active:
            raise FileNotFoundError("No active profile — sanctum not initialised")
        owner_id = profiles.owner_id_from_profile(active)
        fields = store.load_sanctum_fields_sync(owner_id, active)
        if not fields.get("persona"):
            raise FileNotFoundError(
                "Sanctum not initialised — run YANA first to complete First Breath"
            )
        return cls(bond=fields.get("bond", ""))


# ---------------------------------------------------------------------------
# Mode persistence guard
# ---------------------------------------------------------------------------


def is_explicit_mode_switch(text: str) -> bool:
    """
    Return True if the input is an explicit mode-switch command.

    YANA only accepts a mode switch when Fred explicitly signals it.
    Unmarked input never triggers a switch — Design Principle 2.

    Recognised patterns (case-insensitive):
      /switch-mode voice
      /switch-mode text
      "switch to voice"
      "switch to text"
    """
    low = text.strip().lower()
    return low in {
        "/switch-mode voice",
        "/switch-mode text",
        "/switch-mode v",
        "/switch-mode t",
        "switch to voice",
        "switch to text",
    }


def parse_mode_switch(text: str) -> InteractionMode | None:
    """
    If text is an explicit mode-switch command, return the target InteractionMode.
    Returns None if not a mode-switch command.
    """
    low = text.strip().lower()
    if "voice" in low or low.endswith(" v"):
        return InteractionMode.VOICE
    if "text" in low or low.endswith(" t"):
        return InteractionMode.TEXT
    return None


# ---------------------------------------------------------------------------
# Programmer mode runner
# ---------------------------------------------------------------------------


def run_programmer_mode(
    text_flag: bool,
    voice_flag: bool,
    speak_fn: Callable[[str], None] | None = None,
    providers_config: dict | None = None,
) -> None:
    """
    Activate YANA programmer mode.

    text_flag:        True if --text was passed
    voice_flag:       True if --voice was passed
    speak_fn:         TTS callable for voice mode (None = text only)
    providers_config: providers.yaml dict (loaded from file if None)

    Hard stops:
      - Sanctum does not exist → print error, sys.exit(1)
      - Both text_flag and voice_flag → text takes precedence (unambiguous default)
    """
    import output
    from strings import t

    output.configure(voice_mode=False)  # text output during setup; reconfigured after mode chosen

    # --- Sanctum load (hard stop if missing) ---
    try:
        sanctum = SanctumContext.load()
    except FileNotFoundError as exc:
        print(f"  [{t('programmer_sanctum_missing')}]", file=sys.stderr)
        print(f"  [erro: {exc}]", file=sys.stderr)
        sys.exit(1)

    # --- Interaction mode selection ---
    mode = _resolve_mode(text_flag, voice_flag)

    # --- Reconfigure output for chosen mode ---
    if mode is InteractionMode.VOICE and speak_fn is not None:
        output.configure(voice_mode=True, speak_fn=speak_fn)
    else:
        output.configure(voice_mode=False)

    # --- Readiness signal ---
    ready_msg = t("programmer_ready", mode=mode.label())
    print(ready_msg, flush=True)
    if mode is InteractionMode.VOICE and speak_fn:
        speak_fn(ready_msg)

    # --- Session loop ---
    _session_loop(mode, sanctum, speak_fn, providers_config=providers_config)


def _resolve_mode(text_flag: bool, voice_flag: bool) -> InteractionMode:
    """
    Determine the interaction mode.

    Both set → text (unambiguous, text is the safe default).
    Neither set → ask Fred interactively.
    """
    from strings import t

    if text_flag:
        return InteractionMode.TEXT
    if voice_flag:
        return InteractionMode.VOICE

    # Ask Fred
    while True:
        choice = input(t("programmer_choose_mode")).strip().lower()
        if choice in ("v", "voice"):
            return InteractionMode.VOICE
        if choice in ("t", "text"):
            return InteractionMode.TEXT
        print(t("programmer_mode_invalid"))


def _session_loop(
    mode: InteractionMode,
    sanctum: SanctumContext,
    speak_fn: Callable[[str], None] | None,
    providers_config: dict | None = None,
) -> None:
    """
    Main programmer session loop.

    Tracks the last active DispatchResult so /end-session can clean up the worktree.
    """
    import output
    from strings import t

    current_mode = mode
    last_dispatch: object = None  # holds DispatchResult if a worktree needs cleanup

    def _end_session() -> None:
        """Cleanup worktree and signal session end."""
        from programmer.dispatcher import DispatchResult

        nonlocal last_dispatch
        if isinstance(last_dispatch, DispatchResult):
            wm = last_dispatch.worktree_manager
            if wm.exists():
                msg = wm.cleanup(force=True)
                print(msg, flush=True)
                if speak_fn:
                    speak_fn(msg)
        last_dispatch = None
        print(t("programmer_session_end"), flush=True)

    try:
        while True:
            try:
                user_input = input(f"{t('user_label')}: ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue

            # Explicit mode switch (Design Principle 2 — never infer)
            if is_explicit_mode_switch(user_input):
                new_mode = parse_mode_switch(user_input)
                if new_mode and new_mode is not current_mode:
                    current_mode = new_mode
                    if current_mode is InteractionMode.VOICE and speak_fn is not None:
                        output.configure(voice_mode=True, speak_fn=speak_fn)
                    else:
                        output.configure(voice_mode=False)
                    print(t("programmer_mode_switched", mode=current_mode.value), flush=True)
                continue

            # Session end — cleanup any active worktree then exit
            if user_input.lower() in ("/end-session", "encerra sessão", "encerra sessao"):
                _end_session()
                return

            last_dispatch = _handle_request(
                user_input,
                current_mode,
                sanctum,
                speak_fn=speak_fn,
                providers_config=providers_config,
            )

    except KeyboardInterrupt:
        # SIGTERM / Ctrl+C — preserve worktree (AC-2.1.6), just exit
        pass

    # Fell through (Ctrl+C or EOF) without explicit /end-session
    # Worktree preserved — not cleaned up (AC-2.1.6)
    print(t("programmer_session_end"), flush=True)


def _handle_request(
    request: str,
    mode: InteractionMode,
    sanctum: SanctumContext,
    speak_fn: Callable[[str], None] | None = None,
    providers_config: dict | None = None,
) -> object:
    """
    Create worktree, inject context, run engine interactively.

    Blocks until the engine session ends.
    Returns DispatchResult (for worktree tracking) or None on failure.
    """
    from programmer.dispatcher import (
        DispatchFailed,
        dispatch_request,
        new_session_id,
    )

    session_id = new_session_id()
    outcome = dispatch_request(
        enriched_prompt=request,
        sanctum=sanctum,
        session_id=session_id,
        config=providers_config,
    )

    if isinstance(outcome, DispatchFailed):
        print(f"\n[erro] {outcome.reason}", flush=True)
        if speak_fn:
            speak_fn(f"Could not dispatch request. {outcome.reason}")
        return None

    return outcome
