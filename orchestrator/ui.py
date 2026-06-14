"""
ui.py — Text UI components for YANA prompt mode.

Session browser: arrow-key navigable list of past sessions.
"""

from __future__ import annotations

from datetime import datetime

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from strings import t

from prompt_toolkit.styles import Style

_STYLE = Style.from_dict(
    {
        "selected": "bold",
        "hint": "fg:ansibrightblack",
        "sep": "fg:ansibrightblack",
    }
)

_NEW = "__new__"


def session_browser(sessions: list[tuple[str, datetime, str]]) -> str | None:
    """
    Arrow-key navigable session selector.

    sessions: list of (session_id, datetime, preview) newest first.
    Returns session_id to resume, "__new__" for a new session,
    or None if the user quit without selecting.
    """
    entries: list[tuple[str, str]] = [(_NEW, t("sessions_new"))]
    for sid, dt, preview in sessions:
        date_part = dt.strftime("%d/%m  %H:%M")
        label = f"{date_part}  {preview}" if preview else date_part
        entries.append((sid, label))

    state = {"cursor": 0}

    kb = KeyBindings()

    @kb.add("up")
    def _up(event) -> None:
        state["cursor"] = max(0, state["cursor"] - 1)

    @kb.add("down")
    def _down(event) -> None:
        state["cursor"] = min(len(entries) - 1, state["cursor"] + 1)

    @kb.add("enter")
    def _enter(event) -> None:
        event.app.exit(result=entries[state["cursor"]][0])

    @kb.add("c-c")
    @kb.add("q")
    def _quit(event) -> None:
        event.app.exit(result=None)

    def get_content() -> FormattedText:
        lines: list[tuple[str, str]] = []
        for i, (sid, label) in enumerate(entries):
            if i == state["cursor"]:
                lines.append(("class:selected", f"  ▶  {label}\n"))
            else:
                lines.append(("", f"     {label}\n"))
        lines.append(("class:hint", f"\n  {t('sessions_hint')}\n"))
        return FormattedText(lines)

    layout = Layout(Window(FormattedTextControl(get_content, focusable=True)))

    app: Application[str | None] = Application(
        layout=layout,
        key_bindings=kb,
        style=_STYLE,
        full_screen=False,
        mouse_support=False,
        refresh_interval=None,
        erase_when_done=True,
    )
    return app.run()
