"""
Contract tests for GmailMCPConnector.

These tests define the interface contract that any backend (current MCP
implementation or future alternatives) must satisfy. They do NOT test
Gmail API integration — only operation signatures, output shapes, and
error envelopes.

The MCP session is mocked at _call_tool() so no real server process is needed.

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

with patch("asyncio.new_event_loop"), patch("threading.Thread"):
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]

GmailMCPConnector = _mod.GmailMCPConnector

# ---------------------------------------------------------------------------
# Shared raw MCP response payloads
# ---------------------------------------------------------------------------

_RAW_EMAIL = {
    "id": "msg_abc123",
    "threadId": "thread_xyz789",
    "from": "joao@empresa.com",
    "subject": "Proposta de parceria",
    "date": "2026-06-14T09:30:00Z",
    "snippet": "Olá Fred, gostaria de discutir uma possível parceria...",
    "body": "Olá Fred,\n\nGostaria de discutir uma possível parceria com vocês.",
}

_RAW_EMAIL_2 = {
    "id": "msg_def456",
    "threadId": "thread_uvw321",
    "from": "contador@escritorio.com.br",
    "subject": "IR 2026 — documentos pendentes",
    "date": "2026-06-13T18:00:00Z",
    "snippet": "Prezado Fred, precisamos dos comprovantes...",
    "body": "Prezado Fred,\n\nPrecisamos dos comprovantes de renda do primeiro trimestre.",
}

_EMAILS_RESPONSE = {"emails": [_RAW_EMAIL, _RAW_EMAIL_2]}
_EMAILS_LIST_RESPONSE = [_RAW_EMAIL]
_EMAILS_EMPTY: dict[str, Any] = {"emails": []}

_EXPECTED_EMAIL_KEYS = {
    "id", "thread_id", "from", "subject", "date", "snippet", "body_text"
}


def _make_connector() -> Any:
    with (
        patch("asyncio.new_event_loop") as mock_loop,
        patch("threading.Thread"),
    ):
        mock_loop.return_value = MagicMock()
        connector = GmailMCPConnector.__new__(GmailMCPConnector)
        connector._loop = MagicMock()
        connector._thread = MagicMock()
        connector._session = MagicMock()
        connector._exit_stack = MagicMock()
        connector._mcp_command = ["uvx", "mcp-gmail"]
        connector._env = {}
        connector._TOOLS = GmailMCPConnector._TOOLS
    return connector


# ---------------------------------------------------------------------------
# CAP-1: Operation discovery — all expected operations are registered
# ---------------------------------------------------------------------------


def test_unread_important_is_query():
    assert "unread_important" in GmailMCPConnector._operations
    assert GmailMCPConnector._operations["unread_important"].kind == "query"


def test_search_is_query():
    assert "search" in GmailMCPConnector._operations
    assert GmailMCPConnector._operations["search"].kind == "query"


def test_send_message_is_command():
    assert "send_message" in GmailMCPConnector._operations
    assert GmailMCPConnector._operations["send_message"].kind == "command"


def test_mark_read_is_command():
    assert "mark_read" in GmailMCPConnector._operations
    assert GmailMCPConnector._operations["mark_read"].kind == "command"


def test_label_is_command():
    assert "label" in GmailMCPConnector._operations
    assert GmailMCPConnector._operations["label"].kind == "command"


def test_new_important_email_is_event():
    assert "new_important_email" in GmailMCPConnector._operations
    assert GmailMCPConnector._operations["new_important_email"].kind == "event"


# ---------------------------------------------------------------------------
# CAP-1: All operations have AI-readable descriptions
# ---------------------------------------------------------------------------


def test_all_operations_have_descriptions():
    for name, op in GmailMCPConnector._operations.items():
        assert op.description, f"Operation '{name}' has no description"


# ---------------------------------------------------------------------------
# CAP-5: Return schemas
# ---------------------------------------------------------------------------


def test_unread_important_returns_list():
    assert GmailMCPConnector._operations["unread_important"].returns.type == "list"


def test_search_returns_list():
    assert GmailMCPConnector._operations["search"].returns.type == "list"


def test_send_message_returns_boolean():
    assert GmailMCPConnector._operations["send_message"].returns.type == "boolean"


def test_mark_read_returns_boolean():
    assert GmailMCPConnector._operations["mark_read"].returns.type == "boolean"


def test_label_returns_boolean():
    assert GmailMCPConnector._operations["label"].returns.type == "boolean"


# ---------------------------------------------------------------------------
# Output shape — unread_important
# ---------------------------------------------------------------------------


def test_unread_important_email_keys():
    connector = _make_connector()
    connector._call_tool = MagicMock(return_value=_EMAILS_RESPONSE)

    result = connector.call("unread_important")

    assert result.ok is True
    assert isinstance(result.data, list)
    assert len(result.data) == 2
    for email in result.data:
        assert set(email.keys()) == _EXPECTED_EMAIL_KEYS


def test_unread_important_maps_thread_id():
    connector = _make_connector()
    connector._call_tool = MagicMock(return_value=_EMAILS_RESPONSE)

    result = connector.call("unread_important")

    assert result.data[0]["thread_id"] == "thread_xyz789"


def test_unread_important_empty_when_no_emails():
    connector = _make_connector()
    connector._call_tool = MagicMock(return_value=_EMAILS_EMPTY)

    result = connector.call("unread_important")

    assert result.ok is True
    assert result.data == []


def test_unread_important_accepts_list_response():
    """Some MCP servers return a plain list instead of {"emails": [...]}."""
    connector = _make_connector()
    connector._call_tool = MagicMock(return_value=_EMAILS_LIST_RESPONSE)

    result = connector.call("unread_important")

    assert result.ok is True
    assert len(result.data) == 1


def test_unread_important_max_results_is_optional():
    connector = _make_connector()
    connector._call_tool = MagicMock(return_value=_EMAILS_EMPTY)

    result = connector.call("unread_important")  # no params
    assert result.ok is True


def test_unread_important_passes_primary_query():
    connector = _make_connector()
    mock_call = MagicMock(return_value=_EMAILS_EMPTY)
    connector._call_tool = mock_call

    connector.call("unread_important")

    args = mock_call.call_args[0][1]
    assert "category:primary" in args["query"]
    assert "is:unread" in args["query"]


# ---------------------------------------------------------------------------
# Output shape — search
# ---------------------------------------------------------------------------


def test_search_returns_list_of_emails():
    connector = _make_connector()
    connector._call_tool = MagicMock(return_value=_EMAILS_RESPONSE)

    result = connector.call("search", {"query": "from:contador@escritorio.com.br"})

    assert result.ok is True
    assert isinstance(result.data, list)
    for email in result.data:
        assert set(email.keys()) == _EXPECTED_EMAIL_KEYS


def test_search_empty_when_no_results():
    connector = _make_connector()
    connector._call_tool = MagicMock(return_value=_EMAILS_EMPTY)

    result = connector.call("search", {"query": "from:nobody@nowhere.com"})

    assert result.ok is True
    assert result.data == []


def test_search_passes_query_to_mcp():
    connector = _make_connector()
    mock_call = MagicMock(return_value=_EMAILS_EMPTY)
    connector._call_tool = mock_call

    connector.call("search", {"query": "from:joao@empresa.com after:2025-01-01"})

    args = mock_call.call_args[0][1]
    assert args["query"] == "from:joao@empresa.com after:2025-01-01"


# ---------------------------------------------------------------------------
# Output shape — _format_email field normalization
# ---------------------------------------------------------------------------


def test_format_email_handles_thread_id_variants():
    """Connector must handle both 'threadId' (Gmail API) and 'thread_id' (some servers)."""
    connector = _make_connector()

    raw_camel = {"id": "1", "threadId": "t1", "from": "a@b.com", "subject": "s",
                 "date": "d", "snippet": "snip", "body": "text"}
    raw_snake = {"id": "2", "thread_id": "t2", "from": "a@b.com", "subject": "s",
                 "date": "d", "snippet": "snip", "body": "text"}

    assert connector._format_email(raw_camel)["thread_id"] == "t1"
    assert connector._format_email(raw_snake)["thread_id"] == "t2"


def test_format_email_discards_html_prefers_plain_body():
    """HTML is not part of the contract — body_text must be plain text only."""
    connector = _make_connector()

    raw = {
        "id": "1", "threadId": "t1", "from": "a@b.com", "subject": "s",
        "date": "d", "snippet": "snip",
        "body_text": "plain text",
        "htmlBody": "<html>should not appear</html>",
    }
    result = connector._format_email(raw)

    assert result["body_text"] == "plain text"
    assert "htmlBody" not in result


def test_format_email_empty_subject_defaults_to_empty_string():
    connector = _make_connector()
    raw = {"id": "1", "threadId": "t1", "from": "a@b.com", "date": "d",
           "snippet": "snip", "body": "text"}
    result = connector._format_email(raw)
    assert result["subject"] == ""


# ---------------------------------------------------------------------------
# CAP-5: Validation — required params
# ---------------------------------------------------------------------------


def test_search_requires_query_param():
    connector = _make_connector()
    connector._call_tool = MagicMock(return_value=_EMAILS_EMPTY)

    result = connector.call("search")  # missing required 'query'
    assert result.ok is False
    assert result.error == "validation_error"


def test_send_message_requires_all_params():
    connector = _make_connector()
    connector._call_tool = MagicMock(return_value=None)

    result = connector.call("send_message", {"to": "a@b.com", "subject": "Hi"})  # missing body
    assert result.ok is False
    assert result.error == "validation_error"


def test_mark_read_requires_email_id():
    connector = _make_connector()
    connector._call_tool = MagicMock(return_value=None)

    result = connector.call("mark_read")
    assert result.ok is False
    assert result.error == "validation_error"


def test_label_requires_both_params():
    connector = _make_connector()
    connector._call_tool = MagicMock(return_value=None)

    result = connector.call("label", {"email_id": "msg_abc123"})  # missing label_name
    assert result.ok is False
    assert result.error == "validation_error"


# ---------------------------------------------------------------------------
# CAP-5: Error envelope
# ---------------------------------------------------------------------------


def test_unread_important_auth_error():
    connector = _make_connector()
    connector._call_tool = MagicMock(side_effect=PermissionError)

    result = connector.call("unread_important")

    assert result.ok is False
    assert result.error == "auth"


def test_unread_important_timeout_error():
    connector = _make_connector()
    connector._call_tool = MagicMock(side_effect=TimeoutError)

    result = connector.call("unread_important")

    assert result.ok is False
    assert result.error == "timeout"


def test_send_message_auth_error():
    connector = _make_connector()
    connector._call_tool = MagicMock(side_effect=PermissionError)

    result = connector.call("send_message", {
        "to": "joao@empresa.com",
        "subject": "Re: Proposta",
        "body": "Olá João, podemos marcar uma call?",
    })

    assert result.ok is False
    assert result.error == "auth"


def test_search_timeout_error():
    connector = _make_connector()
    connector._call_tool = MagicMock(side_effect=TimeoutError)

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
