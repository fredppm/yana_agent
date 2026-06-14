"""
connectors/google_calendar_mcp.py — GoogleCalendarMCPConnector.

Routes YANA connector calls to mcp-server-google-calendar via the Python MCP SDK.
Declares the same contract as GoogleCalendarConnector so the existing contract
tests pass unchanged with this backend.

Setup:
  1. Install the MCP server:
       pip install "git+https://github.com/guinacio/mcp-google-calendar.git"
  2. On first use, a browser window opens once for OAuth authorization.
     Subsequent runs use the saved token — no browser needed.
  3. Register in orchestrator/config/connectors.yaml:
       - type: GoogleCalendarMCPConnector
         id: calendar_fred
         name: "Agenda do Fred"
         owner: fred
         config:
           credentials_file: "~/.yana/google_credentials.json"
           token_file: "~/.yana/tokens/calendar_fred.json"
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from connectors import Connector, command, query

_LAUNCHER = Path(__file__).parent / "gcal_mcp_launcher.py"
_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def _ensure_gcal_auth(creds_path: Path, token_path: Path) -> None:
    """Ensure a valid OAuth token exists. Opens browser if needed.

    Must be called in the parent process — never inside an MCP subprocess
    whose stdout is wired to the JSONRPC pipe.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError(
            f"Google Calendar auth: missing Google auth libraries ({exc}). "
            "Run: pip install google-auth google-auth-oauthlib"
        ) from exc

    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
        except Exception:
            pass  # corrupt token — re-auth below

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None  # refresh failed — full re-auth

        if not creds or not creds.valid:
            if not creds_path.exists():
                raise PermissionError(
                    f"Google Calendar credentials not found: {creds_path}\n"
                    "  1. Go to https://console.cloud.google.com/\n"
                    "  2. Enable Google Calendar API\n"
                    "  3. Create OAuth 2.0 credentials (Desktop app)\n"
                    f"  4. Download JSON and save to: {creds_path}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), _SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())


class GoogleCalendarMCPConnector(Connector):
    connector_description = "Google Calendar events and scheduling via MCP — read and create"

    def __init__(
        self,
        credentials_file: str | None = None,
        token_file: str | None = None,
    ) -> None:
        creds = Path(credentials_file or "~/.yana/google_credentials.json").expanduser()
        token = Path(token_file or "~/.yana/tokens/google_calendar.json").expanduser()

        # Auth MUST happen here, in YANA's process, before the MCP subprocess starts.
        # The MCP subprocess has its stdout wired to the JSONRPC pipe — any print there
        # breaks the protocol.
        _ensure_gcal_auth(creds, token)

        merged = dict(os.environ)
        merged["GOOGLE_CREDENTIALS_PATH"] = str(creds)
        merged["GOOGLE_TOKEN_PATH"] = str(token)
        self._env = merged

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name=f"gcal-mcp-{id(self)}",
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
        return future.result(timeout=60)  # longer for initial browser auth

    async def _start_session(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command="python",
            args=[str(_LAUNCHER)],
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
        description="List calendar events in a time range. Both params are ISO 8601 strings. Omit start_iso to default to now; omit end_iso to default to 7 days from start.",
        params={
            "start_iso": {"type": "string", "required": False},
            "end_iso": {"type": "string", "required": False},
            "max_results": {"type": "number", "required": False},
        },
        returns={"type": "list"},
    )
    def list_events(
        self,
        start_iso: str | None = None,
        end_iso: str | None = None,
        max_results: int = 50,
    ) -> list[dict]:
        now = datetime.now(UTC)
        start = start_iso or now.isoformat()
        end = end_iso or (now + timedelta(days=7)).isoformat()
        data = self._call_tool(
            "get-events",
            {
                "calendarId": "primary",
                "timeMin": start,
                "timeMax": end,
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
            },
        )
        items = (data or {}).get("items") or []
        return [self._format_event(e) for e in items]

    @query(
        description="Check whether a time slot is free (no events overlap). Both params are ISO 8601 strings.",
        params={
            "start_iso": {"type": "string"},
            "end_iso": {"type": "string"},
        },
        returns={"type": "boolean"},
    )
    def is_available(self, start_iso: str, end_iso: str) -> bool:
        data = self._call_tool(
            "check-availability",
            {
                "items": [{"id": "primary"}],
                "timeMin": start_iso,
                "timeMax": end_iso,
            },
        )
        busy = (data or {}).get("calendars", {}).get("primary", {}).get("busy", [])
        return len(busy) == 0

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @command(
        description="Create a new calendar event",
        params={
            "title": {"type": "string"},
            "start_iso": {"type": "string"},
            "end_iso": {"type": "string"},
            "notes": {"type": "string", "required": False},
        },
        returns={"type": "object"},
    )
    def create_event(self, title: str, start_iso: str, end_iso: str, notes: str = "") -> dict:
        args: dict[str, Any] = {
            "calendarId": "primary",
            "summary": title,
            "start_datetime": start_iso,
            "end_datetime": end_iso,
        }
        if notes:
            args["description"] = notes
        data = self._call_tool("create-event", args)
        if (data or {}).get("status") == "CONFLICT":
            raise RuntimeError("Time slot not available — overlapping event exists")
        event_raw = (data or {}).get("event") or {}
        return self._format_event(event_raw)

    @command(
        description="Cancel an existing event by its ID",
        params={"event_id": {"type": "string"}},
        returns={"type": "boolean"},
    )
    def cancel_event(self, event_id: str) -> bool:
        self._call_tool(
            "delete-event",
            {
                "calendarId": "primary",
                "eventId": event_id,
            },
        )
        return True

    # ------------------------------------------------------------------
    # Response transformer — identical contract shape as Python backend
    # ------------------------------------------------------------------

    def _format_event(self, raw: dict) -> dict:
        return {
            "id": raw.get("id"),
            "title": raw.get("summary", ""),
            "start": raw.get("start", {}).get("dateTime") or raw.get("start", {}).get("date"),
            "end": raw.get("end", {}).get("dateTime") or raw.get("end", {}).get("date"),
            "location": raw.get("location"),
            "notes": raw.get("description"),
            "link": raw.get("htmlLink"),
        }
