"""
connectors/youtube_music.py — YouTubeMusicConnector.

Search and discovery via YouTube Music (unofficial API via ytmusicapi).
Playback is launched via browser or mpv — YouTube Music has no public
playback control API.

Setup:
  1. Install ytmusicapi:
       pip install ytmusicapi
  2. Authenticate once (opens browser for OAuth):
       python -c "from ytmusicapi import YTMusic; YTMusic.setup(filepath='~/.yana/ytmusic_auth.json')"
  3. Register in orchestrator/config/connectors.yaml:
       - type: YouTubeMusicConnector
         id: ytmusic_fred
         name: "YouTube Music do Fred"
         owner: fred
         config:
           auth_file: "~/.yana/ytmusic_auth.json"
           player: "browser"   # "browser" | "mpv"

Note on playback:
  YouTube Music has no public playback control API. The `open` command
  launches the track URL in the configured player (browser or mpv).
  Use Spotify connector for in-session playback control (pause, skip, volume).
"""

from __future__ import annotations

import subprocess
import webbrowser
from pathlib import Path
from typing import Any

from connectors import Connector, command, query

_YTM_BASE_URL = "https://music.youtube.com/watch?v="
_YTM_PLAYLIST_URL = "https://music.youtube.com/playlist?list="


class YouTubeMusicConnector(Connector):
    connector_description = "YouTube Music search and library — find songs, albums, playlists, open for playback"

    def __init__(
        self,
        auth_file: str | None = None,
        player: str = "browser",
    ) -> None:
        from ytmusicapi import YTMusic  # type: ignore[import-untyped]

        auth = str(Path(auth_file or "~/.yana/ytmusic_auth.json").expanduser())
        self._ytm = YTMusic(auth)
        self._player = player  # "browser" | "mpv"

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @query(
        description="Search YouTube Music. filter can be 'songs', 'albums', 'playlists', 'artists', 'videos'. Returns up to max_results items.",
        params={
            "q": {"type": "string"},
            "filter": {"type": "string", "required": False},
            "max_results": {"type": "number", "required": False},
        },
        returns={"type": "list"},
    )
    def search(self, q: str, filter: str = "songs", max_results: int = 5) -> list[dict]:
        results = self._ytm.search(q, filter=filter, limit=max_results)
        return [self._format_result(r) for r in (results or [])[:max_results]]

    @query(
        description="List the user's YouTube Music library playlists",
        params={"max_results": {"type": "number", "required": False}},
        returns={"type": "list"},
    )
    def get_library_playlists(self, max_results: int = 20) -> list[dict]:
        playlists = self._ytm.get_library_playlists(limit=max_results)
        return [
            {
                "id": p.get("playlistId"),
                "title": p.get("title"),
                "count": p.get("count"),
                "url": _YTM_PLAYLIST_URL + p["playlistId"] if p.get("playlistId") else None,
            }
            for p in (playlists or [])
        ]

    @query(
        description="Get tracks in a playlist by playlist ID",
        params={"playlist_id": {"type": "string"}},
        returns={"type": "list"},
    )
    def get_playlist_tracks(self, playlist_id: str) -> list[dict]:
        playlist = self._ytm.get_playlist(playlist_id)
        tracks = (playlist or {}).get("tracks") or []
        return [self._format_result(t) for t in tracks]

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @command(
        description="Open a song or playlist in the configured player (browser or mpv). Pass video_id for a song or playlist_id for a playlist.",
        params={
            "video_id": {"type": "string", "required": False},
            "playlist_id": {"type": "string", "required": False},
        },
        returns={"type": "boolean"},
    )
    def open(self, video_id: str | None = None, playlist_id: str | None = None) -> bool:
        if playlist_id:
            url = _YTM_PLAYLIST_URL + playlist_id
        elif video_id:
            url = _YTM_BASE_URL + video_id
        else:
            raise ValueError("Provide video_id or playlist_id")

        if self._player == "mpv":
            subprocess.Popen(["mpv", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            webbrowser.open(url)
        return True

    # ------------------------------------------------------------------
    # Response transformer
    # ------------------------------------------------------------------

    def _format_result(self, raw: dict) -> dict:
        artists = raw.get("artists") or []
        album = raw.get("album") or {}
        video_id = raw.get("videoId")
        return {
            "title": raw.get("title"),
            "artist": ", ".join(a.get("name", "") for a in artists if isinstance(a, dict)),
            "album": album.get("name") if isinstance(album, dict) else None,
            "video_id": video_id,
            "duration": raw.get("duration"),
            "url": (_YTM_BASE_URL + video_id) if video_id else None,
        }
