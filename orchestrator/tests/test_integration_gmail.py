"""
Integration tests for GmailMCPConnector.

These tests hit the real Gmail API via the configured MCP server.
They require a working Gmail MCP server and Google OAuth credentials.

First-time setup:
  1. Choose and install a Gmail MCP server (see connectors.yaml for mcp_command).
     Recommended: uvx mcp-gmail (no local install needed)

  2. Create Google OAuth credentials:
     - Go to https://console.cloud.google.com/
     - Create a project → Enable Gmail API
     - Create OAuth 2.0 credentials (Desktop app) → download JSON
     - Save to ~/.yana/google_credentials.json

  3. Run auth once to save the token:
     The first call will open a browser for OAuth consent.
     Token saved to ~/.yana/tokens/gmail_fred_personal.json automatically.

Run:
    cd orchestrator
    pytest -m integration tests/test_integration_gmail.py -v

    # Specific account:
    pytest -m integration tests/test_integration_gmail.py -v -k "personal"
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import connectors_setup


@pytest.fixture(scope="module")
def registry():
    return connectors_setup.build_registry()


# ---------------------------------------------------------------------------
# gmail_fred_personal
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_personal_unread_important_returns_list(registry):
    result = registry.call("gmail_fred_personal", "unread_important")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)


@pytest.mark.integration
def test_personal_unread_important_email_shape(registry):
    result = registry.call("gmail_fred_personal", "unread_important")
    assert result.ok is True
    for email in result.data:
        assert "id" in email
        assert "subject" in email
        assert "from" in email
        assert "snippet" in email


@pytest.mark.integration
def test_personal_search_returns_list(registry):
    result = registry.call("gmail_fred_personal", "search", {"query": "in:inbox"})
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)


@pytest.mark.integration
def test_personal_search_with_sender_query(registry):
    """Smoke test: search by sender returns list (may be empty — that's fine)."""
    result = registry.call("gmail_fred_personal", "search", {"query": "from:noreply@github.com"})
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)


@pytest.mark.integration
def test_personal_contract_has_all_operations(registry):
    contract = registry.load_contract("gmail_fred_personal")
    query_names = {q["name"] for q in contract["queries"]}
    command_names = {c["name"] for c in contract["commands"]}
    assert "unread_important" in query_names
    assert "search" in query_names
    assert "send_message" in command_names
    assert "mark_read" in command_names
    assert "label" in command_names


# ---------------------------------------------------------------------------
# gmail_fred_work (same assertions, different account)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_work_unread_important_returns_list(registry):
    result = registry.call("gmail_fred_work", "unread_important")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)


@pytest.mark.integration
def test_work_search_returns_list(registry):
    result = registry.call("gmail_fred_work", "search", {"query": "in:inbox"})
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)
