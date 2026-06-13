"""
connectors/spotify_mcp.py — SpotifyMCPConnector.

Routes YANA connector calls to a local Spotify MCP server process via the
Python MCP SDK. Supports playback control, search, and playlist queries.

Backend: sespinosa/spotify-mcp (Python, pip-installable)
  pip install spotify-mcp

Setup:
  1. Install the MCP server:
       pip install spotify-mcp
  2. Create a Spotify app at https://developer.spotify.com/dashboard
     and set redirect URI to http://localhost:8888/callback
  3. Run auth once:
       python -m spotify_mcp auth
  4. Register in orchestrator/config/connectors.yaml:
       - type: SpotifyMCPConnector
         id: spotify_fred
         name: "Spotify do Fred"
         owner: fred
         config:
           client_id: "<your-client-id>"
           client_secret: "<your-client-secret>"
           token_file: "~/.yana/tokens/spotify_fred.json"
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from contextlib import AsyncExitStack
from typing import Any

from connectors import Connector, command, query


class SpotifyMCPConnector(Connector):
    connector_description = "Spotify playback control and music search — play, pause, skip, volume, search"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        token_file: str | None = None,
        mcp_command: list[str] | None = None,
    ) -> None:
        merged = dict(os.environ)
        if client_id:
            merged["SPOTIFY_CLIENT_ID"] = client_id
        if client_secret:
            merged["SPOTIFY_CLIENT_SECRET"] = client_secret
        if token_file:
            merged["SPOTIFY_TOKEN_PATH"] = os.path.expanduser(token_file)
        self._env = merged

        # Command to launch the MCP server process via stdio.
        self._mcp_command = mcp_command or ["python", "-m", "spotify_mcp"]

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name=f"spotify-mcp-{id(self)}",
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
        return future.result(timeout=30)

    async def _start_session(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._mcp_command[0],
            args=self._mcp_command[1:],
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
        description="Currently playing track. Returns None if nothing is playing.",
        returns={"type": "object"},
    )
    def now_playing(self) -> dict | None:
        data = self._call_tool("get-playback-state", {})
        if not data:
            return None
        return self._format_playback(data)

    @query(
        description="Search Spotify. type can be 'track', 'album', 'playlist', or 'artist'. Returns up to max_results items.",
        params={
            "q": {"type": "string"},
            "type": {"type": "string", "required": False},
            "max_results": {"type": "number", "required": False},
        },
        returns={"type": "list"},
    )
    def search(self, q: str, type: str = "track", max_results: int = 5) -> list[dict]:
        data = self._call_tool("search", {
            "query": q,
            "type": type,
            "limit": max_results,
        })
        items = (data or {}).get("tracks", {}).get("items") or (data or {}).get("items") or []
        return [self._format_track(t) for t in items if t]

    @query(
        description="List the current user's playlists",
        params={"max_results": {"type": "number", "required": False}},
        returns={"type": "list"},
    )
    def get_playlists(self, max_results: int = 20) -> list[dict]:
        data = self._call_tool("get-playlists", {"limit": max_results})
        items = (data or {}).get("items") or []
        return [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "uri": p.get("uri"),
                "tracks": p.get("tracks", {}).get("total") if isinstance(p.get("tracks"), dict) else None,
            }
            for p in items if p
        ]

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @command(
        description="Start or resume playback. Pass a Spotify URI (track, album, or playlist) to play something specific.",
        params={"uri": {"type": "string", "required": False}},
        returns={"type": "boolean"},
    )
    def play(self, uri: str | None = None) -> bool:
        args: dict[str, Any] = {}
        if uri:
            if "track" in uri:
                args["uris"] = [uri]
            else:
                args["context_uri"] = uri
        self._call_tool("start-playback", args)
        return True

    @command(
        description="Pause playback",
        returns={"type": "boolean"},
    )
    def pause(self) -> bool:
        self._call_tool("pause-playback", {})
        return True

    @command(
        description="Skip to next track",
        returns={"type": "boolean"},
    )
    def skip_next(self) -> bool:
        self._call_tool("skip-to-next", {})
        return True

    @command(
        description="Go back to previous track",
        returns={"type": "boolean"},
    )
    def skip_prev(self) -> bool:
        self._call_tool("skip-to-previous", {})
        return True

    @command(
        description="Set playback volume (0-100)",
        params={"level": {"type": "number"}},
        returns={"type": "boolean"},
    )
    def set_volume(self, level: int) -> bool:
        self._call_tool("set-volume", {"volume_percent": max(0, min(100, level))})
        return True

    # ------------------------------------------------------------------
    # Response transformers
    # ------------------------------------------------------------------

    def _format_playback(self, data: dict) -> dict:
        item = data.get("item") or {}
        artists = item.get("artists") or []
        album = item.get("album") or {}
        return {
            "track": item.get("name"),
            "artist": ", ".join(a.get("name", "") for a in artists if a),
            "album": album.get("name"),
            "uri": item.get("uri"),
            "is_playing": data.get("is_playing", False),
            "progress_ms": data.get("progress_ms"),
            "duration_ms": item.get("duration_ms"),
        }

    def _format_track(self, raw: dict) -> dict:
        artists = raw.get("artists") or []
        album = raw.get("album") or {}
        return {
            "name": raw.get("name"),
            "artist": ", ".join(a.get("name", "") for a in artists if a),
            "album": album.get("name"),
            "uri": raw.get("uri"),
            "duration_ms": raw.get("duration_ms"),
        }
