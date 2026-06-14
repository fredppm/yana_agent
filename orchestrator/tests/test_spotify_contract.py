"""
Contract tests for SpotifyConnector.

_call_tool() is mocked so no real Spotify credentials or network are needed.

Run with: python -m pytest tests/test_spotify_contract.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

_CONNECTOR_FILE = Path(__file__).parent.parent.parent / "connectors" / "spotify.py"
_spec = importlib.util.spec_from_file_location("spotify", _CONNECTOR_FILE)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

SpotifyConnector = _mod.SpotifyConnector

# ---------------------------------------------------------------------------
# Shared MCP response payloads
# ---------------------------------------------------------------------------

_TRACK = {
    "name": "Bohemian Rhapsody",
    "artists": [{"name": "Queen"}],
    "album": {"name": "A Night at the Opera"},
    "uri": "spotify:track:abc123",
    "duration_ms": 354320,
}

_PLAYBACK_PLAYING = {
    "is_playing": True,
    "progress_ms": 45000,
    "item": _TRACK,
}

_PLAYBACK_PAUSED = {
    "is_playing": False,
    "progress_ms": 45000,
    "item": _TRACK,
}

_SEARCH_RESULTS = {
    "tracks": {
        "items": [
            {
                "name": "Stairway to Heaven",
                "artists": [{"name": "Led Zeppelin"}],
                "album": {"name": "Led Zeppelin IV"},
                "uri": "spotify:track:xyz789",
                "duration_ms": 482000,
            }
        ]
    }
}

_PLAYLISTS = {
    "items": [
        {
            "id": "pl1",
            "name": "Morning Mix",
            "uri": "spotify:playlist:pl1",
            "tracks": {"total": 30},
        },
        {"id": "pl2", "name": "Workout", "uri": "spotify:playlist:pl2", "tracks": {"total": 45}},
    ]
}

_EXPECTED_PLAYBACK_KEYS = {
    "track",
    "artist",
    "album",
    "uri",
    "is_playing",
    "progress_ms",
    "duration_ms",
}
_EXPECTED_TRACK_KEYS = {"name", "artist", "album", "uri", "duration_ms"}
_EXPECTED_PLAYLIST_KEYS = {"id", "name", "uri", "tracks"}


def _make_connector() -> Any:
    connector = SpotifyConnector.__new__(SpotifyConnector)
    connector._sp = None
    return connector


def _with_tool(connector: Any, responses: dict[str, object]) -> Any:
    def _fake(tool: str, args: dict) -> object:
        return responses.get(tool)

    connector._call_tool = _fake
    return connector


# ---------------------------------------------------------------------------
# CAP-1: Operation discovery
# ---------------------------------------------------------------------------


def test_now_playing_is_query():
    assert "now_playing" in SpotifyConnector._operations
    assert SpotifyConnector._operations["now_playing"].kind == "query"


def test_search_is_query():
    assert "search" in SpotifyConnector._operations
    assert SpotifyConnector._operations["search"].kind == "query"


def test_get_playlists_is_query():
    assert "get_playlists" in SpotifyConnector._operations
    assert SpotifyConnector._operations["get_playlists"].kind == "query"


def test_play_is_command():
    assert "play" in SpotifyConnector._operations
    assert SpotifyConnector._operations["play"].kind == "command"


def test_pause_is_command():
    assert "pause" in SpotifyConnector._operations
    assert SpotifyConnector._operations["pause"].kind == "command"


def test_skip_next_is_command():
    assert "skip_next" in SpotifyConnector._operations
    assert SpotifyConnector._operations["skip_next"].kind == "command"


def test_skip_prev_is_command():
    assert "skip_prev" in SpotifyConnector._operations
    assert SpotifyConnector._operations["skip_prev"].kind == "command"


def test_set_volume_is_command():
    assert "set_volume" in SpotifyConnector._operations
    assert SpotifyConnector._operations["set_volume"].kind == "command"


# ---------------------------------------------------------------------------
# CAP-1: Descriptions
# ---------------------------------------------------------------------------


def test_all_operations_have_descriptions():
    for name, op in SpotifyConnector._operations.items():
        assert op.description, f"Operation '{name}' has no description"


# ---------------------------------------------------------------------------
# CAP-5: Param schemas
# ---------------------------------------------------------------------------


def test_search_requires_q():
    params = SpotifyConnector._operations["search"].params
    assert params["q"].required is True


def test_search_type_and_max_are_optional():
    params = SpotifyConnector._operations["search"].params
    assert params["type"].required is False
    assert params["max_results"].required is False


def test_play_uri_is_optional():
    params = SpotifyConnector._operations["play"].params
    assert params["uri"].required is False


def test_set_volume_requires_level():
    params = SpotifyConnector._operations["set_volume"].params
    assert params["level"].required is True


# ---------------------------------------------------------------------------
# Output shape — now_playing
# ---------------------------------------------------------------------------


def test_now_playing_output_shape():
    c = _with_tool(_make_connector(), {"get-playback-state": _PLAYBACK_PLAYING})
    result = c.call("now_playing")
    assert result.ok is True
    assert set(result.data.keys()) == _EXPECTED_PLAYBACK_KEYS


def test_now_playing_values():
    c = _with_tool(_make_connector(), {"get-playback-state": _PLAYBACK_PLAYING})
    result = c.call("now_playing")
    assert result.data["track"] == "Bohemian Rhapsody"
    assert result.data["artist"] == "Queen"
    assert result.data["album"] == "A Night at the Opera"
    assert result.data["uri"] == "spotify:track:abc123"
    assert result.data["is_playing"] is True
    assert result.data["progress_ms"] == 45000
    assert result.data["duration_ms"] == 354320


def test_now_playing_paused():
    c = _with_tool(_make_connector(), {"get-playback-state": _PLAYBACK_PAUSED})
    result = c.call("now_playing")
    assert result.ok is True
    assert result.data["is_playing"] is False


def test_now_playing_none_when_no_data():
    c = _with_tool(_make_connector(), {"get-playback-state": None})
    result = c.call("now_playing")
    assert result.ok is True
    assert result.data is None


# ---------------------------------------------------------------------------
# Output shape — search
# ---------------------------------------------------------------------------


def test_search_output_shape():
    c = _with_tool(_make_connector(), {"search": _SEARCH_RESULTS})
    result = c.call("search", {"q": "stairway to heaven"})
    assert result.ok is True
    assert isinstance(result.data, list)
    assert len(result.data) == 1
    assert set(result.data[0].keys()) == _EXPECTED_TRACK_KEYS


def test_search_track_values():
    c = _with_tool(_make_connector(), {"search": _SEARCH_RESULTS})
    result = c.call("search", {"q": "stairway to heaven"})
    track = result.data[0]
    assert track["name"] == "Stairway to Heaven"
    assert track["artist"] == "Led Zeppelin"
    assert track["uri"] == "spotify:track:xyz789"


def test_search_empty_returns_empty_list():
    c = _with_tool(_make_connector(), {"search": {"tracks": {"items": []}}})
    result = c.call("search", {"q": "nonexistent"})
    assert result.ok is True
    assert result.data == []


def test_search_requires_q_param():
    c = _make_connector()
    result = c.call("search", {})
    assert result.ok is False
    assert result.error == "validation_error"


# ---------------------------------------------------------------------------
# Output shape — get_playlists
# ---------------------------------------------------------------------------


def test_get_playlists_output_shape():
    c = _with_tool(_make_connector(), {"get-playlists": _PLAYLISTS})
    result = c.call("get_playlists")
    assert result.ok is True
    assert isinstance(result.data, list)
    assert len(result.data) == 2
    assert set(result.data[0].keys()) == _EXPECTED_PLAYLIST_KEYS


def test_get_playlists_values():
    c = _with_tool(_make_connector(), {"get-playlists": _PLAYLISTS})
    result = c.call("get_playlists")
    assert result.data[0]["name"] == "Morning Mix"
    assert result.data[0]["uri"] == "spotify:playlist:pl1"
    assert result.data[0]["tracks"] == 30


# ---------------------------------------------------------------------------
# Commands — return True on success
# ---------------------------------------------------------------------------


_PLAYBACK_TV = {
    "device": {"name": "Guest Room TV", "type": "TV"},
    "is_playing": True,
    "item": _TRACK,
}


def test_play_returns_ok_with_device():
    c = _with_tool(_make_connector(), {"start-playback": {}, "get-playback-state": _PLAYBACK_TV})
    result = c.call("play")
    assert result.ok is True
    assert result.data["ok"] is True
    assert result.data["device_name"] == "Guest Room TV"


def test_play_with_track_uri():
    calls: list = []

    def _fake(tool: str, args: dict) -> object:
        calls.append({"tool": tool, "args": args})
        return _PLAYBACK_TV if tool == "get-playback-state" else {}

    c = _make_connector()
    c._call_tool = _fake
    result = c.call("play", {"uri": "spotify:track:abc123"})
    assert result.ok is True
    play_call = next(x for x in calls if x["tool"] == "start-playback")
    assert play_call["args"]["uris"] == ["spotify:track:abc123"]


def test_play_with_playlist_uri():
    calls: list = []

    def _fake(tool: str, args: dict) -> object:
        calls.append({"tool": tool, "args": args})
        return _PLAYBACK_TV if tool == "get-playback-state" else {}

    c = _make_connector()
    c._call_tool = _fake
    result = c.call("play", {"uri": "spotify:playlist:pl1"})
    assert result.ok is True
    play_call = next(x for x in calls if x["tool"] == "start-playback")
    assert play_call["args"]["context_uri"] == "spotify:playlist:pl1"


def test_pause_returns_true():
    c = _with_tool(_make_connector(), {"pause-playback": {}})
    result = c.call("pause")
    assert result.ok is True
    assert result.data is True


def test_skip_next_returns_true():
    c = _with_tool(_make_connector(), {"skip-to-next": {}})
    result = c.call("skip_next")
    assert result.ok is True
    assert result.data is True


def test_skip_prev_returns_true():
    c = _with_tool(_make_connector(), {"skip-to-previous": {}})
    result = c.call("skip_prev")
    assert result.ok is True
    assert result.data is True


def test_set_volume_returns_true():
    c = _with_tool(_make_connector(), {"set-volume": {}})
    result = c.call("set_volume", {"level": 50})
    assert result.ok is True
    assert result.data is True


def test_set_volume_clamps_above_100():
    called_with: dict = {}

    def _fake(tool: str, args: dict) -> object:
        called_with.update(args)
        return {}

    c = _make_connector()
    c._call_tool = _fake
    c.call("set_volume", {"level": 150})
    assert called_with["volume_percent"] == 100


def test_set_volume_clamps_below_0():
    called_with: dict = {}

    def _fake(tool: str, args: dict) -> object:
        called_with.update(args)
        return {}

    c = _make_connector()
    c._call_tool = _fake
    c.call("set_volume", {"level": -10})
    assert called_with["volume_percent"] == 0


def test_set_volume_missing_level_rejected():
    c = _make_connector()
    result = c.call("set_volume", {})
    assert result.ok is False
    assert result.error == "validation_error"


# ---------------------------------------------------------------------------
# CAP-5: Error envelope
# ---------------------------------------------------------------------------


def test_auth_error_propagates():
    c = _make_connector()

    def _fail(tool, args):
        raise PermissionError

    c._call_tool = _fail
    result = c.call("now_playing")
    assert result.ok is False
    assert result.error == "auth"


def test_timeout_error_propagates():
    c = _make_connector()

    def _fail(tool, args):
        raise TimeoutError

    c._call_tool = _fail
    result = c.call("now_playing")
    assert result.ok is False
    assert result.error == "timeout"
