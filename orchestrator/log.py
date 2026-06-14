"""
log.py — YANA console output helper (voice mode + single-shot).

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
# Conversation lines
# ---------------------------------------------------------------------------


def user_prompt(ts: str) -> None:
    """Print the user input prefix — no newline, caller reads input next."""
    console.print(f"[dim]{ts}[/dim] [bold blue]{t('user_label')}:[/bold blue] ", end="")


def yana_prefix(ts: str) -> None:
    """Print the YANA reply prefix — no newline, caller prints reply next."""
    console.print(f"[dim]{ts}[/dim] [bold cyan]YANA:[/bold cyan] ", end="")


def yana_thinking(ts: str) -> None:
    """Overwrite-able thinking indicator."""
    console.print(f"[dim]{ts}[/dim] [bold cyan]YANA:[/bold cyan] [dim]{t('thinking')}[/dim]", end="\r")


def yana_response(text: str, markdown: bool = True) -> None:
    """Print YANA's reply. Renders Markdown in text mode; plain text in voice mode."""
    if markdown and text:
        console.print(Markdown(text.rstrip()), end="")
    elif text:
        console.print(text.rstrip(), end="")


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
