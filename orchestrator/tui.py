"""
tui.py -- Textual-based chat UI for YANA text mode.

Entry point: run_tui(sessions, on_turn) -> (final_messages, chosen_session_id)

Both session selection and chat loop run inside the same textual App so they
share the same visual style.

Visual language:
  User  :  [dim HH:MM:SS  >[/dim]  text
  YANA  :  RichMarkdown, spaced by blank lines
  Input :  darker bg + visible separator + > prompt label
"""

from __future__ import annotations

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
from textual.containers import Horizontal
from textual.events import Key
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Input, Label, RichLog

_NEW = "__new__"

TurnCallback = Callable[[list[dict]], str]
ExitCallback = Callable[[list[dict], str | None], None]
TuiResult = tuple[list[dict], str | None]
VoiceListenFn = Callable[[], str]
VoiceSpeakFn = Callable[[str], None]

_SHARED_CSS = """
Screen {
    background: transparent;
}
"""


# ---------------------------------------------------------------------------
# Session browser screen
# ---------------------------------------------------------------------------


class SessionScreen(Screen[str | None]):
    """Arrow-key session selector — same visual as the chat screen."""

    # textual 8.x: Screen._render() must return a renderable, not None.
    def render(self) -> str:
        return ""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("enter", "confirm", "Select"),
        Binding("escape", "cancel", "Quit"),
        Binding("q", "cancel", show=False),
    ]

    _SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    CSS = (
        _SHARED_CSS
        + """
    #session-list {
        height: 1fr;
        padding: 1 3;
        background: transparent;
        scrollbar-color: #787878;
        scrollbar-background: transparent;
        scrollbar-size: 1 1;
    }
    #session-hint {
        height: 1;
        padding: 0 5;
        color: #909090;
    }
    """
    )

    def __init__(self, sessions: list[tuple[str, datetime, str]]) -> None:
        super().__init__()
        today = datetime.now().date()
        self._entries: list[tuple[str, str]] = [(_NEW, t("sessions_new"))]
        # Pre-compute max date label width for alignment
        _DATE_COL = 9  # "yesterday" and "há N dias" are both 9 chars max
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
            self._entries.append((sid, label))
        self._cursor = 0
        self._spinner_idx = 0

    def compose(self) -> ComposeResult:
        yield RichLog(id="session-list", highlight=False, markup=True)
        yield Label("", id="session-hint")

    def on_mount(self) -> None:
        self._render_list()
        self._update_hint()
        self.set_interval(0.12, self._tick_spinner)

    def on_key(self, event: Key) -> None:
        if event.key == "up":
            self.action_cursor_up()
        elif event.key == "down":
            self.action_cursor_down()
        elif event.key == "enter":
            self.action_confirm()
        elif event.key in ("escape", "q"):
            self.action_cancel()

    def _tick_spinner(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(self._SPINNER)
        self._update_hint()

    def _update_hint(self) -> None:
        frame = self._SPINNER[self._spinner_idx]
        self.query_one("#session-hint", Label).update(f"  {frame}  {t('sessions_hint')}")

    def _render_list(self) -> None:
        lst = self.query_one("#session-list", RichLog)
        lst.clear()
        lst.write("")
        for i, (_, label) in enumerate(self._entries):
            # Blank line gap between "new session" and history
            if i == 1:
                lst.write("")
            if i == self._cursor:
                lst.write(f"  [bold]❯  {escape(label)}[/bold]")  # noqa: RUF001
            elif i == 0:
                # "new session" — always plain, never dim
                lst.write(f"     {escape(label)}")
            else:
                lst.write(f"     [dim]{escape(label)}[/dim]")
        lst.write("")

    def action_cursor_up(self) -> None:
        self._cursor = max(0, self._cursor - 1)
        self._render_list()

    def action_cursor_down(self) -> None:
        self._cursor = min(len(self._entries) - 1, self._cursor + 1)
        self._render_list()

    def action_confirm(self) -> None:
        self.dismiss(self._entries[self._cursor][0])

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
        padding: 0 3;
        background: transparent;
        scrollbar-color: #787878;
        scrollbar-background: transparent;
        scrollbar-size: 1 1;
    }

    /* ── Thinking indicator ────────────────────────────── */

    #thinking {
        height: 1;
        padding: 0 5;
        color: #909090;
        display: none;
    }

    /* ── Input row ─────────────────────────────────────── */

    #input-bar {
        height: 3;
        background: #0a0a0a;
        border-top: solid #383838;
        align: left middle;
        padding: 0 2;
    }

    #prompt-label {
        width: 3;
        color: #909090;
        content-align: center middle;
    }

    Input {
        background: #0a0a0a;
        border: none;
        height: 100%;
        color: #e0e0e0;
    }

    Input:focus {
        border: none;
    }
    """
    )

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+c", "quit_app", "Quit"),
        Binding("ctrl+d", "quit_app", "End session", show=True),
        Binding("ctrl+o", "toggle_history", "History", show=False),
        Binding("ctrl+v", "toggle_voice", "Voice", show=True),
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
    ) -> None:
        super().__init__()
        self._sessions = sessions
        self._on_turn = on_turn
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
        self._voice_mode = voice_mode
        self._listen_fn = listen_fn
        self._speak_fn = speak_fn
        self._greeting = greeting
        self._listening: bool = False

    # ------------------------------------------------------------------
    # Layout

    def compose(self) -> ComposeResult:
        yield RichLog(id="chat", highlight=False, markup=True, wrap=True)
        yield Label(f"  ⟳ {t('thinking')}", id="thinking")
        with Horizontal(id="input-bar"):
            yield Label("❯", id="prompt-label")  # noqa: RUF001
            yield Input(id="input")
        yield Footer()

    def on_mount(self) -> None:
        if self._sessions:
            self.push_screen(SessionScreen(self._sessions), self._on_session_chosen)
        else:
            self._start_chat()

    # ------------------------------------------------------------------
    # Session selection

    def _on_session_chosen(self, choice: str | None) -> None:
        if choice is None:
            self.exit(([], None))
            return
        if choice != _NEW:
            import core

            self._messages = core.load_session_messages(choice)
            self._session_history = list(self._messages)
            self._chosen_session = choice
        self._start_chat()

    # ------------------------------------------------------------------
    # Chat init + history toggle

    def _write_continuing_rule(self, chat: RichLog) -> None:
        hint = "ctrl+o collapse" if self._history_expanded else "ctrl+o expand"
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

    def _write_yana(self, chat: RichLog, content: str, ts: str = "") -> None:
        """YANA: ● + first paragraph inline (no blank line), rest as RichMarkdown."""
        w = self._chat_width()

        parts = content.strip().split("\n\n", 1)
        first_para = parts[0].strip().replace("\n", " ")
        rest = parts[1].strip() if len(parts) > 1 else ""

        ts_str = f"  {ts}" if ts else ""
        ts_len = cell_len(ts_str)
        text_w = max(1, w - self._GUTTER - ts_len)

        lines = textwrap.wrap(first_para, width=text_w, break_long_words=True) or [""]
        first = lines[0]
        gap = max(0, w - self._GUTTER - cell_len(first) - ts_len)
        ts_mk = f"[dim]{escape(ts_str)}[/dim]" if ts_str else ""

        chat.write(f"●  {escape(first)}{' ' * gap}{ts_mk}")
        for line in lines[1:]:
            chat.write(f"   {escape(line)}")

        if rest:
            chat.write(Padding(RichMarkdown(rest), (0, 0, 0, self._GUTTER)))

        chat.write("")

    def _history_line(self, chat: RichLog, m: dict, truncate: int | None = 80) -> None:
        if m["role"] == "user":
            raw = m["content"].replace("\n", " ")
            if truncate is not None:
                text = raw[:truncate] + ("…" if len(raw) > truncate else "")
            else:
                text = raw
            self._write_user_bg(chat, text, ts=self._session_ts())
        else:
            if truncate is None:
                # Expanded: full markdown with icon + ts header
                self._write_yana(chat, m["content"], ts=self._session_ts())
            else:
                # Collapsed: ● icon + truncated text (normal color)
                raw = m["content"].replace("\n", " ")
                text = raw[:truncate] + ("…" if len(raw) > truncate else "")
                chat.write(f"●  {escape(text)}")
                chat.write("")

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
        if self._session_history:
            self._write_history(chat)
        if self._voice_mode:
            self.query_one("#input-bar").display = False
            if self._greeting:
                ts = datetime.now().strftime("%H:%M:%S")
                self._write_yana(chat, self._greeting, ts)
            self._voice_start()
        else:
            self.query_one(Input).focus()

    @work(thread=True)
    def _voice_start(self) -> None:
        """Speaks greeting (blocking) then enters the listen loop."""
        if self._greeting and self._speak_fn:
            self._speak_fn(self._greeting)
        self._voice_loop()

    @work(thread=True)
    def _voice_loop(self) -> None:
        """Shows listening state, blocks on listen_fn(), then triggers a turn."""
        if self._listen_fn is None or self._force_exited:
            return
        self._listening = True
        self.call_from_thread(self._show_thinking, True)
        try:
            text = self._listen_fn()
        except Exception:
            text = ""
        finally:
            self._listening = False
        if text and not self._force_exited:
            self._busy = True
            self._do_turn_voice(text)
        elif not self._force_exited:
            # Nothing heard — listen again
            self._voice_loop()

    @work(thread=True)
    def _do_turn_voice(self, text: str) -> None:
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

        self.call_from_thread(self._show_thinking, False)
        if reply:
            self.call_from_thread(self._write_yana, chat, reply, reply_ts)

        self._busy = False

        if self._speak_fn and reply:
            self._speak_fn(reply)  # blocking — don't listen while speaking

        if not self._force_exited:
            self._voice_loop()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "toggle_voice":
            return self._listen_fn is not None
        return True

    def action_toggle_voice(self) -> None:
        self._voice_mode = not self._voice_mode
        if self._voice_mode:
            self.query_one("#input-bar").display = False
            self._voice_loop()
        else:
            if self._spinner_timer is not None:
                self._spinner_timer.stop()
                self._spinner_timer = None
            self.query_one("#thinking", Label).display = False
            self.query_one("#input-bar").display = True
            self.query_one(Input).focus()

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
            else:
                self._write_yana(chat, m["content"], ts)

    # ------------------------------------------------------------------
    # Input

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._voice_mode:
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
        try:
            reply = self._on_turn(list(self._messages))
        except Exception as exc:
            reply = f"[error: {exc}]"
        reply_ts = datetime.now().strftime("%H:%M:%S")
        self._messages.append({"role": "assistant", "content": reply})
        self._new_messages.append((reply_ts, {"role": "assistant", "content": reply}))

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
            if self._spinner_timer is None:
                self._spinner_timer = self.set_interval(0.1, self._tick_spinner)
        else:
            if self._voice_mode:
                return  # voice mode: spinner always visible
            if self._spinner_timer is not None:
                self._spinner_timer.stop()
                self._spinner_timer = None
            thinking.display = False

    def _tick_spinner(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(self._SPINNER)
        frame = self._SPINNER[self._spinner_idx]
        if self._saving_mode:
            msg = f"{t('saving_memory')}  ·  ctrl+c skip"
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
            self.exit((self._messages, self._chosen_session))
            return
        if self._on_exit is None or not self._messages:
            self.exit((self._messages, self._chosen_session))
            return
        self._saving_mode = True
        self.query_one(Input).disabled = True
        self._show_thinking(True)
        threading.Thread(target=self._save_and_exit, daemon=True).start()

    def _save_and_exit(self) -> None:
        try:
            if self._on_exit is not None:
                self._on_exit(list(self._messages), self._chosen_session)
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
) -> TuiResult:
    """
    Launch the YANA TUI. Blocks until the user exits (and on_exit completes).
    Returns (final_messages, chosen_session_id).
    chosen_session_id is None for new sessions.
    """
    app = YANAApp(
        sessions=sessions,
        on_turn=on_turn,
        on_exit=on_exit,
        voice_mode=voice_mode,
        listen_fn=listen_fn,
        speak_fn=speak_fn,
        greeting=greeting,
    )
    result = app.run(mouse=False)
    return result if result is not None else ([], None)
