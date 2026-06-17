"""
tui.py -- Textual-based chat UI for YANA text mode.

Entry point: run_tui(sessions, on_turn) -> (final_messages, chosen_session_id)

Both session selection and chat loop run inside the same textual App so they
share the same visual style.

Visual language:
  User  :  [dim HH:MM:SS  >[/dim]  text
  YANA  :  RichMarkdown, spaced by blank lines
  Input :  darker bg + visible separator + > prompt label
  Tool  :  ⚙ [tool_name] … (dim) / indented result (dim)
"""

from __future__ import annotations

import re
import textwrap
import threading
from collections.abc import Callable
from datetime import datetime
from typing import ClassVar

from rich.cells import cell_len
from rich.markdown import Markdown as RichMarkdown
from rich.markup import escape
from rich.padding import Padding
from strings import t
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal
from textual.events import MouseScrollDown, MouseScrollUp
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.timer import Timer
from textual.widgets import Input, Label, RichLog, TextArea

_NEW = "__new__"


# ---------------------------------------------------------------------------
# Custom TextArea — Enter submits, Ctrl+Enter inserts newline
# ---------------------------------------------------------------------------


class SubmitTextArea(TextArea):
    """
    A TextArea that:
    - Submits the form on plain Enter (posts a ``SubmitTextArea.Submit`` message)
    - Inserts a literal newline on Ctrl+Enter
    - Wraps text visually (soft_wrap=True, no horizontal scroll)
    """

    class Submit(Message):
        """Posted when the user presses Enter to submit."""

        def __init__(self, text_area: SubmitTextArea) -> None:
            super().__init__()
            self.text_area = text_area

    async def _on_key(self, event) -> None:
        if event.key in ("enter", "ctrl+j"):
            event.prevent_default()
            event.stop()
            self.post_message(self.Submit(self))
        elif event.key == "ctrl+enter":
            event.prevent_default()
            event.stop()
            self.insert("\n")
        else:
            await super()._on_key(event)


TurnCallback = Callable[[list[dict]], str]
ExitCallback = Callable[[list[dict], str | None], None]
TuiResult = tuple[list[dict], str | None]
VoiceListenFn = Callable[[], str]
VoiceSpeakFn = Callable[[str], None]
# tool_event_fn(instance_id, operation, error_or_none, payload_or_none)
# payload is set for run_code: {"code", "deps", "stdout", "stderr", "exit_code", "timed_out"}
ToolEventCallback = Callable[[str, str, str | None, dict | None], None]

_SHARED_CSS = """
Screen {
    background: transparent;
}
"""


# ---------------------------------------------------------------------------
# New-profile modal
# ---------------------------------------------------------------------------


class NewProfileScreen(ModalScreen[str | None]):
    """
    Overlay modal to name a new profile.
    Dismisses with the new label string on Enter, or None on Escape.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    NewProfileScreen {
        align: center middle;
    }
    #new-profile-box {
        width: 44;
        height: 11;
        border: solid #505050;
        background: #111111;
        padding: 1 2;
    }
    #new-profile-label {
        height: 1;
        color: #c0c0c0;
    }
    #new-profile-input {
        background: #1a1a1a;
        border: solid #383838;
        color: #e0e0e0;
        height: 3;
    }
    #new-profile-input:focus {
        border: solid #787878;
    }
    #new-profile-hint {
        height: 1;
        color: #505050;
    }
    """

    def __init__(self) -> None:
        super().__init__()

    def compose(self) -> ComposeResult:
        with Container(id="new-profile-box"):
            yield Label(t("new_profile_prompt"), id="new-profile-label")
            yield Input(
                placeholder=t("new_profile_placeholder"),
                id="new-profile-input",
            )
            yield Label(t("new_profile_hint"), id="new-profile-hint")

    def on_mount(self) -> None:
        self.query_one("#new-profile-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        label = event.value.strip()
        if len(label) >= 2:
            self.dismiss(label)
        else:
            event.input.clear()  # Too short — clear and let user try again

    def action_cancel(self) -> None:
        self.dismiss(None)


class RenameProfileScreen(ModalScreen[str | None]):
    """
    Overlay modal to rename the display label of the active profile.

    Dismisses with the new label string on Enter, or None on Escape.
    The profile id (e.g. 'fred::trabalho') is unchanged — only the
    human-readable label shown in the profile bar is updated.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    RenameProfileScreen {
        align: center middle;
    }
    #rename-profile-box {
        width: 44;
        height: 9;
        border: solid #505050;
        background: #111111;
        padding: 1 2;
    }
    #rename-profile-label {
        height: 1;
        color: #c0c0c0;
    }
    #rename-profile-input {
        background: #1a1a1a;
        border: solid #383838;
        color: #e0e0e0;
        height: 3;
    }
    #rename-profile-input:focus {
        border: solid #787878;
    }
    """

    def __init__(self, current_label: str) -> None:
        super().__init__()
        self._current_label = current_label

    def compose(self) -> ComposeResult:
        with Container(id="rename-profile-box"):
            yield Label(t("rename_profile_prompt"), id="rename-profile-label")
            yield Input(value=self._current_label, id="rename-profile-input")

    def on_mount(self) -> None:
        inp = self.query_one("#rename-profile-input", Input)
        inp.focus()
        inp.cursor_position = len(self._current_label)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if len(name) >= 2:
            self.dismiss(name)
        else:
            event.input.clear()

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Session browser screen — unified profile + session view (CAP-1, CAP-7)
# ---------------------------------------------------------------------------


def _build_session_entries(
    sessions: list[tuple[str, datetime, str]],
) -> list[tuple[str, str]]:
    """Convert session tuples to (id, label) list, prepending a 'new session' entry."""
    today = datetime.now().date()
    entries: list[tuple[str, str]] = [(_NEW, t("sessions_new"))]
    _DATE_COL = 9  # "yesterday" and "há N dias" are both ≤9 chars
    for sid, dt, preview in sessions:
        delta = (today - dt.date()).days
        if delta == 0:
            date_label = t("session_today")
        elif delta == 1:
            date_label = t("session_yesterday")
        elif delta < 7:
            date_label = t("session_days_ago", n=delta)
        else:
            date_label = dt.strftime("%d/%m")
        label = f"{date_label:<{_DATE_COL}}  {dt.strftime('%H:%M')}"
        if preview:
            label += f"  ·  {preview}"
        entries.append((sid, label))
    return entries


class ProfileSessionScreen(Screen[str | None]):
    """
    Unified profile + session browser.

    Left/right arrows switch between profiles (updates active_profile immediately).
    Up/down arrows navigate the session list for the active profile.
    Enter opens the selected session. 'd' deletes the current profile (CAP-7).
    """

    def render(self) -> str:
        return ""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "prev_profile", show=False, priority=True),
        Binding("right", "next_profile", show=False, priority=True),
        Binding("up", "cursor_up", show=False, priority=True),
        Binding("down", "cursor_down", show=False, priority=True),
        Binding("enter", "confirm", "Open", priority=True),
        Binding("n", "new_profile", show=False),
        Binding("r", "rename_profile", show=False),
        Binding("d", "delete_profile", show=False),
        Binding("escape", "cancel", "Quit"),
        Binding("q", "cancel", show=False),
    ]

    _SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    CSS = (
        _SHARED_CSS
        + """
    #profile-bar {
        height: 1;
        padding: 0;
        color: #e0e0e0;
    }
    #session-list {
        height: 1fr;
        padding: 0;
        background: transparent;
        scrollbar-color: #787878;
        scrollbar-background: transparent;
        scrollbar-size: 1 1;
    }
    #session-hint {
        height: 1;
        padding: 0;
        color: #909090;
    }
    """
    )

    def __init__(
        self,
        profiles: list[dict],
        active_profile_id: str,
        sessions: list[tuple[str, datetime, str]],
    ) -> None:
        super().__init__()
        self._profiles = list(profiles)
        self._profile_idx = next(
            (i for i, p in enumerate(profiles) if p["id"] == active_profile_id),
            0,
        )
        self._entries = _build_session_entries(sessions)
        self._cursor = 0
        self._spinner_idx = 0
        self._flash_ticks: int = 0  # countdown for temporary hint messages
        self._flash_msg: str = ""

    def compose(self) -> ComposeResult:
        yield Label("", id="profile-bar")
        yield RichLog(id="session-list", highlight=False, markup=True)
        yield Label("", id="session-hint")

    def on_mount(self) -> None:
        self._render_profile_bar()
        self._render_list()
        self._update_hint()
        self.set_interval(0.12, self._tick_spinner)

    # ------------------------------------------------------------------
    # Profile bar

    def _render_profile_bar(self) -> None:
        bar = self.query_one("#profile-bar", Label)
        if not self._profiles:
            bar.update("")
            return
        parts = []
        for i, p in enumerate(self._profiles):
            label = escape(p.get("label") or p["id"])
            if i == self._profile_idx:
                parts.append(f"[bold white]{label}[/bold white]")
            else:
                parts.append(f"[dim]{label}[/dim]")
        sep = "  [dim]│[/dim]  "
        left = "◄  " if self._profile_idx > 0 else "   "
        right = "  ►" if self._profile_idx < len(self._profiles) - 1 else ""
        bar.update(f"{left}{sep.join(parts)}{right}")

    # ------------------------------------------------------------------
    # Session list

    def _render_list(self) -> None:
        lst = self.query_one("#session-list", RichLog)
        lst.clear()
        lst.write("")
        for i, (_, label) in enumerate(self._entries):
            if i == 1:
                lst.write("")
            if i == self._cursor:
                lst.write(f"  [bold]❯  {escape(label)}[/bold]")  # noqa: RUF001
            elif i == 0:
                lst.write(f"     {escape(label)}")
            else:
                lst.write(f"     [dim]{escape(label)}[/dim]")
        lst.write("")

    # ------------------------------------------------------------------
    # Hint bar

    def _tick_spinner(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(self._SPINNER)
        if self._flash_ticks > 0:
            self._flash_ticks -= 1
        self._update_hint()

    def _flash_hint(self, msg: str, ticks: int = 15) -> None:
        """Show a temporary message in the hint bar for ~1.8s (15 x 0.12s ticks)."""
        self._flash_ticks = ticks
        self._flash_msg = msg
        self._update_hint()

    def _update_hint(self) -> None:
        frame = self._SPINNER[self._spinner_idx]
        if self._flash_ticks > 0:
            self.query_one("#session-hint", Label).update(f"{frame}  {self._flash_msg}")
            return
        multi = len(self._profiles) > 1
        nav = t("profiles_hint_nav") if multi else t("sessions_hint_nav")
        parts = [
            nav,
            t("sessions_hint_select"),
            t("profiles_hint_new"),
            t("profiles_hint_rename"),
            t("sessions_hint_quit"),
        ]
        if multi:
            parts.append(t("profiles_hint_delete"))
        self.query_one("#session-hint", Label).update(f"{frame}  {'   '.join(parts)}")

    # ------------------------------------------------------------------
    # Actions

    def action_prev_profile(self) -> None:
        if self._profile_idx > 0:
            self._profile_idx -= 1
            self._on_profile_changed()

    def action_next_profile(self) -> None:
        if self._profile_idx < len(self._profiles) - 1:
            self._profile_idx += 1
            self._on_profile_changed()

    def _on_profile_changed(self) -> None:
        import core
        import profiles

        profile = self._profiles[self._profile_idx] if self._profiles else {}
        if profile:
            profiles.set_runtime_profile(profile["id"])
            new_sessions = core.list_sessions()
            self._entries = _build_session_entries(new_sessions)
            self._cursor = 0
            self._render_list()
        self._render_profile_bar()

    def action_cursor_up(self) -> None:
        self._cursor = max(0, self._cursor - 1)
        self._render_list()

    def action_cursor_down(self) -> None:
        self._cursor = min(len(self._entries) - 1, self._cursor + 1)
        self._render_list()

    def action_confirm(self) -> None:
        self.dismiss(self._entries[self._cursor][0])

    def action_delete_profile(self) -> None:
        if len(self._profiles) <= 1:
            return  # Refuse to delete the last profile
        import core
        import profiles

        profile = self._profiles[self._profile_idx]
        profiles.delete_profile(profile["id"])
        self._profiles.pop(self._profile_idx)
        self._profile_idx = min(self._profile_idx, len(self._profiles) - 1)
        if self._profiles:
            profiles.set_runtime_profile(self._profiles[self._profile_idx]["id"])
            new_sessions = core.list_sessions()
            self._entries = _build_session_entries(new_sessions)
        else:
            self._entries = _build_session_entries([])
        self._cursor = 0
        self._render_profile_bar()
        self._render_list()
        self._update_hint()

    _PROFILE_LIMIT = 5

    def action_new_profile(self) -> None:
        if len(self._profiles) >= self._PROFILE_LIMIT:
            self._flash_hint(t("profiles_limit_reached"))
            return
        self.app.push_screen(NewProfileScreen(), self._on_new_profile)

    def _on_new_profile(self, label: str | None) -> None:
        if not label:
            return
        import profiles

        try:
            profile_id = profiles.add_profile(label)
        except ValueError as exc:
            self._flash_hint(str(exc))
            return
        self._profiles.append({"id": profile_id, "label": label})
        self._profile_idx = len(self._profiles) - 1
        self._entries = _build_session_entries([])  # new profile has no sessions
        self._cursor = 0
        self._render_profile_bar()
        self._render_list()
        self._update_hint()

    def action_rename_profile(self) -> None:
        if not self._profiles:
            return
        current = self._profiles[self._profile_idx]
        self.app.push_screen(
            RenameProfileScreen(current.get("label", current["id"])), self._on_rename
        )

    def _on_rename(self, new_label: str | None) -> None:
        if not new_label:
            return
        import profiles

        profile = self._profiles[self._profile_idx]
        profiles.rename_profile_label(profile["id"], new_label)
        profile["label"] = new_label
        self._render_profile_bar()

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Main chat app
# ---------------------------------------------------------------------------


class YANAApp(App[TuiResult]):
    """
    YANA TUI — session browser → chat loop.
    Returns (final_messages, chosen_session_id) on exit.
    """

    CSS = (
        _SHARED_CSS
        + """
    /* ── Chat log ──────────────────────────────────────── */

    #chat {
        height: 1fr;
        padding: 0;
        background: transparent;
        scrollbar-color: #787878;
        scrollbar-background: transparent;
        scrollbar-size: 1 1;
    }

    /* ── Input row ─────────────────────────────────────── */

    #input-bar {
        height: 2;
        background: #0a0a0a;
        border-top: solid #383838;
        align: left bottom;
        padding: 0;
    }

    #prompt-label {
        width: 3;
        color: #909090;
        content-align: center middle;
    }

    #input {
        background: #0a0a0a;
        border: none;
        color: #e0e0e0;
        padding: 0;
    }

    #input:focus {
        border: none;
    }

    /* ── Thinking / listening indicator (row above input-bar) ─ */

    #thinking {
        height: 1;
        padding: 0;
        color: #909090;
        content-align: left middle;
        display: none;
    }

    /* ── Keyboard shortcut hints (below input-bar) ──────────── */

    #chat-hint {
        height: 2;
        padding: 0;
        border-top: solid #383838;
        color: #505050;
        content-align: left middle;
    }
    """
    )

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+c", "quit_app", "Quit", priority=True),
        Binding("ctrl+d", "quit_app", "End session", show=True, priority=True),
        Binding("ctrl+o", "toggle_history", "History", show=False),
        Binding("ctrl+y", "copy_last", "Copy last reply", show=False),
        Binding("ctrl+t", "toggle_voice", "Voice", show=True),
        Binding("ctrl+b", "switch_session", "Sessions", show=False),
        Binding("pageup", "scroll_chat_up", "Scroll up", show=False, priority=True),
        Binding("pagedown", "scroll_chat_down", "Scroll down", show=False, priority=True),
    ]

    _SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    _USER_BG = "#3a3a3a"

    def __init__(
        self,
        sessions: list[tuple[str, datetime, str]],
        on_turn: TurnCallback,
        on_exit: ExitCallback | None = None,
        voice_mode: bool = False,
        listen_fn: VoiceListenFn | None = None,
        speak_fn: VoiceSpeakFn | None = None,
        greeting: str | None = None,
        auto_greet: bool = False,
        profiles: list[dict] | None = None,
        active_profile_id: str = "",
        make_tool_event_cb: Callable[[ToolEventCallback], TurnCallback] | None = None,
    ) -> None:
        super().__init__()
        self._sessions = sessions
        self._profiles = profiles or []
        self._active_profile_id = active_profile_id
        self._on_turn = on_turn
        self._make_tool_event_cb = make_tool_event_cb
        self._on_exit = on_exit
        self._messages: list[dict] = []
        self._session_history: list[dict] = []  # loaded from old session
        self._new_messages: list[tuple[str, dict]] = []  # (ts, msg) this session
        self._history_expanded: bool = False
        self._chosen_session: str | None = None
        self._busy = False
        self._saving_mode = False
        self._force_exited = False
        self._spinner_idx: int = 0
        self._spinner_timer: Timer | None = None
        self._inbox_timer: Timer | None = None
        self._voice_mode = voice_mode
        self._listen_fn = listen_fn
        self._speak_fn = speak_fn
        self._greeting = greeting
        self._auto_greet = auto_greet
        self._listening: bool = False
        self._voice_gen: int = 0  # incremented each activation; invalidates old loops
        self._chat_started: bool = (
            False  # True once _start_chat() completes — guards on_input_submitted
        )
        self._last_yana_reply: str = ""  # for ctrl+y copy

    # ------------------------------------------------------------------
    # Layout

    def compose(self) -> ComposeResult:
        yield RichLog(id="chat", highlight=False, markup=True, wrap=True)
        yield Label("", id="thinking")
        with Horizontal(id="input-bar"):
            yield Label("❯", id="prompt-label")  # noqa: RUF001
            yield Input(id="input")
        yield Label("", id="chat-hint")

    def on_mount(self) -> None:
        if self._profiles or self._sessions:
            # Has profiles or existing sessions — show the unified browser screen
            self.push_screen(
                ProfileSessionScreen(self._profiles, self._active_profile_id, self._sessions),
                self._on_session_chosen,
            )
        else:
            self._start_chat()  # Fresh install — First Breath

    # ------------------------------------------------------------------
    # Session selection

    def _on_session_chosen(self, choice: str | None) -> None:
        if choice is None:
            self.exit(([], None))
            return
        if choice != _NEW:
            import core

            all_msgs = core.load_session_messages(choice)
            self._session_history = all_msgs
            self._messages = [m for m in all_msgs if m.get("role") in ("user", "assistant")]
            self._chosen_session = choice
        self._start_chat()

    # ------------------------------------------------------------------
    # Chat init + history toggle

    def _write_continuing_rule(self, chat: RichLog) -> None:
        hint = t("chat_history_collapse") if self._history_expanded else t("chat_history_expand")
        label = f"◷  {t('sessions_continuing')}  ·  {hint}"
        chat.write(f"[dim]{escape(label)}[/dim]")
        chat.write(RichMarkdown("---"))

    _YANA_ICON = "●"
    _GUTTER = 3  # width of icon column: ">  " or "·  " or "   "

    def _chat_width(self) -> int:
        """Usable line width inside the chat widget.
        Uses size.width (outer widget width) minus CSS padding (0 3 → 6) and scrollbar (1).
        content_size grows with scroll content so must NOT be used here.
        """
        try:
            w = self.query_one("#chat", RichLog).size.width - 7
            return w if w > 20 else 80
        except Exception:
            return 80

    def _write_user_bg(self, chat: RichLog, text: str, ts: str = "") -> None:
        """User message: dim rule above, > + text + ts, dim rule below."""
        w = self._chat_width()
        ts_str = f"  {ts}" if ts else ""
        ts_len = cell_len(ts_str)
        text_w = max(1, w - self._GUTTER - ts_len)  # space for text on first line
        wrap_w = max(1, w - self._GUTTER)  # space for wrapped lines

        raw = text.replace("\n", " ")
        lines = textwrap.wrap(raw, width=text_w, break_long_words=True) or [""]

        # First line: icon + text + gap + ts
        first = lines[0]
        gap = max(0, w - self._GUTTER - cell_len(first) - ts_len)
        ts_mk = f"[dim]{escape(ts_str)}[/dim]" if ts_str else ""
        chat.write(
            f"[on {self._USER_BG}][dim]❯  [/dim]{escape(first)}{' ' * gap}{ts_mk}[/on {self._USER_BG}]"  # noqa: RUF001
        )
        # Wrapped lines: indent only, no icon, no ts
        for line in lines[1:]:
            pad = max(0, wrap_w - cell_len(line))
            chat.write(f"[on {self._USER_BG}]   {escape(line)}{' ' * pad}[/on {self._USER_BG}]")

        chat.write("")

    @staticmethod
    def _md_inline(text: str) -> str:
        """Escape Rich delimiters then convert inline markdown to Rich markup."""
        s = escape(text)  # escapes [ ] \ so they won't be misread as Rich markup
        s = re.sub(r"\*\*(.+?)\*\*", r"[bold]\1[/bold]", s)
        s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"[italic]\1[/italic]", s)
        s = re.sub(r"`(.+?)`", r"[dim]\1[/dim]", s)
        return s

    def _write_yana(self, chat: RichLog, content: str, ts: str = "") -> None:
        """YANA: ● + first paragraph inline (no blank line), rest as RichMarkdown."""
        w = self._chat_width()

        parts = content.strip().split("\n\n", 1)
        first_para = parts[0].strip().replace("\n", " ")
        rest = parts[1].strip() if len(parts) > 1 else ""

        ts_str = f"  {ts}" if ts else ""
        ts_len = cell_len(ts_str)
        text_w = max(1, w - self._GUTTER - ts_len)

        # Strip markdown for width measurement (cell_len needs plain text)
        plain = re.sub(r"\*+|`", "", first_para)
        lines = textwrap.wrap(plain, width=text_w, break_long_words=True) or [""]
        first_plain = lines[0]

        # Re-wrap original text at same width to get correct first chunk
        orig_lines = textwrap.wrap(first_para, width=text_w, break_long_words=True) or [""]
        first_orig = orig_lines[0]

        gap = max(0, w - self._GUTTER - cell_len(first_plain) - ts_len)
        ts_mk = f"[dim]{escape(ts_str)}[/dim]" if ts_str else ""

        chat.write(f"●  {self._md_inline(first_orig)}{' ' * gap}{ts_mk}")
        for line in orig_lines[1:]:
            chat.write(f"   {self._md_inline(line)}")

        if rest:
            chat.write(Padding(RichMarkdown(rest), (0, 0, 0, self._GUTTER)))

        chat.write("")

    def _write_tool_event(
        self,
        chat: RichLog,
        instance: str,
        operation: str,
        error: str | None = None,
        payload: dict | None = None,
        ts: str = "",
    ) -> None:
        """Render a tool call/result event in the chat log (dim, muted style)."""
        if operation == "run_code" and payload is not None:
            self._write_sandbox_event(chat, payload, ts=ts)
            return
        label = escape(f"{instance}/{operation}") if instance else escape(operation)
        ts_mk = f"[dim]  {ts}[/dim]" if ts else ""
        if error:
            chat.write(f"[dim]  ⚙ {label}  ✗ {escape(error)}[/dim]{ts_mk}")
        else:
            chat.write(f"[dim]  ⚙ {label}[/dim]{ts_mk}")

    def _write_sandbox_event(self, chat: RichLog, payload: dict, ts: str = "") -> None:
        """Render a sandbox run_code event — shows code sent and output received."""
        code: str = payload.get("code", "")
        deps: list = payload.get("deps") or []
        stdout: str = payload.get("stdout", "").strip()
        stderr: str = payload.get("stderr", "").strip()
        exit_code: int = payload.get("exit_code", -1)
        timed_out: bool = payload.get("timed_out", False)

        # Header line
        status = "[red]✗[/red]" if exit_code != 0 or timed_out else "[green]✓[/green]"
        deps_hint = f"  {', '.join(deps)}" if deps else ""
        ts_mk = f"[dim]  {ts}[/dim]" if ts else ""
        chat.write(
            f"[dim]  {escape(t('sandbox_label'))} {status}[/dim][dim]{escape(deps_hint)}[/dim]{ts_mk}"
        )

        # Code block — blank line after, plain indent, no │
        for line in code.splitlines():
            chat.write(f"[dim]    {escape(line)}[/dim]")
        chat.write("")

        # Output
        if timed_out:
            chat.write(f"[dim]  → {escape(t('sandbox_timed_out'))}[/dim]")
        elif stdout:
            for line in stdout.splitlines():
                chat.write(f"[dim]  → {escape(line)}[/dim]")
        elif stderr:
            first_err = stderr.splitlines()[0]
            chat.write(f"[dim]  → [red]{escape(first_err)}[/red][/dim]")

    def _make_tool_event_fn(self, chat: RichLog) -> ToolEventCallback:
        """Return a thread-safe callback that writes tool events to *chat*."""

        def _cb(
            instance: str, operation: str, error: str | None, payload: dict | None = None
        ) -> None:
            ts = datetime.now().strftime("%H:%M:%S")
            msg: dict = {"role": "tool", "content": instance, "tool_op": operation}
            if error:
                msg["error"] = error
            if payload:
                msg["payload"] = payload
            self._new_messages.append((ts, msg))
            self.call_from_thread(
                self._write_tool_event, chat, instance, operation, error, payload, ts
            )

        return _cb

    def _history_line(self, chat: RichLog, m: dict, truncate: int | None = 80) -> None:
        if m["role"] == "tool":
            # Always render tool events fully — no truncation concept
            self._write_tool_event(
                chat,
                m.get("content", ""),
                m.get("tool_op", ""),
                m.get("error"),
                m.get("payload"),
                m.get("ts", ""),
            )
            return
        if m["role"] == "user":
            raw = m["content"].replace("\n", " ")
            if truncate is not None:
                text = raw[:truncate] + ("…" if len(raw) > truncate else "")
            else:
                text = raw
            self._write_user_bg(chat, text, ts=m.get("ts", self._session_ts()))
        else:
            ts = m.get("ts", self._session_ts())
            if truncate is None:
                # Expanded: full markdown with icon + ts header
                self._write_yana(chat, m["content"], ts=ts)
            else:
                # Collapsed: ● icon + truncated text (normal color)
                raw = m["content"].replace("\n", " ")
                text = raw[:truncate] + ("…" if len(raw) > truncate else "")
                chat.write(f"●  {escape(text)}")
                chat.write("")

    def _build_storable_messages(self) -> list[dict]:
        """Merge _new_messages (user + assistant + tool events) into a flat list for storage."""
        result = []
        for ts, m in self._new_messages:
            entry = dict(m)
            if ts:
                entry.setdefault("ts", ts)
            result.append(entry)
        return result or list(self._messages)

    def _session_ts(self) -> str:
        """Return HH:MM:SS from the chosen session ID, or empty string."""
        if not self._chosen_session:
            return ""
        try:
            dt = datetime.strptime(self._chosen_session[:19], "%Y-%m-%d_%H-%M-%S")
            return dt.strftime("%H:%M:%S")
        except ValueError:
            return ""

    def _write_history(self, chat: RichLog) -> None:
        if self._history_expanded:
            for m in self._session_history:
                self._history_line(chat, m, truncate=None)
        else:
            for m in self._session_history[-2:]:
                self._history_line(chat, m, truncate=80)
        self._write_continuing_rule(chat)
        chat.write("")

    def _start_chat(self) -> None:
        chat = self.query_one("#chat", RichLog)
        self.query_one("#input", Input).clear()  # flush any text buffered during screen transitions
        self._chat_started = True  # gate: discard events before this point
        # Hint bar
        hints = [
            t("chat_hint_end"),
            t("chat_hint_history"),
            t("chat_hint_copy"),
            t("chat_hint_select"),
        ]
        if self._listen_fn:
            hints.append(t("chat_hint_voice"))
        if self._profiles:
            hints.append(t("chat_hint_sessions"))
        self.query_one("#chat-hint", Label).update("   ".join(hints))
        if self._session_history:
            self._write_history(chat)
        if self._voice_mode:
            self._voice_gen += 1
            self.query_one("#prompt-label", Label).display = False
            self.query_one("#input", Input).display = False
            if self._greeting:
                ts = datetime.now().strftime("%H:%M:%S")
                self._write_yana(chat, self._greeting, ts)
            self._voice_start(self._voice_gen)
        else:
            if self._greeting:
                ts = datetime.now().strftime("%H:%M:%S")
                self._write_yana(chat, self._greeting, ts)
                self.query_one("#input", Input).focus()
            elif self._auto_greet:
                self._busy = True
                self._show_thinking(True)
                self._do_auto_greet()
            else:
                self.query_one("#input", Input).focus()
        self._inbox_timer = self.set_interval(2.0, self._check_pulse_inbox)

    def _check_pulse_inbox(self) -> None:
        """Poll pulse-inbox.json and display any pending Pulse notifications."""
        import json
        import os

        import core

        inbox_path = core.sanctum_path() / "pulse-inbox.json"
        if not inbox_path.exists():
            return
        tmp = inbox_path.with_suffix(".reading")
        try:
            os.replace(inbox_path, tmp)
        except FileNotFoundError:
            return
        try:
            entries = json.loads(tmp.read_text(encoding="utf-8"))
            tmp.unlink()
        except (json.JSONDecodeError, OSError):
            # Restore unprocessed entries so they are not lost
            try:
                os.replace(tmp, inbox_path)
            except OSError:
                pass
            return
        if not entries or not isinstance(entries, list):
            return
        chat = self.query_one("#chat", RichLog)
        for entry in entries:
            raw_ts = entry.get("ts", "")
            try:
                ts_str = datetime.fromisoformat(raw_ts).strftime("%H:%M:%S")
            except (ValueError, TypeError):
                ts_str = datetime.now().strftime("%H:%M:%S")
            self._write_yana(chat, entry["content"], ts_str)

    @work(thread=True)
    def _do_auto_greet(self) -> None:
        """Trigger YANA's opening message from inside the TUI — no pre-generation blocking startup."""
        chat = self.query_one("#chat", RichLog)

        # Hidden trigger — starts the conversation without showing a user bubble
        trigger = {"role": "user", "content": "..."}
        try:
            reply = self._on_turn([trigger])
        except Exception as exc:
            reply = f"[error: {exc}]"

        reply_ts = datetime.now().strftime("%H:%M:%S")

        # Both trigger and reply go into history so subsequent turns have valid [user, assistant, user...] structure
        self._messages.append(trigger)
        self._messages.append({"role": "assistant", "content": reply})
        self._new_messages.append((reply_ts, {"role": "assistant", "content": reply}))
        if reply:
            self._last_yana_reply = reply

        self.call_from_thread(self._show_thinking, False)
        if reply:
            self.call_from_thread(self._write_yana, chat, reply, reply_ts)

        self._busy = False

    @work(thread=True)
    def _voice_start(self, gen: int) -> None:
        """Speaks greeting (blocking) then enters the listen loop."""
        if self._greeting and self._speak_fn:
            self._speak_fn(self._greeting)
        self._voice_loop(gen)

    @work(thread=True)
    def _voice_loop(self, gen: int) -> None:
        """Shows listening state, blocks on listen_fn(), then triggers a turn."""
        if (
            self._listen_fn is None
            or self._force_exited
            or not self._voice_mode
            or gen != self._voice_gen
        ):
            return
        self._listening = True
        self.call_from_thread(self._show_thinking, True)
        try:
            text = self._listen_fn()
        except Exception:
            text = ""
        finally:
            self._listening = False
        if not self._voice_mode or self._force_exited or gen != self._voice_gen:
            return
        if text:
            self._busy = True
            self._do_turn_voice(text, gen)
        else:
            # Nothing heard — listen again
            self._voice_loop(gen)

    @work(thread=True)
    def _do_turn_voice(self, text: str, gen: int) -> None:
        """Voice-mode turn: write user msg, call LLM, speak reply, loop."""
        chat = self.query_one("#chat", RichLog)
        ts = datetime.now().strftime("%H:%M:%S")

        self.call_from_thread(self._write_user_bg, chat, text, ts)

        self._messages.append({"role": "user", "content": text})
        self._new_messages.append((ts, {"role": "user", "content": text}))
        try:
            reply = self._on_turn(list(self._messages))
        except Exception as exc:
            reply = f"[error: {exc}]"
        reply_ts = datetime.now().strftime("%H:%M:%S")
        self._messages.append({"role": "assistant", "content": reply})
        self._new_messages.append((reply_ts, {"role": "assistant", "content": reply}))
        if reply:
            self._last_yana_reply = reply

        self.call_from_thread(self._show_thinking, False)
        if reply:
            self.call_from_thread(self._write_yana, chat, reply, reply_ts)

        self._busy = False

        if self._speak_fn and reply:
            self._speak_fn(reply)  # blocking — don't listen while speaking

        if not self._force_exited and self._voice_mode and gen == self._voice_gen:
            self._voice_loop(gen)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "toggle_voice":
            return self._listen_fn is not None
        if action == "switch_session":
            return bool(self._profiles)
        return True

    def action_toggle_voice(self) -> None:
        self._voice_mode = not self._voice_mode
        if self._voice_mode:
            self._voice_gen += 1
            self.query_one("#prompt-label", Label).display = False
            self.query_one("#input", Input).display = False
            self._voice_loop(self._voice_gen)
        else:
            if self._spinner_timer is not None:
                self._spinner_timer.stop()
                self._spinner_timer = None
            self.query_one("#thinking", Label).display = False
            self.query_one("#prompt-label", Label).display = True
            self.query_one("#input", Input).display = True
            self.query_one("#input", Input).focus()

    def action_toggle_history(self) -> None:
        if not self._session_history:
            return
        self._history_expanded = not self._history_expanded
        chat = self.query_one("#chat", RichLog)
        chat.clear()
        self._write_history(chat)
        for ts, m in self._new_messages:
            if m["role"] == "user":
                self._write_user_bg(chat, m["content"], ts)
            elif m["role"] == "tool":
                self._write_tool_event(
                    chat, m["content"], m.get("tool_op", ""), m.get("error"), m.get("payload")
                )
            else:
                self._write_yana(chat, m["content"], ts)

    def action_scroll_chat_up(self) -> None:
        """Scroll the chat log up by one page (PageUp while input is focused)."""
        self.query_one("#chat", RichLog).scroll_page_up(animate=False)

    def action_scroll_chat_down(self) -> None:
        """Scroll the chat log down by one page (PageDown while input is focused)."""
        self.query_one("#chat", RichLog).scroll_page_down(animate=False)

    def action_copy_last(self) -> None:
        """Copy the last YANA reply to the system clipboard (ctrl+y)."""
        if not self._last_yana_reply:
            self._flash_hint(t("chat_nothing_to_copy"))
            return
        self.copy_to_clipboard(self._last_yana_reply)
        self._flash_hint(t("chat_copied"))

    def _flash_hint(self, msg: str, duration: float = 1.5) -> None:
        """Briefly show *msg* in the hint bar, then restore the normal hints."""
        hint = self.query_one("#chat-hint", Label)
        hint.update(msg)
        self.set_timer(duration, self._restore_hint)

    def _restore_hint(self) -> None:
        """Restore the normal hint bar content after a flash."""
        hints = [
            t("chat_hint_end"),
            t("chat_hint_history"),
            t("chat_hint_copy"),
            t("chat_hint_select"),
        ]
        if self._listen_fn:
            hints.append(t("chat_hint_voice"))
        if self._profiles:
            hints.append(t("chat_hint_sessions"))
        self.query_one("#chat-hint", Label).update("   ".join(hints))

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        """Forward mouse wheel up to the chat log regardless of where the mouse is."""
        event.stop()
        self.query_one("#chat", RichLog).scroll_up(animate=False)

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        """Forward mouse wheel down to the chat log regardless of where the mouse is."""
        event.stop()
        self.query_one("#chat", RichLog).scroll_down(animate=False)

    def action_switch_session(self) -> None:
        """Return to the session browser mid-conversation (ctrl+b)."""
        if self._busy:
            return
        # Save current session in the background before returning to browser
        if self._messages and self._on_exit:
            import threading as _threading

            _session_id = self._chosen_session or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            _msgs = self._build_storable_messages()
            _on_exit = self._on_exit
            _threading.Thread(
                target=lambda: _on_exit(_msgs, _session_id),
                daemon=False,
                name="session-switch-save",
            ).start()
        import core as _core

        fresh_sessions = _core.list_sessions()
        self.push_screen(
            ProfileSessionScreen(self._profiles, self._active_profile_id, fresh_sessions),
            self._on_switch_session_chosen,
        )

    def _on_switch_session_chosen(self, choice: str | None) -> None:
        if choice is None:
            return  # dismissed — stay in current session
        import core as _core
        import profiles as _profiles

        # Update active profile (user may have navigated to a different profile in the browser)
        self._active_profile_id = _profiles.get_active_profile() or self._active_profile_id
        # Reset all chat state — including _busy which may be stale from the previous session
        self._messages = []
        self._session_history = []
        self._new_messages = []
        self._chosen_session = None
        self._history_expanded = False
        self._busy = False
        if choice != _NEW:
            all_msgs = _core.load_session_messages(choice)
            self._session_history = all_msgs
            self._messages = [m for m in all_msgs if m.get("role") in ("user", "assistant")]
            self._chosen_session = choice
        self.query_one("#chat", RichLog).clear()
        self._chat_started = False
        self.query_one("#input", Input).clear()
        self._start_chat()

    # ------------------------------------------------------------------
    # Input handling

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter-to-submit from the chat input."""
        if event.input.id != "input":
            return  # ignore modal inputs
        if self._voice_mode:
            return
        if not self._chat_started:
            event.input.clear()
            return
        text = event.value.strip()
        if not text or self._busy:
            return
        event.input.clear()
        self._busy = True
        self._do_turn(text)

    @work(thread=True)
    def _do_turn(self, text: str) -> None:
        chat = self.query_one("#chat", RichLog)
        ts = datetime.now().strftime("%H:%M:%S")

        self.call_from_thread(self._write_user_bg, chat, text, ts)
        self.call_from_thread(self._show_thinking, True)

        self._messages.append({"role": "user", "content": text})
        self._new_messages.append((ts, {"role": "user", "content": text}))

        # Wire tool-event display if the caller provided a factory
        _on_turn = self._on_turn
        if self._make_tool_event_cb is not None:
            tool_cb = self._make_tool_event_fn(chat)
            _on_turn = self._make_tool_event_cb(tool_cb)

        try:
            reply = _on_turn(list(self._messages))
        except Exception as exc:
            reply = f"[error: {exc}]"
        reply_ts = datetime.now().strftime("%H:%M:%S")
        self._messages.append({"role": "assistant", "content": reply})
        self._new_messages.append((reply_ts, {"role": "assistant", "content": reply}))
        if reply:
            self._last_yana_reply = reply

        self.call_from_thread(self._show_thinking, False)
        if reply:
            self.call_from_thread(self._write_yana, chat, reply, reply_ts)

        self._busy = False

    # ------------------------------------------------------------------
    # Helpers

    def _show_thinking(self, visible: bool) -> None:
        thinking = self.query_one("#thinking", Label)
        if visible:
            thinking.display = True
            self._spinner_idx = 0
            thinking.update(
                f"  {self._SPINNER[0]} {t('thinking')}"
            )  # immediate — no wait for first tick
            if self._spinner_timer is None:
                self._spinner_timer = self.set_interval(0.1, self._tick_spinner)
        else:
            if self._voice_mode:
                return  # voice mode: spinner always visible
            if self._spinner_timer is not None:
                self._spinner_timer.stop()
                self._spinner_timer = None
            thinking.display = False
            if not self._saving_mode:
                self.query_one("#input", Input).focus()

    def _tick_spinner(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(self._SPINNER)
        frame = self._SPINNER[self._spinner_idx]
        if self._saving_mode:
            msg = f"{t('saving_memory')}  ·  {t('saving_memory_skip')}"
        elif self._listening:
            msg = t("listening")
        else:
            msg = t("thinking")
        self.query_one("#thinking", Label).update(f"  {frame} {msg}")

    def action_quit_app(self) -> None:
        if self._busy:
            return
        if self._saving_mode:
            # Second Ctrl+C — force exit immediately; daemon thread dies with the process
            self._force_exited = True
            self.exit((self._build_storable_messages(), self._chosen_session))
            return
        if self._on_exit is None or not self._messages:
            self.exit((self._build_storable_messages(), self._chosen_session))
            return
        self._saving_mode = True
        self.query_one("#input", Input).disabled = True
        self._show_thinking(True)
        threading.Thread(target=self._save_and_exit, daemon=True).start()

    def _save_and_exit(self) -> None:
        try:
            if self._on_exit is not None:
                self._on_exit(self._build_storable_messages(), self._chosen_session)
        except Exception:
            pass
        if not self._force_exited:
            self.call_from_thread(self._show_thinking, False)
            self.call_from_thread(self.exit, (self._messages, self._chosen_session))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_tui(
    sessions: list[tuple[str, datetime, str]],
    on_turn: TurnCallback,
    on_exit: ExitCallback | None = None,
    voice_mode: bool = False,
    listen_fn: VoiceListenFn | None = None,
    speak_fn: VoiceSpeakFn | None = None,
    greeting: str | None = None,
    auto_greet: bool = False,
    profiles: list[dict] | None = None,
    active_profile_id: str = "",
    make_tool_event_cb: Callable[[ToolEventCallback], TurnCallback] | None = None,
) -> TuiResult:
    """
    Launch the YANA TUI. Blocks until the user exits (and on_exit completes).
    Returns (final_messages, chosen_session_id).
    chosen_session_id is None for new sessions.

    profiles: list of {id, label} dicts — if provided, shows profile switcher (CAP-1).
    active_profile_id: the currently active profile id.
    make_tool_event_cb: optional factory — receives a ToolEventCallback and returns
        a TurnCallback that routes tool events to the chat display.
    """
    app = YANAApp(
        sessions=sessions,
        on_turn=on_turn,
        on_exit=on_exit,
        voice_mode=voice_mode,
        listen_fn=listen_fn,
        speak_fn=speak_fn,
        greeting=greeting,
        auto_greet=auto_greet,
        profiles=profiles,
        active_profile_id=active_profile_id,
        make_tool_event_cb=make_tool_event_cb,
    )
    try:
        result = app.run(mouse=True)
    except KeyboardInterrupt:
        result = None
    return result if result is not None else ([], None)
