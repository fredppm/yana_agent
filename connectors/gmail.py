"""
connectors/gmail.py — GmailMCPConnector.

Routes YANA connector calls to a Gmail MCP server via the Python MCP SDK.
The connector is intentionally dumb: it passes raw email data to YANA, which
applies intelligence (triaging, drafting replies) using sanctum context.

Gmail Primary inbox is used as the importance oracle — no custom filtering logic
inside the connector. YANA decides what matters based on sanctum relationship
context (BOND.md, MEMORY.md).

Setup:
  1. Install a Gmail MCP server, e.g.:
       uvx mcp-gmail   (no local install required)
     or:
       pip install mcp-gmail-server
  2. Run auth once per account (follow the server's instructions to authorize
     via browser OAuth — subsequent runs use the saved token).
  3. Register in orchestrator/config/connectors.yaml:
       - type: GmailMCPConnector
         id: gmail_fred_personal
         name: "Gmail pessoal do Fred"
         owner: fred
         config:
           mcp_command: ["uvx", "mcp-gmail"]
           env:
             GOOGLE_CREDENTIALS_PATH: "~/.yana/google_credentials.json"
             GOOGLE_TOKEN_PATH: "~/.yana/tokens/gmail_fred_personal.json"

  Multiple accounts: register one instance per account with different ids/owners.
  The connector is stateless about identity — isolation is done by config, not code.

Note on MCP tool names: different Gmail MCP servers use different tool names.
The defaults target the common convention. Override _TOOLS at class level to
adapt to any backend without changing business logic.

send_message uses a generic name intentionally — this is the first implementation
of a future CommunicationsConnector abstraction (see issue #20).
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from contextlib import AsyncExitStack
from typing import Any

from connectors import Connector, command, event, query


class GmailMCPConnector(Connector):
    connector_description = "Gmail email access via MCP — unread important, search, send, label"

    # Override to adapt to a different Gmail MCP server's tool names.
    _TOOLS: dict[str, str] = {
        "list_emails": "list_emails",
        "send_email": "send_email",
        "mark_as_read": "mark_as_read",
        "modify_labels": "modify_labels",
    }

    def __init__(
        self,
        mcp_command: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        # mcp_command: command + args to launch the Gmail MCP server via stdio.
        # Defaults to uvx mcp-gmail (no local install needed).
        self._mcp_command = mcp_command or ["uvx", "mcp-gmail"]

        # Merge caller-supplied env into the current process env.
        # Expand ~ in path-like values.
        merged: dict[str, str] = dict(os.environ)
        for k, v in (env or {}).items():
            merged[k] = os.path.expanduser(v) if isinstance(v, str) else v
        self._env = merged

        # Dedicated event loop in a background thread — keeps the MCP session
        # and the Gmail MCP subprocess alive across calls.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name=f"gmail-mcp-{id(self)}",
        )
        self._thread.start()
        self._session: Any = None
        self._exit_stack: AsyncExitStack | None = None
        self._connect()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        self._run(self._start_session())

    def _run(self, coro: Any) -> Any:
        """Submit a coroutine to the background loop and block until done."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=60)

    async def _start_session(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._mcp_command[0],
            args=self._mcp_command[1:],
            env=self._env,
        )
        self._exit_stack = AsyncExitStack()
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        session = ClientSession(read, write)
        self._session = await self._exit_stack.enter_async_context(session)
        await self._session.initialize()

    async def _call_async(self, tool: str, args: dict[str, Any]) -> Any:
        result = await self._session.call_tool(tool, args)
        if not result.content:
            return None
        text = getattr(result.content[0], "text", None)
        if text:
            return json.loads(text)
        return None

    def _call_tool(self, tool: str, args: dict[str, Any]) -> Any:
        return self._run(self._call_async(tool, args))

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @query(
        description=(
            "List unread emails in the Primary inbox. Returns raw email objects "
            "for YANA to triage and prioritize using sanctum context."
        ),
        params={"max_results": {"type": "number", "required": False}},
        returns={"type": "list"},
    )
    def unread_important(self, max_results: int = 10) -> list[dict]:
        data = self._call_tool(self._TOOLS["list_emails"], {
            "query": "in:inbox is:unread category:primary",
            "max_results": max_results,
        })
        items = self._extract_emails(data)
        return [self._format_email(e) for e in items]

    @query(
        description=(
            "Search emails using Gmail query syntax "
            "(e.g. 'from:joao@empresa.com after:2025-01-01'). "
            "Returns matching email objects."
        ),
        params={"query": {"type": "string"}},
        returns={"type": "list"},
    )
    def search(self, query: str) -> list[dict]:
        data = self._call_tool(self._TOOLS["list_emails"], {"query": query})
        items = self._extract_emails(data)
        return [self._format_email(e) for e in items]

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @command(
        description=(
            "Send a message to an email address. Generic name is intentional — "
            "this is the first implementation of a future multi-channel "
            "CommunicationsConnector abstraction (issue #20)."
        ),
        params={
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        returns={"type": "boolean"},
    )
    def send_message(self, to: str, subject: str, body: str) -> bool:
        self._call_tool(self._TOOLS["send_email"], {
            "to": to,
            "subject": subject,
            "body": body,
        })
        return True

    @command(
        description="Mark an email as read by its ID",
        params={"email_id": {"type": "string"}},
        returns={"type": "boolean"},
    )
    def mark_read(self, email_id: str) -> bool:
        self._call_tool(self._TOOLS["mark_as_read"], {"email_id": email_id})
        return True

    @command(
        description="Apply a Gmail label to an email by its ID",
        params={
            "email_id": {"type": "string"},
            "label_name": {"type": "string"},
        },
        returns={"type": "boolean"},
    )
    def label(self, email_id: str, label_name: str) -> bool:
        self._call_tool(self._TOOLS["modify_labels"], {
            "email_id": email_id,
            "add_labels": [label_name],
        })
        return True

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @event(
        description=(
            "Fired when a new email arrives in the Primary inbox. "
            "Payload: formatted email object. "
            "Implemented as polling — called by PULSE scheduler."
        ),
        schema={"type": "object"},
    )
    def new_important_email(self) -> None:
        """Polling-based event handler — PULSE calls unread_important() to check."""

    # ------------------------------------------------------------------
    # Response transformer
    # ------------------------------------------------------------------

    def _extract_emails(self, data: Any) -> list[dict]:
        """Normalize MCP response to a list of raw email dicts.

        Handles both {"emails": [...]} and plain list responses.
        """
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("emails") or []
        return []

    def _format_email(self, raw: dict) -> dict:
        """Normalize a raw MCP email response to the YANA contract shape.

        HTML body is discarded — YANA only receives plain text.
        Handles field name variations across different Gmail MCP server implementations.
        """
        return {
            "id": raw.get("id"),
            "thread_id": raw.get("threadId") or raw.get("thread_id"),
            "from": raw.get("from") or raw.get("sender"),
            "subject": raw.get("subject", ""),
            "date": raw.get("date") or raw.get("internalDate"),
            "snippet": raw.get("snippet", ""),
            "body_text": (
                raw.get("body")
                or raw.get("body_text")
                or raw.get("plainText")
                or ""
            ),
        }
