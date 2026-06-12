"""
connectors/google_calendar.py — GoogleCalendar connector.

Requires OAuth2 credentials from Google Cloud Console.
On first run, opens a browser for authorization and saves a token file.
Subsequent runs use the saved token (auto-refreshed when expired).

Setup:
  1. Create OAuth2 credentials at console.cloud.google.com
     (Desktop app type, Calendar API scope)
  2. Download credentials.json
  3. Pass paths when registering the instance:
       registry.add_instance(
           GoogleCalendarConnector,
           instance_id="calendar_fred",
           name="Fred's Calendar",
           owner="fred",
           credentials_file="~/.yana/google_credentials.json",
           token_file="~/.yana/tokens/calendar_fred.json",
       )
     Or set GOOGLE_CREDENTIALS_FILE / GOOGLE_TOKEN_FILE env vars.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from connectors import Connector, command, event, query

_SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarConnector(Connector):
    connector_description = "Google Calendar events and scheduling — read and create"

    def __init__(
        self,
        credentials_file: str | None = None,
        token_file: str | None = None,
    ) -> None:
        self._credentials_file = Path(
            credentials_file
            or os.environ.get("GOOGLE_CREDENTIALS_FILE", "~/.yana/google_credentials.json")
        ).expanduser()
        self._token_file = Path(
            token_file
            or os.environ.get("GOOGLE_TOKEN_FILE", "~/.yana/tokens/google_calendar.json")
        ).expanduser()
        self._service = None  # lazy — built on first call

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @query(
        description="List calendar events in a time range. Both params are ISO 8601 strings. Omit start_iso to default to now; omit end_iso to default to 7 days from start.",
        params={
            "start_iso": {"type": "string", "required": False},
            "end_iso":   {"type": "string", "required": False},
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
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        start = start_iso or now.isoformat()
        end = end_iso or (now + timedelta(days=7)).isoformat()
        return self._list_events(time_min=start, time_max=end, max_results=max_results)

    @query(
        description="Check whether a time slot is free (no events overlap). Both params are ISO 8601 strings.",
        params={
            "start_iso": {"type": "string"},
            "end_iso":   {"type": "string"},
        },
        returns={"type": "boolean"},
    )
    def is_available(self, start_iso: str, end_iso: str) -> bool:
        events = self._list_events(time_min=start_iso, time_max=end_iso)
        return len(events) == 0

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @command(
        description="Create a new calendar event",
        params={
            "title":     {"type": "string"},
            "start_iso": {"type": "string"},
            "end_iso":   {"type": "string"},
            "notes":     {"type": "string", "required": False},
        },
        returns={"type": "object"},
    )
    def create_event(
        self, title: str, start_iso: str, end_iso: str, notes: str = ""
    ) -> dict:
        body: dict[str, Any] = {
            "summary": title,
            "start": {"dateTime": start_iso},
            "end": {"dateTime": end_iso},
        }
        if notes:
            body["description"] = notes
        result = (
            self._svc()
            .events()
            .insert(calendarId="primary", body=body)
            .execute()
        )
        return self._format_event(result)

    @command(
        description="Cancel an existing event by its ID",
        params={"event_id": {"type": "string"}},
        returns={"type": "boolean"},
    )
    def cancel_event(self, event_id: str) -> bool:
        self._svc().events().delete(calendarId="primary", eventId=event_id).execute()
        return True

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    _POLL_INTERVAL = 60  # seconds between polls

    @event(
        description="New event added to the calendar",
        schema={"type": "object"},
    )
    def on_event_created(self, callback) -> None:  # type: ignore[type-arg]
        """Poll every 60 s; fire callback for any event ID not seen before."""
        def _poll() -> None:
            now = datetime.now(timezone.utc)
            try:
                existing = self._list_events(
                    time_min=now.isoformat(),
                    time_max=(now + timedelta(days=30)).isoformat(),
                )
                known: set[str] = {e["id"] for e in existing if e.get("id")}
            except Exception:
                known = set()

            while True:
                time.sleep(self._POLL_INTERVAL)
                try:
                    now = datetime.now(timezone.utc)
                    events = self._list_events(
                        time_min=now.isoformat(),
                        time_max=(now + timedelta(days=30)).isoformat(),
                    )
                    current: set[str] = {e["id"] for e in events if e.get("id")}
                    for ev in events:
                        if ev.get("id") in (current - known):
                            callback(ev)
                    known = current
                except Exception:
                    pass

        t = threading.Thread(target=_poll, daemon=True, name="gcal-on_event_created")
        t.start()

    @event(
        description="Event starting within the next 15 minutes",
        schema={"type": "object"},
    )
    def on_event_reminder(self, callback) -> None:  # type: ignore[type-arg]
        """Poll every 60 s; fire callback once per event that starts within 15 minutes."""
        def _poll() -> None:
            notified: set[str] = set()
            while True:
                try:
                    now = datetime.now(timezone.utc)
                    upcoming = self._list_events(
                        time_min=now.isoformat(),
                        time_max=(now + timedelta(minutes=16)).isoformat(),
                    )
                    for ev in upcoming:
                        eid = ev.get("id")
                        if eid and eid not in notified:
                            notified.add(eid)
                            callback(ev)
                except Exception:
                    pass
                time.sleep(self._POLL_INTERVAL)

        t = threading.Thread(target=_poll, daemon=True, name="gcal-on_event_reminder")
        t.start()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _svc(self):
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def _build_service(self):
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = None
        if self._token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self._token_file), _SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._credentials_file), _SCOPES
                )
                creds = flow.run_local_server(port=0)
            self._token_file.parent.mkdir(parents=True, exist_ok=True)
            self._token_file.write_text(creds.to_json())

        return build("calendar", "v3", credentials=creds)

    def _list_events(
        self,
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 50,
    ) -> list[dict]:
        kwargs: dict[str, Any] = {
            "calendarId": "primary",
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min:
            kwargs["timeMin"] = time_min
        if time_max:
            kwargs["timeMax"] = time_max

        result = self._svc().events().list(**kwargs).execute()
        return [self._format_event(e) for e in result.get("items", [])]

    def _format_event(self, raw: dict) -> dict:
        return {
            "id":       raw.get("id"),
            "title":    raw.get("summary", ""),
            "start":    raw.get("start", {}).get("dateTime") or raw.get("start", {}).get("date"),
            "end":      raw.get("end", {}).get("dateTime") or raw.get("end", {}).get("date"),
            "location": raw.get("location"),
            "notes":    raw.get("description"),
            "link":     raw.get("htmlLink"),
        }
