"""
log.py — YANA console output helper.

Single Console instance so colour state is consistent across all modules.
All runtime prints should go through here instead of raw print().

Colour legend:
  dim            — timestamps and low-priority metadata
  bold cyan      — "YANA:" label
  bold blue      — "Você:" label
  green          — connector calls (success)
  red            — errors
  yellow         — warnings / rate-limit notices
"""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from strings import t

console = Console(highlight=False)

_CONNECTOR = escape("[connector]")

# ---------------------------------------------------------------------------
# Text UI mode state
# ---------------------------------------------------------------------------

_text_ui: bool = False


def configure_text_ui(enabled: bool) -> None:
    """Enable the rich text interface (date separators, BG speaker identity)."""
    global _text_ui
    _text_ui = enabled


def _ts(ts: str) -> str:
    """Return HH:MM:SS in text UI (strip milliseconds), or full ts in voice mode."""
    return ts[:8] if _text_ui else ts


# ---------------------------------------------------------------------------
# Conversation lines
# ---------------------------------------------------------------------------


def text_date_separator(date_str: str, session_name: str = "") -> None:
    """Print a date separator line — text UI only."""
    label = date_str + (f" · {session_name}" if session_name else "")
    console.rule(f"[dim]{label}[/dim]", style="dim")


def user_prompt(ts: str) -> None:
    """Print the user input prefix — no newline, caller reads input next."""
    if _text_ui:
        console.print(f"[dim]{_ts(ts)}[/dim]  ", end="")
    else:
        console.print(f"[dim]{ts}[/dim] [bold blue]{t('user_label')}:[/bold blue] ", end="")


def yana_prefix(ts: str) -> None:
    """Print the YANA reply prefix — no newline, caller prints reply next."""
    if _text_ui:
        console.print(f"[dim]{_ts(ts)}[/dim]  ", end="")
    else:
        console.print(f"[dim]{ts}[/dim] [bold cyan]YANA:[/bold cyan] ", end="")


def yana_thinking(ts: str) -> None:
    """Overwrite-able thinking indicator."""
    if _text_ui:
        console.print(f"[dim]{_ts(ts)}[/dim]  [dim]⟳ {t('thinking')}[/dim]", end="\r")
    else:
        console.print(f"[dim]{ts}[/dim] [bold cyan]YANA:[/bold cyan] [dim]{t('thinking')}[/dim]", end="\r")


def user_input_echo(ts: str, text: str) -> None:
    """Reprint user's input line with BG highlight (text UI only)."""
    console.print(f"[dim]{ts}[/dim]  [on color(238)] {escape(text)} [/on color(238)]")


def yana_response(text: str, markdown: bool = True) -> None:
    """Print YANA's reply. Renders Markdown in text UI; plain text in voice mode."""
    if markdown and text:
        console.print(Markdown(text.rstrip()), end="")
    elif text:
        console.print(text.rstrip(), end="")
    if _text_ui:
        console.print()  # ensure clean newline after response


# ---------------------------------------------------------------------------
# Connector / tool lines
# ---------------------------------------------------------------------------


def connector_ok(ts: str, instance: str, op: str) -> None:
    console.print(f"\n[dim]{ts}[/dim] [green]{_CONNECTOR}[/green] {instance}/{op}")


def connector_err(ts: str, instance: str, op: str, error: str) -> None:
    console.print(
        f"\n[dim]{ts}[/dim] [red]{_CONNECTOR}[/red] {instance}/{op} [red]ERRO:[/red] {error}"
    )


# ---------------------------------------------------------------------------
# Session / system lines
# ---------------------------------------------------------------------------


def session_end(session_id: str) -> None:
    console.print(f"[dim][{t('session_label')}: {session_id}][/dim]")


def pulse_start(task: str) -> None:
    console.print(f"[dim][PULSE][/dim] task={task}")


def pulse_skip(reason: str) -> None:
    console.print(f"[dim][PULSE][/dim] [yellow]{reason}[/yellow]")


def separator() -> None:
    console.rule("[dim]YANA[/dim]", style="dim")


def error(msg: str) -> None:
    console.print(f"[red]{msg}[/red]")


def warn(msg: str) -> None:
    console.print(f"[yellow]{msg}[/yellow]")


def info(msg: str) -> None:
    console.print(f"[dim]{msg}[/dim]")
