"""
connectors/youtube_music.py — YouTubeMusicConnector.

Full playback control via mpv + yt-dlp + IPC socket, plus search/library
via ytmusicapi. Equivalent capability to SpotifyMCPConnector — both play,
pause, skip, set volume.

Architecture:
  ytmusicapi  → search, library, playlist queries (unofficial YTM API)
  mpv + yt-dlp → actual audio playback (streams YTM URLs locally)
  mpv IPC socket → play, pause, skip, volume commands

Setup:
  1. Install dependencies:
       pip install ytmusicapi
       # install mpv and yt-dlp via system package manager:
       # Windows: winget install mpv  &&  pip install yt-dlp
       # macOS:   brew install mpv yt-dlp
  2. Authenticate ytmusicapi once:
       python -c "from ytmusicapi import YTMusic; YTMusic.setup(filepath='~/.yana/ytmusic_auth.json')"
  3. Register in orchestrator/config/connectors.yaml:
       - type: YouTubeMusicConnector
         id: ytmusic_fred
         name: "YouTube Music do Fred"
         owner: fred
         config:
           auth_file: "~/.yana/ytmusic_auth.json"
           ipc_socket: "/tmp/yana-ytmusic.sock"
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from connectors import Connector, command, query

_YTM_BASE_URL = "https://music.youtube.com/watch?v="
_YTM_PLAYLIST_URL = "https://music.youtube.com/playlist?list="


class YouTubeMusicConnector(Connector):
    connector_description = "YouTube Music — full playback control (play, pause, skip, volume) + search and library via mpv + ytmusicapi"

    def __init__(
        self,
        auth_file: str | None = None,
        ipc_socket: str | None = None,
    ) -> None:
        from ytmusicapi import YTMusic  # type: ignore[import-untyped]

        auth = str(Path(auth_file or "~/.yana/ytmusic_auth.json").expanduser())
        self._ytm = YTMusic(auth)
        self._ipc_socket = ipc_socket or "/tmp/yana-ytmusic.sock"
        self._mpv: subprocess.Popen | None = None  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # mpv IPC
    # ------------------------------------------------------------------

    def _launch_mpv(self, url: str) -> None:
        """Start mpv with IPC socket, replacing any existing process."""
        if self._mpv and self._mpv.poll() is None:
            self._mpv.terminate()

        self._mpv = subprocess.Popen(
            [
                "mpv",
                f"--input-ipc-server={self._ipc_socket}",
                "--no-video",
                "--ytdl",
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait briefly for the IPC socket to become available
        for _ in range(20):
            if Path(self._ipc_socket).exists():
                break
            time.sleep(0.1)

    def _mpv_cmd(self, *args: Any) -> Any:
        """Send a JSON IPC command to the running mpv process."""
        payload = json.dumps({"command": list(args)}) + "\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(self._ipc_socket)
                s.sendall(payload.encode())
                s.settimeout(2.0)
                try:
                    data = s.recv(4096)
                    return json.loads(data).get("data")
                except (TimeoutError, json.JSONDecodeError):
                    return None
        except OSError as exc:
            raise RuntimeError(f"mpv IPC unavailable: {exc}") from exc

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @query(
        description="Search YouTube Music. filter: 'songs' | 'albums' | 'playlists' | 'artists' | 'videos'. Returns up to max_results items.",
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
        description="Currently playing track in mpv. Returns None if nothing is playing.",
        returns={"type": "object"},
    )
    def now_playing(self) -> dict | None:
        if not self._mpv or self._mpv.poll() is not None:
            return None
        title = self._mpv_cmd("get_property", "media-title")
        paused = self._mpv_cmd("get_property", "pause")
        pos = self._mpv_cmd("get_property", "time-pos")
        duration = self._mpv_cmd("get_property", "duration")
        return {
            "title": title,
            "is_playing": paused is False,
            "progress_s": round(pos, 1) if pos else None,
            "duration_s": round(duration, 1) if duration else None,
        }

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
        description="Play a song or playlist via mpv. Pass video_id for a track or playlist_id for a full playlist.",
        params={
            "video_id": {"type": "string", "required": False},
            "playlist_id": {"type": "string", "required": False},
        },
        returns={"type": "boolean"},
    )
    def play(self, video_id: str | None = None, playlist_id: str | None = None) -> bool:
        if playlist_id:
            url = _YTM_PLAYLIST_URL + playlist_id
        elif video_id:
            url = _YTM_BASE_URL + video_id
        else:
            raise ValueError("Provide video_id or playlist_id")
        self._launch_mpv(url)
        return True

    @command(
        description="Pause or resume playback",
        returns={"type": "boolean"},
    )
    def pause(self) -> bool:
        self._mpv_cmd("cycle", "pause")
        return True

    @command(
        description="Skip to next track (playlist mode)",
        returns={"type": "boolean"},
    )
    def skip_next(self) -> bool:
        self._mpv_cmd("playlist-next")
        return True

    @command(
        description="Go back to previous track (playlist mode)",
        returns={"type": "boolean"},
    )
    def skip_prev(self) -> bool:
        self._mpv_cmd("playlist-prev")
        return True

    @command(
        description="Set playback volume (0-100)",
        params={"level": {"type": "number"}},
        returns={"type": "boolean"},
    )
    def set_volume(self, level: int) -> bool:
        self._mpv_cmd("set_property", "volume", max(0, min(100, level)))
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
