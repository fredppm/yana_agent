"""
connectors/youtube_music.py — YouTubeMusicConnector.

Full playback control via mpv + yt-dlp + IPC socket, plus search/library
via ytmusicapi. Equivalent capability to SpotifyMCPConnector — both play,
pause, skip, set volume.

Architecture:
  google-auth-oauthlib → OAuth flow (same as Google Calendar connector)
  ytmusicapi  → search, library, playlist queries (unofficial YTM API)
  mpv + yt-dlp → actual audio playback (streams YTM URLs locally)
  mpv IPC      → play, pause, skip, volume commands

Setup:
  1. Install mpv:
       Windows: winget install mpv.mpv  (in PowerShell)
       macOS:   brew install mpv yt-dlp
  2. Uses the same google_credentials.json as Google Calendar — no separate
     setup needed if Calendar is already configured. First use opens a
     browser window for Google authentication and saves the token.
  3. Entry in orchestrator/config/connectors.yaml:
       - type: YouTubeMusicConnector
         id: ytmusic_fred
         name: "YouTube Music do Fred"
         owner: fred
         config:
           credentials_file: "~/.yana/google_credentials.json"
           token_file: "~/.yana/tokens/ytmusic_fred.json"
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

_YTM_SCOPE = "https://www.googleapis.com/auth/youtube"


class YouTubeMusicConnector(Connector):
    connector_description = "YouTube Music — full playback control (play, pause, skip, volume) + search and library via mpv + ytmusicapi"
    connector_credential_hint = (
        "Uses the same Google credentials as the Calendar connector. "
        "Ensure ~/.yana/google_credentials.json exists (download from console.cloud.google.com). "
        "On first use a browser window opens for Google authentication — no manual setup needed. "
        "Also requires mpv: run `winget install mpv.mpv` in PowerShell."
    )

    def __init__(
        self,
        credentials_file: str | None = None,
        token_file: str | None = None,
        ipc_socket: str | None = None,
    ) -> None:
        self._credentials_file = Path(
            credentials_file or "~/.yana/google_credentials.json"
        ).expanduser()
        self._token_file = Path(
            token_file or "~/.yana/tokens/ytmusic_fred.json"
        ).expanduser()
        # On Windows mpv uses named pipes; default to a pipe name (no path separators).
        # On Unix use a socket file path.
        if _IS_WINDOWS:
            self._ipc_socket = ipc_socket or "yana-ytmusic"
        else:
            self._ipc_socket = ipc_socket or "/tmp/yana-ytmusic.sock"

        self._ytm: Any = None
        self._mpv: subprocess.Popen | None = None  # type: ignore[type-arg]

        # Eagerly initialize YTMusic if token already exists
        if self._token_file.exists():
            self._init_ytm()
        elif not self._credentials_file.exists():
            raise PermissionError(
                f"Google credentials not found: {self._credentials_file}. "
                "Download from console.cloud.google.com."
            )
        # If token doesn't exist but credentials do — lazy setup on first call

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _client_info(self) -> dict:
        """Extract client_id and client_secret from the Google credentials file."""
        data = json.loads(self._credentials_file.read_text(encoding="utf-8"))
        return data.get("installed") or data.get("web") or {}

    def _ensure_auth(self) -> None:
        """Run browser OAuth flow if token doesn't exist, then init YTMusic."""
        if self._ytm is not None:
            return
        if not self._token_file.exists():
            self._run_oauth_flow()
        self._init_ytm()

    def _run_oauth_flow(self) -> None:
        """Open browser for Google OAuth (same flow as Calendar connector)."""
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._credentials_file), scopes=[_YTM_SCOPE]
        )
        google_creds = flow.run_local_server(port=0)

        # Write ytmusicapi-compatible OAuth JSON
        expiry_ts = int(google_creds.expiry.timestamp()) if google_creds.expiry else int(time.time()) + 3600
        token_data = {
            "scope": _YTM_SCOPE,
            "token_type": "Bearer",
            "access_token": google_creds.token,
            "refresh_token": google_creds.refresh_token,
            "expires_at": expiry_ts,
            "expires_in": max(0, expiry_ts - int(time.time())),
        }
        self._token_file.parent.mkdir(parents=True, exist_ok=True)
        self._token_file.write_text(json.dumps(token_data, indent=2), encoding="utf-8")

    def _init_ytm(self) -> None:
        """Create YTMusic instance with saved OAuth token."""
        from ytmusicapi import YTMusic  # type: ignore[import-untyped]
        from ytmusicapi.auth.oauth import OAuthCredentials  # type: ignore[import-untyped]

        client = self._client_info()
        oauth_creds = OAuthCredentials(
            client_id=client["client_id"],
            client_secret=client["client_secret"],
        )
        self._ytm = YTMusic(str(self._token_file), oauth_credentials=oauth_creds)

    # ------------------------------------------------------------------
    # mpv IPC
    # ------------------------------------------------------------------

    def _launch_mpv(self, url: str) -> None:
        """Start mpv with IPC, replacing any existing process."""
        if self._mpv and self._mpv.poll() is None:
            self._mpv.terminate()

        # Windows: --input-ipc-server=<name> creates \\.\pipe\<name>
        # Unix:    --input-ipc-server=<path> creates a Unix socket file
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
        description="Search YouTube Music. filter: 'songs' | 'albums' | 'playlists' | 'artists' | 'videos'. Returns up to max_results items.",
        params={
            "q": {"type": "string"},
            "filter": {"type": "string", "required": False},
            "max_results": {"type": "number", "required": False},
        },
        returns={"type": "list"},
    )
    def search(self, q: str, filter: str = "songs", max_results: int = 5) -> list[dict]:
        self._ensure_auth()
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
        self._ensure_auth()
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
        self._ensure_auth()
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
