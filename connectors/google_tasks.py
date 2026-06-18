"""
connectors/google_tasks.py — GoogleTasks connector.

Requires OAuth2 credentials from Google Cloud Console.
On first run, opens a browser for authorization and saves a token file.
Subsequent runs use the saved token (auto-refreshed when expired).

Setup:
  1. Create OAuth2 credentials at console.cloud.google.com
     (Desktop app type, Tasks API scope)
  2. Download credentials.json
  3. Pass paths when registering the instance:
       registry.add_instance(
           GoogleTasksConnector,
           instance_id="tasks_fred",
           name="Fred's Tasks",
           owner="fred",
           app_credential="~/.yana/google_credentials.json",
           persona_token="~/.yana/tokens/tasks_fred.json",
       )
     Or set GOOGLE_CREDENTIALS_FILE / GOOGLE_TASKS_TOKEN_FILE env vars.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from connectors import Connector, command, query

_SCOPES = ["https://www.googleapis.com/auth/tasks"]

_DEFAULT_TASKLIST = "@default"


class GoogleTasksConnector(Connector):
    connector_description = "Google Tasks — read and manage personal task lists"

    def __init__(
        self,
        app_credential: str | None = None,
        persona_token: str | None = None,
    ) -> None:
        self._app_credential = Path(
            app_credential
            or os.environ.get("GOOGLE_CREDENTIALS_FILE", "~/.yana/google_credentials.json")
        ).expanduser()
        self._persona_token = Path(
            persona_token
            or os.environ.get("GOOGLE_TASKS_TOKEN_FILE", "~/.yana/tokens/google_tasks.json")
        ).expanduser()
        self._service = None  # lazy — built on first call

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @query(
        description="List all task lists owned by the user.",
        returns={"type": "list"},
    )
    def list_tasklists(self) -> list[dict]:
        result = self._svc().tasklists().list().execute()
        return [self._format_tasklist(t) for t in result.get("items", [])]

    @query(
        description=(
            "List tasks in a task list. "
            "tasklist_id defaults to the primary list. "
            "Set show_completed=true to include already-completed tasks."
        ),
        params={
            "tasklist_id": {"type": "string", "required": False},
            "show_completed": {"type": "boolean", "required": False},
        },
        returns={"type": "list"},
    )
    def list_tasks(
        self,
        tasklist_id: str = _DEFAULT_TASKLIST,
        show_completed: bool = False,
    ) -> list[dict]:
        kwargs: dict[str, Any] = {
            "tasklist": tasklist_id,
            "showCompleted": show_completed,
            "showHidden": show_completed,
        }
        result = self._svc().tasks().list(**kwargs).execute()
        return [self._format_task(t) for t in result.get("items", [])]

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @command(
        description="Create a new task. due_iso is an ISO 8601 date string (date only, e.g. 2026-06-15).",
        params={
            "title": {"type": "string"},
            "notes": {"type": "string", "required": False},
            "due_iso": {"type": "string", "required": False},
            "tasklist_id": {"type": "string", "required": False},
        },
        returns={"type": "object"},
    )
    def create_task(
        self,
        title: str,
        notes: str = "",
        due_iso: str = "",
        tasklist_id: str = _DEFAULT_TASKLIST,
    ) -> dict:
        body: dict[str, Any] = {"title": title}
        if notes:
            body["notes"] = notes
        if due_iso:
            # Tasks API expects RFC 3339 — append T00:00:00Z if only a date was given
            body["due"] = due_iso if "T" in due_iso else f"{due_iso}T00:00:00Z"
        result = self._svc().tasks().insert(tasklist=tasklist_id, body=body).execute()
        return self._format_task(result)

    @command(
        description="Mark a task as completed.",
        params={
            "task_id": {"type": "string"},
            "tasklist_id": {"type": "string", "required": False},
        },
        returns={"type": "object"},
    )
    def complete_task(
        self,
        task_id: str,
        tasklist_id: str = _DEFAULT_TASKLIST,
    ) -> dict:
        body = {"status": "completed"}
        result = self._svc().tasks().patch(tasklist=tasklist_id, task=task_id, body=body).execute()
        return self._format_task(result)

    @command(
        description="Update task title, notes, or due date. Only provided fields are changed.",
        params={
            "task_id": {"type": "string"},
            "title": {"type": "string", "required": False},
            "notes": {"type": "string", "required": False},
            "due_iso": {"type": "string", "required": False},
            "tasklist_id": {"type": "string", "required": False},
        },
        returns={"type": "object"},
    )
    def update_task(
        self,
        task_id: str,
        title: str = "",
        notes: str = "",
        due_iso: str = "",
        tasklist_id: str = _DEFAULT_TASKLIST,
    ) -> dict:
        body: dict[str, Any] = {}
        if title:
            body["title"] = title
        if notes:
            body["notes"] = notes
        if due_iso:
            body["due"] = due_iso if "T" in due_iso else f"{due_iso}T00:00:00Z"
        result = self._svc().tasks().patch(tasklist=tasklist_id, task=task_id, body=body).execute()
        return self._format_task(result)

    @command(
        description="Delete a task permanently.",
        params={
            "task_id": {"type": "string"},
            "tasklist_id": {"type": "string", "required": False},
        },
        returns={"type": "boolean"},
    )
    def delete_task(
        self,
        task_id: str,
        tasklist_id: str = _DEFAULT_TASKLIST,
    ) -> bool:
        self._svc().tasks().delete(tasklist=tasklist_id, task=task_id).execute()
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _svc(self):
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def _build_service(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if self._persona_token.exists():
            creds = Credentials.from_authorized_user_file(str(self._persona_token), _SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._app_credential), _SCOPES
                )
                creds = flow.run_local_server(port=0)
            self._persona_token.parent.mkdir(parents=True, exist_ok=True)
            self._persona_token.write_text(creds.to_json())

        return build("tasks", "v1", credentials=creds, cache_discovery=False)

    def _format_tasklist(self, raw: dict) -> dict:
        return {
            "id": raw.get("id"),
            "title": raw.get("title", ""),
        }

    def _format_task(self, raw: dict) -> dict:
        return {
            "id": raw.get("id"),
            "title": raw.get("title", ""),
            "notes": raw.get("notes"),
            "due": raw.get("due"),
            "status": raw.get("status"),  # "needsAction" | "completed"
            "completed_at": raw.get("completed"),
        }
