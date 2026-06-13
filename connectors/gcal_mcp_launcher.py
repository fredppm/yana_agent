"""
connectors/gcal_mcp_launcher.py

Launcher for mcp-server-google-calendar that:
  1. Patches credential paths to configurable locations before the server starts
     (the package hard-codes paths relative to site-packages when installed via pip)
  2. Bypasses the server's main() function, which calls argparse.parse_args()
     and fails when sys.argv contains parent-process arguments on Windows

Environment variables:
  GOOGLE_CREDENTIALS_PATH  OAuth2 client credentials JSON (Google Cloud Console)
  GOOGLE_TOKEN_PATH        Saved OAuth2 token (auto-created after first browser auth)
"""

import asyncio
import os
import sys
from pathlib import Path

# Patch credential paths before any server code is imported
import mcp_server_google_calendar.auth.auth as _auth

_creds = Path(os.environ.get("GOOGLE_CREDENTIALS_PATH", "~/.yana/google_credentials.json")).expanduser()
_token = Path(os.environ.get("GOOGLE_TOKEN_PATH", "~/.yana/tokens/google_calendar.json")).expanduser()

_auth.get_credentials_path = lambda: _creds
_auth.get_token_path = lambda: _token

# Import server internals after patching
from mcp_server_google_calendar.server import server  # noqa: E402
from mcp_server_google_calendar.auth import authorize   # noqa: E402
import mcp.server.stdio                                # noqa: E402
from mcp.server import NotificationOptions             # noqa: E402
from mcp.server.models import InitializationOptions    # noqa: E402


async def _run() -> None:
    """Start the MCP server, bypassing the argparse-based main() entrypoint."""
    try:
        authorize()
    except Exception as e:
        print(f"Google Calendar auth failed: {e}", file=sys.stderr)
        sys.exit(1)

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="mcp_server_google_calendar",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(_run())
