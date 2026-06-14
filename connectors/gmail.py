"""
connectors/gmail.py — GmailConnector.

Direct Gmail API connector using google-api-python-client.
No MCP subprocess — reads and sends email via the Gmail REST API.

Gmail Primary inbox is used as the importance oracle — no custom filtering logic
inside the connector. YANA decides what matters based on sanctum relationship
context (BOND.md, MEMORY.md).

Setup:
  1. Go to https://console.cloud.google.com/, enable Gmail API, create OAuth 2.0
     credentials (Desktop app), download JSON.
  2. Save to the path configured as credentials_file (default: ~/.yana/google_credentials.json).
  3. Register in orchestrator/config/connectors.yaml:

       - type: GmailConnector
         id: gmail_fred_personal
         name: "Gmail pessoal do Fred"
         owner: fred
         config:
           credentials_file: "~/.yana/google_credentials.json"
           token_file: "~/.yana/tokens/gmail_fred_personal.json"

  On first YANA startup, a browser window opens for OAuth consent.
  The token is saved to token_file — no browser needed on subsequent runs.

  Multiple accounts: register one instance per account with separate token_files.

send_message uses a generic name intentionally — first implementation of a future
CommunicationsConnector abstraction (see issue #20).
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from connectors import Connector, command, event, query

_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailConnector(Connector):
    connector_description = "Gmail email access — unread important, search, send, label"

    def __init__(
        self,
        credentials_file: str | None = None,
        token_file: str | None = None,
    ) -> None:
        self._credentials_file = Path(
            credentials_file or "~/.yana/google_credentials.json"
        ).expanduser()
        self._token_file = Path(
            token_file or "~/.yana/tokens/gmail.json"
        ).expanduser()
        self._service = None  # lazy — built on first call

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
        return self._fetch_messages(
            "in:inbox is:unread category:primary",
            max_results=max_results,
        )

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
        return self._fetch_messages(query)

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
        msg = MIMEText(body)
        msg["to"] = to
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        self._svc().users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        return True

    @command(
        description="Mark an email as read by its ID",
        params={"email_id": {"type": "string"}},
        returns={"type": "boolean"},
    )
    def mark_read(self, email_id: str) -> bool:
        self._svc().users().messages().modify(
            userId="me",
            id=email_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
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
        label_id = self._resolve_label(label_name)
        self._svc().users().messages().modify(
            userId="me",
            id=email_id,
            body={"addLabelIds": [label_id]},
        ).execute()
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
        if self._token_file.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self._token_file), _SCOPES
                )
            except Exception:
                pass

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    creds = None
            if not creds or not creds.valid:
                if not self._credentials_file.exists():
                    raise PermissionError(
                        f"Gmail credentials not found: {self._credentials_file}\n"
                        "  1. Go to https://console.cloud.google.com/\n"
                        "  2. Enable Gmail API\n"
                        "  3. Create OAuth 2.0 credentials (Desktop app)\n"
                        f"  4. Download JSON and save to: {self._credentials_file}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._credentials_file), _SCOPES
                )
                creds = flow.run_local_server(port=0)
            self._token_file.parent.mkdir(parents=True, exist_ok=True)
            self._token_file.write_text(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    def _fetch_messages(self, gmail_query: str, max_results: int = 10) -> list[dict]:
        svc = self._svc()
        result = svc.users().messages().list(
            userId="me",
            q=gmail_query,
            maxResults=max_results,
        ).execute()
        out = []
        for stub in result.get("messages", []):
            raw = svc.users().messages().get(
                userId="me",
                id=stub["id"],
                format="full",
            ).execute()
            out.append(self._format_message(raw))
        return out

    def _resolve_label(self, label_name: str) -> str:
        """Return label ID for label_name, creating it if necessary."""
        svc = self._svc()
        all_labels = svc.users().labels().list(userId="me").execute()
        for lbl in all_labels.get("labels", []):
            if lbl["name"] == label_name:
                return lbl["id"]
        created = svc.users().labels().create(
            userId="me", body={"name": label_name}
        ).execute()
        return created["id"]

    def _format_message(self, raw: dict) -> dict:
        """Normalize a Gmail API message to the YANA contract shape.

        HTML body is discarded — YANA only receives plain text.
        """
        payload = raw.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        return {
            "id": raw.get("id"),
            "thread_id": raw.get("threadId"),
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": raw.get("snippet", ""),
            "body_text": self._extract_plain_text(payload),
        }

    def _extract_plain_text(self, payload: dict) -> str:
        """Extract plain text body from a message payload, ignoring HTML parts."""
        mime = payload.get("mimeType", "")
        if mime == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            return ""
        for part in payload.get("parts", []):
            text = self._extract_plain_text(part)
            if text:
                return text
        return ""
