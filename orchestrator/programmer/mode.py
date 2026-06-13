"""
mode.py — YANA programmer mode activation and session loop.

Entry point: run_programmer_mode(). Called from main.py when --programmer is passed.

Story 1.1 scope: activation, mode selection, sanctum load, readiness signal.
Stories 1.2-1.4 will extend _handle_request() with clarification, routing, and filtering.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# ---------------------------------------------------------------------------
# Methodology definitions — loaded from YAML, never hardcoded
# ---------------------------------------------------------------------------

_METHODOLOGY_DIR = Path(__file__).parent / "methodologies"


@dataclass
class _MethodologyDef:
    name: str
    display_name: str
    triggers: list[str]  # lowercased exact-match phrases
    prompt: str  # dispatched verbatim to the engine


def _load_methodology_defs(repo_root: Path | None = None) -> list[_MethodologyDef]:
    """
    Load methodology definitions from YAML files.

    Bundled (programmer/methodologies/*.yaml) loaded first;
    project-specific ({repo_root}/.yana/methodologies/*.yaml) override by name.
    """
    defs: dict[str, _MethodologyDef] = {}
    for f in sorted(_METHODOLOGY_DIR.glob("*.yaml")):
        d = _parse_methodology_yaml(f)
        if d:
            defs[d.name] = d
    if repo_root is not None:
        project_dir = repo_root / ".yana" / "methodologies"
        if project_dir.exists():
            for f in sorted(project_dir.glob("*.yaml")):
                d = _parse_methodology_yaml(f)
                if d:
                    defs[d.name] = d
    return list(defs.values())


def _parse_methodology_yaml(path: Path) -> _MethodologyDef | None:
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        name = str(data.get("name", path.stem))
        return _MethodologyDef(
            name=name,
            display_name=str(data.get("display_name", name.upper())),
            triggers=[str(t).strip().lower() for t in data.get("triggers", [])],
            prompt=str(data.get("prompt", f"Run {name.upper()} in the worktree.")),
        )
    except Exception:
        return None


def _match_methodology(text: str, defs: list[_MethodologyDef]) -> _MethodologyDef | None:
    low = text.strip().lower()
    return next((d for d in defs if low in d.triggers), None)


def _worktree_has_files(path: Path) -> bool:
    return path.exists() and any(f for f in path.rglob("*") if f.is_file())


# ---------------------------------------------------------------------------
# Interaction mode
# ---------------------------------------------------------------------------


class InteractionMode(Enum):
    TEXT = "text"
    VOICE = "voice"

    def label(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Sanctum context — the YANA knowledge loaded at mode activation
# ---------------------------------------------------------------------------


@dataclass
class SanctumContext:
    """
    The subset of sanctum files relevant to programmer mode dispatch.

    Loaded once at activation; passed into every EngineRequest as context.
    """

    bond: str  # BOND.md — enduring truths about Fred
    memory: str  # MEMORY.md — current situations, open threads
    persona: str  # PERSONA.md — YANA's identity

    @classmethod
    def load(cls, sanctum_path: Path) -> SanctumContext:
        """
        Load BOND.md, MEMORY.md, PERSONA.md from the sanctum.

        Raises FileNotFoundError if sanctum_path does not exist.
        Missing individual files are replaced with empty strings
        (sanctum may be partially initialised).
        """
        if not sanctum_path.exists():
            raise FileNotFoundError(f"Sanctum not found at {sanctum_path}")

        def _read(fname: str) -> str:
            p = sanctum_path / fname
            return p.read_text(encoding="utf-8") if p.exists() else ""

        return cls(
            bond=_read("BOND.md"),
            memory=_read("MEMORY.md"),
            persona=_read("PERSONA.md"),
        )

    def as_context_string(self, max_tokens: int = 500) -> str:
        """
        Produce a condensed context string for EngineRequest.context.

        Concatenates bond + memory. persona is YANA's identity, not needed by
        the engine. Hard-truncates at max_tokens*4 chars as a rough proxy.
        """
        combined = ""
        if self.bond:
            combined += f"## Who Fred is (BOND)\n\n{self.bond}\n\n"
        if self.memory:
            combined += f"## Current context (MEMORY)\n\n{self.memory}\n"
        char_limit = max_tokens * 4
        return combined[:char_limit] if len(combined) > char_limit else combined


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
    sanctum_path: Path,
    speak_fn: Callable[[str], None] | None = None,
    providers_config: dict | None = None,
) -> None:
    """
    Activate YANA programmer mode.

    text_flag:        True if --text was passed
    voice_flag:       True if --voice was passed
    sanctum_path:     path to the sanctum directory (from core.sanctum_path())
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
    if not sanctum_path.exists():
        print(f"  [{t('programmer_sanctum_missing')}]", file=sys.stderr)
        sys.exit(1)

    try:
        sanctum = SanctumContext.load(sanctum_path)
    except FileNotFoundError as exc:
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
        print("Please type 'v' for voice or 't' for text.")


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
    method_defs = _load_methodology_defs()  # bundled defs, loaded once per session

    def _end_session() -> None:
        """AC-2.1.2: signal engine, cleanup worktree, output status."""
        from programmer.dispatcher import DispatchResult

        nonlocal last_dispatch
        if isinstance(last_dispatch, DispatchResult):
            wm = last_dispatch.worktree_manager
            if wm.exists():
                msg = wm.stop_and_cleanup(last_dispatch.session)
                print(msg, flush=True)
                if speak_fn:
                    speak_fn(msg)
        last_dispatch = None
        print(t("programmer_session_end"), flush=True)

    try:
        while True:
            try:
                user_input = input(f"[programmer/{current_mode.value}] ").strip()
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
                    print(f"Mode switched to {current_mode.value}.", flush=True)
                continue

            # Session end — cleanup any active worktree then exit
            if user_input.lower() in ("/end-session", "encerra sessão", "encerra sessao"):
                _end_session()
                return

            # Methodology routing — explicit trigger required (never inferred)
            method_def = _match_methodology(user_input, method_defs)
            if method_def:
                last_dispatch = _handle_methodology_request(
                    method_def,
                    sanctum,
                    speak_fn=speak_fn,
                    providers_config=providers_config,
                )
                continue

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
    """Returns the DispatchResult (for worktree tracking) or None."""
    """
    Handle a programmer request.

    Story 1.2: clarification gate — detect gaps, ask Fred, stop on no answer.
    Story 1.3: create worktree, dispatch to engine.
    Story 1.4: decision-point filter on engine events.
    """
    from strings import t

    from programmer.clarification import Cancelled, run_clarification_gate
    from programmer.dispatcher import (
        DispatchFailed,
        dispatch_request,
        new_session_id,
    )

    context = sanctum.as_context_string()

    # --- Clarification gate (Story 1.2) ---
    clarification = run_clarification_gate(
        request=request,
        context=context,
        speak_fn=speak_fn,
        listen_fn=None,
        config=providers_config,
    )

    if isinstance(clarification, Cancelled):
        msg = t("programmer_cancelled")
        print(f"\n{msg}", flush=True)
        if speak_fn:
            speak_fn(msg)
        return None

    # --- Dispatch to engine (Story 1.3) ---
    session_id = new_session_id()
    outcome = dispatch_request(
        enriched_prompt=clarification.enriched_prompt,
        sanctum=sanctum,
        session_id=session_id,
        config=providers_config,
    )

    if isinstance(outcome, DispatchFailed):
        print(f"\n[erro] {outcome.reason}", flush=True)
        if speak_fn:
            speak_fn(f"Could not dispatch request. {outcome.reason}")
        return None

    # AC-1.3.4: notify Fred of dispatch
    dispatch_msg = "Request sent to engine. I'll surface decisions that need you."
    print(f"\n{dispatch_msg}", flush=True)
    if speak_fn:
        speak_fn(dispatch_msg)

    # --- Event loop + decision-point filter (Story 1.4) ---
    status = _run_event_filter(outcome, speak_fn, listen_fn=None)

    # --- Post-filter lifecycle management (Story 2.1) ---
    _handle_post_filter(outcome, status, speak_fn)

    return outcome


def _run_event_filter(
    outcome: object,
    speak_fn: Callable[[str], None] | None,
    listen_fn: Callable[[], str] | None = None,
) -> object:
    """
    Run the decision-point filter on the active engine session.
    Returns FilterStatus.
    """
    from programmer.dispatcher import DispatchResult
    from programmer.filter import EventFilter

    if not isinstance(outcome, DispatchResult):
        return None

    event_filter = EventFilter(
        engine=outcome.engine,
        session=outcome.session,
        speak_fn=speak_fn,
        listen_fn=listen_fn,
    )
    return event_filter.run()


def _handle_post_filter(
    outcome: object,
    status: object,
    speak_fn: Callable[[str], None] | None,
) -> None:
    """
    Post-filter lifecycle: decide what to do with the worktree based on filter result.

    COMPLETED → offer cleanup or keep (worktree has the work; Fred may want to PR)
    ENGINE_ERROR → "Engine stopped unexpectedly. Worktree intact at {path}." Don't auto-cleanup.
    CANCELLED → "Cancel complete. Keep worktree or clean it up?"
    """
    from programmer.dispatcher import DispatchResult
    from programmer.filter import FilterStatus

    if not isinstance(outcome, DispatchResult) or status is None:
        return

    wm = outcome.worktree_manager

    if status is FilterStatus.ENGINE_ERROR:
        msg = (
            f"Engine stopped unexpectedly. Your worktree is intact at {wm.path}. "
            "Resume, inspect, or end session?"
        )
        print(f"\n[erro] {msg}", flush=True)
        if speak_fn:
            speak_fn(
                "Engine stopped unexpectedly. Your worktree is intact. Resume, inspect, or end session?"
            )
        # Do NOT auto-cleanup — Fred must explicitly ask (AC-2.1.4)

    elif status is FilterStatus.CANCELLED:
        print("\nCancel complete.", flush=True)
        choice = (
            input(f"Keep worktree at {wm.path} for inspection, or clean it up? [keep/clean] ")
            .strip()
            .lower()
        )
        if choice in ("clean", "c", "cleanup"):
            msg = wm.stop_and_cleanup(outcome.session)
            print(msg, flush=True)
            if speak_fn:
                speak_fn(msg)
        else:
            print(f"Worktree kept at {wm.path}.", flush=True)

    elif status is FilterStatus.COMPLETED:
        # Task finished normally — worktree contains the work
        # YANA does not auto-cleanup (Fred may want to inspect or PR from it)
        # Cleanup happens when Fred issues /end-session in the session loop
        pass


def _handle_methodology_request(
    method_def: object,
    sanctum: SanctumContext,
    speak_fn: Callable[[str], None] | None = None,
    providers_config: dict | None = None,
) -> object:
    """
    Handle a methodology mode request (Story 2.2).

    Dispatches the methodology prompt directly to the engine — no input
    collection in YANA. The engine handles all methodology-specific Q&A
    through the existing decision-point loop.
    Returns the DispatchResult (for worktree tracking) or None.
    """
    from programmer.dispatcher import (
        DispatchFailed,
        DispatchResult,
        dispatch_request,
        new_session_id,
    )
    from programmer.filter import FilterStatus

    if not isinstance(method_def, _MethodologyDef):
        return None

    # --- Dispatch directly — engine owns input collection (Design Principle 1) ---
    session_id = new_session_id()
    outcome = dispatch_request(
        enriched_prompt=method_def.prompt,
        sanctum=sanctum,
        session_id=session_id,
        config=providers_config,
    )

    if isinstance(outcome, DispatchFailed):
        print(f"\n[erro] {outcome.reason}", flush=True)
        if speak_fn:
            speak_fn(f"Could not dispatch methodology. {outcome.reason}")
        return None

    dispatch_msg = (
        f"{method_def.display_name} run dispatched. I'll surface decisions that need you."
    )
    print(f"\n{dispatch_msg}", flush=True)
    if speak_fn:
        speak_fn(dispatch_msg)

    # --- Event loop + decision-point filter ---
    status = _run_event_filter(outcome, speak_fn, listen_fn=None)

    # --- Standard post-filter lifecycle ---
    _handle_post_filter(outcome, status, speak_fn)

    # --- Verify artifacts on COMPLETED ---
    if status is FilterStatus.COMPLETED and isinstance(outcome, DispatchResult):
        wm = outcome.worktree_manager
        if _worktree_has_files(wm.path):
            msg = f"Methodology run complete. Artifacts are in the worktree at {wm.path}."
            print(f"\n{msg}", flush=True)
            if speak_fn:
                speak_fn("Methodology run complete. Artifacts are in the worktree.")
        else:
            msg = f"Methodology run complete but no artifacts found in worktree at {wm.path}."
            print(f"\n{msg}", flush=True)
            if speak_fn:
                speak_fn("Methodology run complete but no artifacts were detected.")

    return outcome
