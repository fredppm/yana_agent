"""
connectors/gmail_mcp_launcher.py

Launcher for mcp-google-gmail. Starts the MCP server with token/credential
paths injected via env vars. Auth is intentionally NOT done here — it must
run in the parent process (GmailMCPConnector.__init__) where stdout is the
terminal, not the JSONRPC pipe.

Environment variables (set by GmailMCPConnector):
  GMAIL_CREDENTIALS_PATH  OAuth2 client credentials JSON
  GMAIL_TOKEN_PATH        Saved OAuth2 token (guaranteed to exist before this runs)
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_token_path = Path(
    os.environ.get("GMAIL_TOKEN_PATH", "~/.yana/tokens/gmail.json")
).expanduser()


async def _run() -> None:
    try:
        import mcp_google_gmail.server as _server_mod  # type: ignore[import]
    except ImportError:
        print(
            "Gmail MCP: mcp-google-gmail not installed. "
            "Run: pip install mcp-google-gmail",
            file=sys.stderr,
        )
        sys.exit(1)

    # Best-effort: patch token path if the server exposes a setter.
    for attr in ("get_token_path", "TOKEN_PATH", "token_path"):
        if hasattr(_server_mod, attr) and callable(getattr(_server_mod, attr, None)):
            try:
                setattr(_server_mod, attr, lambda: _token_path)
            except Exception:
                pass

    if hasattr(_server_mod, "run"):
        await _server_mod.run()
    elif hasattr(_server_mod, "server"):
        import mcp.server.stdio
        from mcp.server import NotificationOptions
        from mcp.server.models import InitializationOptions

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
            "Update gmail_mcp_launcher.py to match the installed version.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_run())
