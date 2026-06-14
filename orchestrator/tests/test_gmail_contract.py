"""
Contract tests for GmailConnector.

These tests define the interface contract that any backend must satisfy.
They do NOT test Gmail API integration — only operation signatures, output
shapes, and error envelopes.

The Gmail service is mocked at _svc() so no real API calls are made.

Run with: python -m pytest tests/test_gmail_contract.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_CONNECTOR_FILE = Path(__file__).parent.parent.parent / "connectors" / "gmail.py"
_spec = importlib.util.spec_from_file_location("gmail", _CONNECTOR_FILE)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

GmailConnector = _mod.GmailConnector

# ---------------------------------------------------------------------------
# Shared Gmail API-format message payloads
# ---------------------------------------------------------------------------

def _make_raw_message(
    msg_id: str,
    thread_id: str,
    from_: str,
    subject: str,
    date: str,
    snippet: str,
    body_text: str,
) -> dict:
    """Build a minimal Gmail API message object."""
    import base64
    encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()
    return {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": snippet,
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": from_},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date},
            ],
            "body": {"data": encoded_body},
        },
    }


_RAW_MSG_1 = _make_raw_message(
    msg_id="msg_abc123",
    thread_id="thread_xyz789",
    from_="joao@empresa.com",
    subject="Proposta de parceria",
    date="Sat, 14 Jun 2026 09:30:00 +0000",
    snippet="Olá Fred, gostaria de discutir uma possível parceria...",
    body_text="Olá Fred,\n\nGostaria de discutir uma possível parceria com vocês.",
)

_RAW_MSG_2 = _make_raw_message(
    msg_id="msg_def456",
    thread_id="thread_uvw321",
    from_="contador@escritorio.com.br",
    subject="IR 2026 — documentos pendentes",
    date="Fri, 13 Jun 2026 18:00:00 +0000",
    snippet="Prezado Fred, precisamos dos comprovantes...",
    body_text="Prezado Fred,\n\nPrecisamos dos comprovantes de renda do primeiro trimestre.",
)

_EXPECTED_EMAIL_KEYS = {
    "id", "thread_id", "from", "subject", "date", "snippet", "body_text"
}


def _make_connector() -> Any:
    """Return a GmailConnector with no real credentials, service not yet built."""
    connector = GmailConnector.__new__(GmailConnector)
    connector._credentials_file = Path("/fake/credentials.json")
    connector._token_file = Path("/fake/token.json")
    connector._service = None
    return connector


def _mock_svc(connector: Any, messages: list[dict] | None = None) -> MagicMock:
    """Attach a mock Gmail service that returns the given messages on list+get."""
    mock_svc = MagicMock()
    connector._service = mock_svc

    if messages is not None:
        stubs = [{"id": m["id"], "threadId": m["threadId"]} for m in messages]
        mock_svc.users().messages().list().execute.return_value = {"messages": stubs}

        # get() returns the matching full message by ID
        msg_map = {m["id"]: m for m in messages}
        def _get_execute(msg_id):
            mock = MagicMock()
            mock.execute.return_value = msg_map[msg_id]
            return mock
        mock_svc.users().messages().get.side_effect = (
            lambda userId, id, format: _get_execute(id)
        )

    return mock_svc


# ---------------------------------------------------------------------------
# CAP-1: Operation discovery — all expected operations are registered
# ---------------------------------------------------------------------------


def test_unread_important_is_query():
    assert "unread_important" in GmailConnector._operations
    assert GmailConnector._operations["unread_important"].kind == "query"


def test_search_is_query():
    assert "search" in GmailConnector._operations
    assert GmailConnector._operations["search"].kind == "query"


def test_send_message_is_command():
    assert "send_message" in GmailConnector._operations
    assert GmailConnector._operations["send_message"].kind == "command"


def test_mark_read_is_command():
    assert "mark_read" in GmailConnector._operations
    assert GmailConnector._operations["mark_read"].kind == "command"


def test_label_is_command():
    assert "label" in GmailConnector._operations
    assert GmailConnector._operations["label"].kind == "command"


def test_new_important_email_is_event():
    assert "new_important_email" in GmailConnector._operations
    assert GmailConnector._operations["new_important_email"].kind == "event"


# ---------------------------------------------------------------------------
# CAP-1: All operations have AI-readable descriptions
# ---------------------------------------------------------------------------


def test_all_operations_have_descriptions():
    for name, op in GmailConnector._operations.items():
        assert op.description, f"Operation '{name}' has no description"


# ---------------------------------------------------------------------------
# CAP-5: Return schemas
# ---------------------------------------------------------------------------


def test_unread_important_returns_list():
    assert GmailConnector._operations["unread_important"].returns.type == "list"


def test_search_returns_list():
    assert GmailConnector._operations["search"].returns.type == "list"


def test_send_message_returns_boolean():
    assert GmailConnector._operations["send_message"].returns.type == "boolean"


def test_mark_read_returns_boolean():
    assert GmailConnector._operations["mark_read"].returns.type == "boolean"


def test_label_returns_boolean():
    assert GmailConnector._operations["label"].returns.type == "boolean"


# ---------------------------------------------------------------------------
# Output shape — unread_important
# ---------------------------------------------------------------------------


def test_unread_important_email_keys():
    connector = _make_connector()
    _mock_svc(connector, [_RAW_MSG_1, _RAW_MSG_2])

    result = connector.call("unread_important")

    assert result.ok is True
    assert isinstance(result.data, list)
    assert len(result.data) == 2
    for email in result.data:
        assert set(email.keys()) == _EXPECTED_EMAIL_KEYS


def test_unread_important_maps_thread_id():
    connector = _make_connector()
    _mock_svc(connector, [_RAW_MSG_1])

    result = connector.call("unread_important")

    assert result.data[0]["thread_id"] == "thread_xyz789"


def test_unread_important_empty_when_no_emails():
    connector = _make_connector()
    mock_svc = MagicMock()
    connector._service = mock_svc
    mock_svc.users().messages().list().execute.return_value = {"messages": []}

    result = connector.call("unread_important")

    assert result.ok is True
    assert result.data == []


def test_unread_important_empty_when_list_missing_key():
    """Gmail API omits 'messages' key when inbox is empty."""
    connector = _make_connector()
    mock_svc = MagicMock()
    connector._service = mock_svc
    mock_svc.users().messages().list().execute.return_value = {}

    result = connector.call("unread_important")

    assert result.ok is True
    assert result.data == []


def test_unread_important_max_results_is_optional():
    connector = _make_connector()
    mock_svc = MagicMock()
    connector._service = mock_svc
    mock_svc.users().messages().list().execute.return_value = {}

    result = connector.call("unread_important")
    assert result.ok is True


def test_unread_important_passes_primary_query():
    connector = _make_connector()
    mock_svc = MagicMock()
    connector._service = mock_svc
    mock_svc.users().messages().list().execute.return_value = {}

    connector.call("unread_important")

    call_kwargs = mock_svc.users().messages().list.call_args
    q = call_kwargs.kwargs.get("q") or call_kwargs.args[0] if call_kwargs.args else ""
    # list() is called with keyword args
    _, kwargs = call_kwargs
    assert "category:primary" in kwargs.get("q", "")
    assert "is:unread" in kwargs.get("q", "")


# ---------------------------------------------------------------------------
# Output shape — search
# ---------------------------------------------------------------------------


def test_search_returns_list_of_emails():
    connector = _make_connector()
    _mock_svc(connector, [_RAW_MSG_1, _RAW_MSG_2])

    result = connector.call("search", {"query": "from:contador@escritorio.com.br"})

    assert result.ok is True
    assert isinstance(result.data, list)
    for email in result.data:
        assert set(email.keys()) == _EXPECTED_EMAIL_KEYS


def test_search_empty_when_no_results():
    connector = _make_connector()
    mock_svc = MagicMock()
    connector._service = mock_svc
    mock_svc.users().messages().list().execute.return_value = {}

    result = connector.call("search", {"query": "from:nobody@nowhere.com"})

    assert result.ok is True
    assert result.data == []


def test_search_passes_query_to_api():
    connector = _make_connector()
    mock_svc = MagicMock()
    connector._service = mock_svc
    mock_svc.users().messages().list().execute.return_value = {}

    connector.call("search", {"query": "from:joao@empresa.com after:2025-01-01"})

    _, kwargs = mock_svc.users().messages().list.call_args
    assert kwargs.get("q") == "from:joao@empresa.com after:2025-01-01"


# ---------------------------------------------------------------------------
# Output shape — _format_message field normalization
# ---------------------------------------------------------------------------


def test_format_message_body_decoded():
    connector = _make_connector()
    result = connector._format_message(_RAW_MSG_1)
    assert "Gostaria de discutir" in result["body_text"]


def test_format_message_empty_subject_defaults_to_empty_string():
    import base64
    connector = _make_connector()
    raw = {
        "id": "1", "threadId": "t1", "snippet": "snip",
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "From", "value": "a@b.com"}],
            "body": {"data": base64.urlsafe_b64encode(b"text").decode()},
        },
    }
    result = connector._format_message(raw)
    assert result["subject"] == ""


def test_format_message_multipart_prefers_plain_text():
    """Multipart messages: plain text extracted, HTML ignored."""
    import base64
    connector = _make_connector()
    plain = base64.urlsafe_b64encode(b"plain body").decode()
    html = base64.urlsafe_b64encode(b"<html>html body</html>").decode()
    raw = {
        "id": "1", "threadId": "t1", "snippet": "",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": plain}, "headers": []},
                {"mimeType": "text/html", "body": {"data": html}, "headers": []},
            ],
        },
    }
    result = connector._format_message(raw)
    assert result["body_text"] == "plain body"
    assert "<html>" not in result["body_text"]


# ---------------------------------------------------------------------------
# CAP-5: Validation — required params
# ---------------------------------------------------------------------------


def test_search_requires_query_param():
    connector = _make_connector()
    result = connector.call("search")  # missing required 'query'
    assert result.ok is False
    assert result.error == "validation_error"


def test_send_message_requires_all_params():
    connector = _make_connector()
    result = connector.call("send_message", {"to": "a@b.com", "subject": "Hi"})  # missing body
    assert result.ok is False
    assert result.error == "validation_error"


def test_mark_read_requires_email_id():
    connector = _make_connector()
    result = connector.call("mark_read")
    assert result.ok is False
    assert result.error == "validation_error"


def test_label_requires_both_params():
    connector = _make_connector()
    result = connector.call("label", {"email_id": "msg_abc123"})  # missing label_name
    assert result.ok is False
    assert result.error == "validation_error"


# ---------------------------------------------------------------------------
# CAP-5: Error envelope
# ---------------------------------------------------------------------------


def test_unread_important_auth_error():
    connector = _make_connector()
    with patch.object(connector, "_svc", side_effect=PermissionError):
        result = connector.call("unread_important")
    assert result.ok is False
    assert result.error == "auth"


def test_unread_important_timeout_error():
    connector = _make_connector()
    with patch.object(connector, "_svc", side_effect=TimeoutError):
        result = connector.call("unread_important")
    assert result.ok is False
    assert result.error == "timeout"


def test_send_message_auth_error():
    connector = _make_connector()
    with patch.object(connector, "_svc", side_effect=PermissionError):
        result = connector.call("send_message", {
            "to": "joao@empresa.com",
            "subject": "Re: Proposta",
            "body": "Olá João, podemos marcar uma call?",
        })
    assert result.ok is False
    assert result.error == "auth"


def test_search_timeout_error():
    connector = _make_connector()
    with patch.object(connector, "_svc", side_effect=TimeoutError):
        result = connector.call("search", {"query": "from:alguem@empresa.com"})
    assert result.ok is False
    assert result.error == "timeout"


# ---------------------------------------------------------------------------
# Contract — events are not callable via call()
# ---------------------------------------------------------------------------


def test_new_important_email_is_not_callable_via_call():
    connector = _make_connector()
    result = connector.call("new_important_email")
    assert result.ok is False
    assert result.error == "validation_error"
