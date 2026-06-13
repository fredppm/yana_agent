"""
connectors/youtube_music.py — YouTubeMusicConnector.

Full playback control via mpv + yt-dlp + IPC socket.
Search uses yt-dlp (no auth required). Library access (playlists, liked songs)
uses ytmusicapi with browser-cookie auth.

Architecture:
  yt-dlp       → search YouTube Music (no auth, uses ytmsearch: prefix)
  mpv + yt-dlp → actual audio playback (streams YTM URLs locally)
  mpv IPC      → play, pause, skip, volume commands
  ytmusicapi   → library queries (optional, requires one-time browser-cookie setup)

Setup:
  1. Install mpv:
       Windows: winget install mpv.mpv  (in PowerShell)
       macOS:   brew install mpv yt-dlp
  2. For search and playback: no credentials needed.
  3. For library access (playlists, liked songs): one-time browser setup:
       ytmusicapi browser --file ~/.yana/ytmusic_auth.json
     Follow the on-screen instructions to paste your browser request headers.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from connectors import Connector, command, query

_YTM_BASE_URL = "https://music.youtube.com/watch?v="
_YTM_PLAYLIST_URL = "https://music.youtube.com/playlist?list="
_IS_WINDOWS = sys.platform == "win32"


class YouTubeMusicConnector(Connector):
    connector_description = "YouTube Music — search and play via yt-dlp/mpv (no auth needed), library access optional"
    connector_credential_hint = (
        "Search and playback require no credentials — just mpv installed "
        "(Windows: winget install mpv.mpv in PowerShell). "
        "For library access run once: ytmusicapi browser --file ~/.yana/ytmusic_auth.json"
    )

    def __init__(
        self,
        auth_file: str | None = None,
        ipc_socket: str | None = None,
    ) -> None:
        self._auth_file = Path(auth_file or "~/.yana/ytmusic_auth.json").expanduser()
        # On Windows mpv uses named pipes; default to a pipe name (no path separators).
        # On Unix use a socket file path.
        if _IS_WINDOWS:
            self._ipc_socket = ipc_socket or "yana-ytmusic"
        else:
            self._ipc_socket = ipc_socket or "/tmp/yana-ytmusic.sock"
        self._ytm: Any = None  # lazy — only loaded when library access is needed
        self._mpv: subprocess.Popen | None = None  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # ytmusicapi (library access, optional)
    # ------------------------------------------------------------------

    def _ensure_ytm(self) -> None:
        """Initialize ytmusicapi if auth file exists. Raises PermissionError if not."""
        if self._ytm is not None:
            return
        if not self._auth_file.exists():
            raise PermissionError(
                f"YouTube Music library auth not set up. "
                f"Run: ytmusicapi browser --file {self._auth_file}"
            )
        from ytmusicapi import YTMusic  # type: ignore[import-untyped]
        self._ytm = YTMusic(str(self._auth_file))

    # ------------------------------------------------------------------
    # yt-dlp search (no auth)
    # ------------------------------------------------------------------

    def _ytdlp_search(self, query: str, max_results: int) -> list[dict]:
        """Search YouTube Music via yt-dlp — no credentials required."""
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-playlist",
            "--flat-playlist",
            f"ytsearch{max_results}:{query}",
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"yt-dlp unavailable: {exc}") from exc

        items = []
        for line in result.stdout.strip().splitlines():
            try:
                data = json.loads(line)
                video_id = data.get("id")
                url = data.get("url") or data.get("webpage_url")
                items.append({
                    "title": data.get("title"),
                    "artist": data.get("uploader") or data.get("channel"),
                    "album": None,
                    "video_id": video_id,
                    "duration": data.get("duration_string") or str(data.get("duration", "")),
                    "url": url,
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return items

    # ------------------------------------------------------------------
    # mpv IPC
    # ------------------------------------------------------------------

    def _launch_mpv(self, url: str) -> None:
        """Start mpv with IPC, replacing any existing process."""
        if self._mpv and self._mpv.poll() is None:
            self._mpv.terminate()

        try:
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
        except FileNotFoundError as exc:
            raise RuntimeError(
                "mpv not found. Install with: winget install mpv.mpv (PowerShell)"
            ) from exc

        # Wait for the pipe/socket to become available
        pipe_path = rf"\\.\pipe\{self._ipc_socket}" if _IS_WINDOWS else self._ipc_socket
        for _ in range(30):
            if Path(pipe_path).exists():
                break
            time.sleep(0.1)

    def _mpv_cmd(self, *args: Any) -> Any:
        """Send a JSON IPC command to the running mpv process."""
        payload = (json.dumps({"command": list(args)}) + "\n").encode()
        try:
            if _IS_WINDOWS:
                import win32file  # type: ignore[import-untyped]

                pipe_path = rf"\\.\pipe\{self._ipc_socket}"
                handle = win32file.CreateFile(
                    pipe_path,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0,
                    None,
                    win32file.OPEN_EXISTING,
                    0,
                    None,
                )
                try:
                    win32file.WriteFile(handle, payload)
                    _, data = win32file.ReadFile(handle, 65536)
                    return json.loads(data).get("data")
                except (json.JSONDecodeError, Exception):
                    return None
                finally:
                    win32file.CloseHandle(handle)
            else:
                import socket

                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.connect(self._ipc_socket)
                    s.sendall(payload)
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
        description="Search YouTube Music via yt-dlp. No authentication required. filter ignored (yt-dlp always returns mixed results). Returns up to max_results items.",
        params={
            "q": {"type": "string"},
            "filter": {"type": "string", "required": False},
            "max_results": {"type": "number", "required": False},
        },
        returns={"type": "list"},
    )
    def search(self, q: str, filter: str = "songs", max_results: int = 5) -> list[dict]:
        return self._ytdlp_search(q, max_results)

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
        description="List the user's YouTube Music library playlists. Requires browser-cookie auth setup.",
        params={"max_results": {"type": "number", "required": False}},
        returns={"type": "list"},
    )
    def get_library_playlists(self, max_results: int = 20) -> list[dict]:
        self._ensure_ytm()
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
        description="Get tracks in a playlist by playlist ID. Requires browser-cookie auth setup.",
        params={"playlist_id": {"type": "string"}},
        returns={"type": "list"},
    )
    def get_playlist_tracks(self, playlist_id: str) -> list[dict]:
        self._ensure_ytm()
        playlist = self._ytm.get_playlist(playlist_id)
        tracks = (playlist or {}).get("tracks") or []
        return [self._format_result(t) for t in tracks]

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @command(
        description="Search and play a song or playlist via mpv. Pass video_id for a specific track, playlist_id for a playlist, or query to search and play the top result.",
        params={
            "video_id": {"type": "string", "required": False},
            "playlist_id": {"type": "string", "required": False},
            "query": {"type": "string", "required": False},
        },
        returns={"type": "boolean"},
    )
    def play(
        self,
        video_id: str | None = None,
        playlist_id: str | None = None,
        query: str | None = None,
    ) -> bool:
        if playlist_id:
            url = _YTM_PLAYLIST_URL + playlist_id
        elif video_id:
            url = _YTM_BASE_URL + video_id
        elif query:
            # Search via yt-dlp and play the first result
            results = self._ytdlp_search(query, max_results=1)
            if not results or not results[0].get("url"):
                raise ValueError(f"No results found for: {query}")
            url = results[0]["url"]
        else:
            raise ValueError("Provide video_id, playlist_id, or query")
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
    # Response transformer (ytmusicapi results)
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
