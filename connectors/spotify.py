"""
connectors/spotify.py — SpotifyConnector.

Uses spotipy directly for Spotify Web API access. Supports playback control,
search, and playlist queries.

Setup:
  1. pip install spotipy
  2. Create a Spotify app at https://developer.spotify.com/dashboard
     and set redirect URI to http://localhost:8888/callback
  3. Create ~/.yana/credentials/spotify_fred.json:
       {"client_id": "...", "client_secret": "..."}
  4. Register in orchestrator/config/connectors.yaml:
       - type: SpotifyConnector
         id: spotify_fred
         name: "Spotify do Fred"
         owner: fred
         config:
           credentials_file: "~/.yana/credentials/spotify_fred.json"
           token_file: "~/.yana/tokens/spotify_fred.json"

  On first use, a browser opens for OAuth and saves the token automatically.
  Subsequent runs load the saved token — no interaction needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from connectors import Connector, command, query


def _read_secret(prompt: str) -> str:
    """Read a secret from the terminal with echo suppressed."""
    print(prompt, end="", flush=True)

    if sys.platform == "win32":
        import msvcrt

        chars: list[str] = []
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                break
            if ch == "\x03":
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                raise KeyboardInterrupt
            if ch == "\x08":
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
            else:
                chars.append(ch)
                sys.stdout.write("*")
                sys.stdout.flush()
        sys.stdout.write("\r\n")
        sys.stdout.flush()
        return "".join(chars)

    import getpass

    return getpass.getpass("")


_SCOPE = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing "
    "playlist-read-private"
)
_DEFAULT_REDIRECT = "http://localhost:8888/callback"


class SpotifyConnector(Connector):
    connector_description = (
        "Spotify playback control and music search — play, pause, skip, volume, search"
    )

    def __init__(
        self,
        credentials_file: str | None = None,
        token_file: str | None = None,
    ) -> None:
        creds_path = Path(credentials_file or "~/.yana/credentials/spotify_fred.json").expanduser()

        if not creds_path.exists():
            creds_path = self._prompt_and_save_credentials(creds_path)

        creds = json.loads(creds_path.read_text(encoding="utf-8"))
        self._client_id: str = creds.get("client_id", "")
        self._client_secret: str = creds.get("client_secret", "")
        if not self._client_id or not self._client_secret:
            raise PermissionError(
                f"Spotify credentials at {creds_path} are missing client_id or client_secret."
            )
        self._redirect_uri: str = creds.get("redirect_uri", _DEFAULT_REDIRECT)
        self._token_file = Path(token_file or "~/.yana/tokens/spotify_fred.json").expanduser()
        self._sp: Any = None  # lazy — created on first use

        # Suppress spotipy's internal HTTP error logging — retries are handled
        # internally and the raw 404/503 noise should not reach the user's console.
        import logging

        logging.getLogger("spotipy").setLevel(logging.CRITICAL)

    @staticmethod
    def _prompt_and_save_credentials(creds_path: Path) -> Path:
        """Interactively ask for Spotify app credentials and save them to disk."""
        print(f"\n[Spotify] Credenciais não encontradas: {creds_path}")
        print("[Spotify] Informe as credenciais do app em developer.spotify.com/dashboard:")
        client_id = input("  Client ID: ").strip()
        client_secret = _read_secret("  Client Secret: ")
        creds_path.parent.mkdir(parents=True, exist_ok=True)
        creds_path.write_text(
            json.dumps({"client_id": client_id, "client_secret": client_secret}, indent=2),
            encoding="utf-8",
        )
        print(f"[Spotify] Credenciais salvas em {creds_path}")
        return creds_path

    # ------------------------------------------------------------------
    # Lazy Spotify client
    # ------------------------------------------------------------------

    def _spotify(self) -> Any:
        if self._sp is not None:
            return self._sp
        import spotipy  # type: ignore[import-untyped]
        from spotipy.oauth2 import SpotifyOAuth  # type: ignore[import-untyped]

        self._token_file.parent.mkdir(parents=True, exist_ok=True)
        self._sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=self._client_id,
                client_secret=self._client_secret,
                redirect_uri=self._redirect_uri,
                scope=_SCOPE,
                cache_path=str(self._token_file),
                open_browser=True,
            )
        )
        return self._sp

    # ------------------------------------------------------------------
    # Internal dispatcher — keeps _call_tool(tool, args) interface so
    # existing tests can mock at this level without touching the Spotify SDK.
    # ------------------------------------------------------------------

    def _call_tool(self, tool: str, args: dict[str, Any]) -> Any:
        try:
            sp = self._spotify()
        except Exception as exc:
            raise PermissionError(str(exc)) from exc

        try:
            if tool == "get-playback-state":
                return sp.current_playback()

            if tool == "search":
                return sp.search(
                    q=args.get("query", ""),
                    type=args.get("type", "track"),
                    limit=args.get("limit", 5),
                )

            if tool == "get-playlists":
                return sp.current_user_playlists(limit=args.get("limit", 20))

            if tool == "get-devices":
                return sp.devices()

            if tool == "start-playback":
                device_id = args.get("device_id")
                try:
                    if "uris" in args:
                        sp.start_playback(device_id=device_id, uris=args["uris"])
                    elif "context_uri" in args:
                        sp.start_playback(device_id=device_id, context_uri=args["context_uri"])
                    else:
                        sp.start_playback(device_id=device_id)
                except Exception as exc:
                    # NO_ACTIVE_DEVICE: auto-retry on best available device
                    if "NO_ACTIVE_DEVICE" in str(exc) and not device_id:
                        all_devices = (sp.devices() or {}).get("devices") or []
                        if not all_devices:
                            raise RuntimeError(
                                "Nenhum dispositivo Spotify encontrado. "
                                "Abra o Spotify no celular, computador ou outro dispositivo."
                            ) from exc

                        def _priority(d: dict) -> int:
                            if d.get("is_active"):
                                return 0
                            t = (d.get("type") or "").lower()
                            return 1 if t == "smartphone" else (2 if t == "computer" else 3)

                        target_id = sorted(all_devices, key=_priority)[0]["id"]
                        if "uris" in args:
                            sp.start_playback(device_id=target_id, uris=args["uris"])
                        elif "context_uri" in args:
                            sp.start_playback(device_id=target_id, context_uri=args["context_uri"])
                        else:
                            sp.start_playback(device_id=target_id)
                    else:
                        raise
                return {}

            if tool == "pause-playback":
                sp.pause_playback()
                return {}

            if tool == "skip-to-next":
                sp.next_track()
                return {}

            if tool == "skip-to-previous":
                sp.previous_track()
                return {}

            if tool == "set-volume":
                sp.volume(args.get("volume_percent", 50))
                return {}

        except Exception as exc:
            import spotipy  # type: ignore[import-untyped]

            if isinstance(exc, spotipy.SpotifyException) and exc.http_status in (401, 403):
                raise PermissionError(str(exc)) from exc
            raise

        return None

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
        data = self._call_tool("search", {"query": q, "type": type, "limit": max_results})
        items = (data or {}).get("tracks", {}).get("items") or (data or {}).get("items") or []
        return [self._format_track(t) for t in items if t]

    @query(
        description="List available Spotify devices (phone, computer, TV, etc). Use this when playback fails to find where to play.",
        returns={"type": "list"},
    )
    def get_devices(self) -> list[dict]:
        data = self._call_tool("get-devices", {})
        return [
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "type": d.get("type"),
                "is_active": d.get("is_active", False),
            }
            for d in (data or {}).get("devices", [])
            if d
        ]

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
                "tracks": p.get("tracks", {}).get("total")
                if isinstance(p.get("tracks"), dict)
                else None,
            }
            for p in items
            if p
        ]

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @command(
        description="Start or resume playback. Pass a Spotify URI (track, album, or playlist) to play something specific. Returns the device name where playback started.",
        params={"uri": {"type": "string", "required": False}},
        returns={"type": "object"},
    )
    def play(self, uri: str | None = None) -> dict:
        args: dict[str, Any] = {}
        if uri:
            if "track" in uri:
                args["uris"] = [uri]
            else:
                args["context_uri"] = uri
        self._call_tool("start-playback", args)
        # Return which device is now playing so YANA can tell the user
        pb = self._call_tool("get-playback-state", {})
        device = (pb or {}).get("device") or {}
        return {
            "ok": True,
            "device_name": device.get("name"),
            "device_type": device.get("type"),
        }

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
