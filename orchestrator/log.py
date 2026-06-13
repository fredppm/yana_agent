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

console = Console(highlight=False)

_CONNECTOR = escape("[connector]")


# ---------------------------------------------------------------------------
# Conversation lines
# ---------------------------------------------------------------------------


def user_prompt(ts: str) -> None:
    """Print the 'Você:' prompt prefix, no newline — caller reads input next."""
    console.print(f"[dim]{ts}[/dim] [bold blue]Você:[/bold blue] ", end="")


def yana_prefix(ts: str) -> None:
    """Print the 'YANA:' prefix, no newline — caller streams or prints reply next."""
    console.print(f"[dim]{ts}[/dim] [bold cyan]YANA:[/bold cyan] ", end="")


def yana_thinking(ts: str) -> None:
    """Overwrite-able 'pensando...' indicator."""
    console.print(f"[dim]{ts}[/dim] [bold cyan]YANA:[/bold cyan] [dim]pensando...[/dim]", end="\r")


def yana_response(text: str, markdown: bool = True) -> None:
    """Print YANA's reply. In text mode renders Markdown (bold, italic, etc.)."""
    if markdown and text:
        console.print(Markdown(text), end="")
    elif text:
        console.print(text, end="")


# ---------------------------------------------------------------------------
# Connector / tool lines
# ---------------------------------------------------------------------------


def connector_ok(ts: str, instance: str, op: str) -> None:
    console.print(f"\n[dim]{ts}[/dim] [green]{_CONNECTOR}[/green] {instance}/{op}")


def connector_err(ts: str, instance: str, op: str, error: str) -> None:
    console.print(f"\n[dim]{ts}[/dim] [red]{_CONNECTOR}[/red] {instance}/{op} [red]ERRO:[/red] {error}")


# ---------------------------------------------------------------------------
# Session / system lines
# ---------------------------------------------------------------------------


def session_end(session_id: str) -> None:
    console.print(f"[dim][sessão: {session_id}][/dim]")


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
