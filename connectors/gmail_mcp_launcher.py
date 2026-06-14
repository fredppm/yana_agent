"""
connectors/gmail_mcp_launcher.py

Launcher for mcp-google-gmail that:
  1. Reads credential/token paths from env vars set by GmailMCPConnector
  2. Runs Google OAuth flow if no valid token exists (browser opens once)
  3. Saves/refreshes the token
  4. Starts the mcp-google-gmail MCP server

Environment variables (set by GmailMCPConnector.__init__):
  GMAIL_CREDENTIALS_PATH  OAuth2 client credentials JSON (Google Cloud Console)
  GMAIL_TOKEN_PATH        Saved OAuth2 token (auto-created after first browser auth)

OAuth is handled here using google-auth-oauthlib directly, independent of
mcp-google-gmail's internal auth module. This keeps auth consistent across
connector updates and gives clear error messages when credentials are missing.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

_creds_path = Path(
    os.environ.get("GMAIL_CREDENTIALS_PATH", "~/.yana/google_credentials.json")
).expanduser()

_token_path = Path(
    os.environ.get("GMAIL_TOKEN_PATH", "~/.yana/tokens/gmail.json")
).expanduser()


def _authorize() -> None:
    """Ensure a valid OAuth token exists. Opens browser on first run."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        print(
            f"Gmail auth: missing Google auth libraries ({exc}). "
            "Run: pip install google-auth google-auth-oauthlib",
            file=sys.stderr,
        )
        sys.exit(1)

    creds = None

    if _token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(_token_path), _SCOPES)
        except Exception:
            pass  # corrupt token — will re-auth below

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None  # refresh failed — re-auth

        if not creds or not creds.valid:
            if not _creds_path.exists():
                print(
                    f"Gmail auth: credentials file not found: {_creds_path}\n"
                    "  1. Go to https://console.cloud.google.com/\n"
                    "  2. Enable Gmail API\n"
                    "  3. Create OAuth 2.0 credentials (Desktop app)\n"
                    f"  4. Download JSON and save to: {_creds_path}",
                    file=sys.stderr,
                )
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(
                str(_creds_path), _SCOPES
            )
            creds = flow.run_local_server(port=0)

        _token_path.parent.mkdir(parents=True, exist_ok=True)
        _token_path.write_text(creds.to_json())


async def _run() -> None:
    """Start the mcp-google-gmail MCP server after auth."""
    try:
        import mcp_google_gmail.server as _server_mod  # type: ignore[import]
    except ImportError:
        print(
            "Gmail MCP: mcp-google-gmail not installed. "
            "Run: pip install mcp-google-gmail  or use uvx mcp-google-gmail@latest",
            file=sys.stderr,
        )
        sys.exit(1)

    # Patch token path if the server exposes a setter — best-effort.
    for attr in ("get_token_path", "TOKEN_PATH", "token_path"):
        if hasattr(_server_mod, attr) and callable(getattr(_server_mod, attr, None)):
            try:
                setattr(_server_mod, attr, lambda: _token_path)
            except Exception:
                pass

    # Run the server's main entry point.
    # mcp-google-gmail exposes either run() or a server object with .run().
    if hasattr(_server_mod, "run"):
        await _server_mod.run()
    elif hasattr(_server_mod, "server"):
        import mcp.server.stdio
        from mcp.server.models import InitializationOptions
        from mcp.server import NotificationOptions

        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await _server_mod.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="mcp_google_gmail",
                    server_version="0.1.0",
                    capabilities=_server_mod.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )
    else:
        print(
            "Gmail MCP: could not find server entry point in mcp_google_gmail.server. "
            "Check the installed version and update gmail_mcp_launcher.py accordingly.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    _authorize()
    asyncio.run(_run())
