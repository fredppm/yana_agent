"""
Contract tests for YouTubeMusicConnector.

yt-dlp search is mocked at _ytdlp_search().
ytmusicapi is only used for library access and is mocked at _ytm.
mpv IPC is mocked at _mpv_cmd() and _launch_mpv() so no real process is needed.

Run with: python -m pytest tests/test_youtube_music_contract.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

_CONNECTOR_FILE = Path(__file__).parent.parent.parent / "connectors" / "youtube_music.py"
_spec = importlib.util.spec_from_file_location("youtube_music", _CONNECTOR_FILE)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

YouTubeMusicConnector = _mod.YouTubeMusicConnector

# ---------------------------------------------------------------------------
# Shared payloads
# ---------------------------------------------------------------------------

_SONG_YTDLP = {
    "title": "Blinding Lights",
    "artist": "The Weeknd",
    "album": None,
    "video_id": "4NRXx6U8ABQ",
    "duration": "3:20",
    "url": "https://music.youtube.com/watch?v=4NRXx6U8ABQ",
}

_PLAYLISTS = [
    {"playlistId": "PLabc123", "title": "Morning Mix", "count": 30},
    {"playlistId": "PLxyz789", "title": "Workout", "count": 45},
]

_EXPECTED_RESULT_KEYS = {"title", "artist", "album", "video_id", "duration", "url"}
_EXPECTED_PLAYLIST_KEYS = {"id", "title", "count", "url"}
_EXPECTED_NOW_PLAYING_KEYS = {"title", "is_playing", "progress_s", "duration_s"}


def _make_connector() -> YouTubeMusicConnector:
    """Return a connector with all external dependencies bypassed."""
    mock_ytm = MagicMock()
    c = YouTubeMusicConnector.__new__(YouTubeMusicConnector)
    c._ytm = mock_ytm  # pre-set so _ensure_ytm() returns immediately
    c._auth_file = Path("/tmp/fake_auth.json")
    c._ipc_socket = "/tmp/yana-ytmusic-test.sock"
    c._mpv = None
    return c


# ---------------------------------------------------------------------------
# CAP-1: Operation discovery
# ---------------------------------------------------------------------------


def test_search_is_query():
    assert "search" in YouTubeMusicConnector._operations
    assert YouTubeMusicConnector._operations["search"].kind == "query"


def test_now_playing_is_query():
    assert "now_playing" in YouTubeMusicConnector._operations
    assert YouTubeMusicConnector._operations["now_playing"].kind == "query"


def test_get_library_playlists_is_query():
    assert "get_library_playlists" in YouTubeMusicConnector._operations
    assert YouTubeMusicConnector._operations["get_library_playlists"].kind == "query"


def test_get_playlist_tracks_is_query():
    assert "get_playlist_tracks" in YouTubeMusicConnector._operations
    assert YouTubeMusicConnector._operations["get_playlist_tracks"].kind == "query"


def test_play_is_command():
    assert "play" in YouTubeMusicConnector._operations
    assert YouTubeMusicConnector._operations["play"].kind == "command"


def test_pause_is_command():
    assert "pause" in YouTubeMusicConnector._operations
    assert YouTubeMusicConnector._operations["pause"].kind == "command"


def test_skip_next_is_command():
    assert "skip_next" in YouTubeMusicConnector._operations
    assert YouTubeMusicConnector._operations["skip_next"].kind == "command"


def test_skip_prev_is_command():
    assert "skip_prev" in YouTubeMusicConnector._operations
    assert YouTubeMusicConnector._operations["skip_prev"].kind == "command"


def test_set_volume_is_command():
    assert "set_volume" in YouTubeMusicConnector._operations
    assert YouTubeMusicConnector._operations["set_volume"].kind == "command"


def test_no_events_declared():
    event_ops = [
        name for name, op in YouTubeMusicConnector._operations.items() if op.kind == "event"
    ]
    assert event_ops == []


# ---------------------------------------------------------------------------
# CAP-1: Descriptions
# ---------------------------------------------------------------------------


def test_all_operations_have_descriptions():
    for name, op in YouTubeMusicConnector._operations.items():
        assert op.description, f"Operation '{name}' has no description"


# ---------------------------------------------------------------------------
# CAP-5: Param schemas
# ---------------------------------------------------------------------------


def test_search_requires_q():
    params = YouTubeMusicConnector._operations["search"].params
    assert params["q"].required is True


def test_search_filter_and_max_optional():
    params = YouTubeMusicConnector._operations["search"].params
    assert params["filter"].required is False
    assert params["max_results"].required is False


def test_play_all_params_optional():
    params = YouTubeMusicConnector._operations["play"].params
    assert params["video_id"].required is False
    assert params["playlist_id"].required is False
    assert params["query"].required is False


def test_set_volume_requires_level():
    params = YouTubeMusicConnector._operations["set_volume"].params
    assert params["level"].required is True


# ---------------------------------------------------------------------------
# Output shape — search (uses _ytdlp_search)
# ---------------------------------------------------------------------------


def test_search_output_shape():
    c = _make_connector()
    c._ytdlp_search = lambda q, max_results: [_SONG_YTDLP]
    result = c.call("search", {"q": "blinding lights"})
    assert result.ok is True
    assert isinstance(result.data, list)
    assert set(result.data[0].keys()) == _EXPECTED_RESULT_KEYS


def test_search_values():
    c = _make_connector()
    c._ytdlp_search = lambda q, max_results: [_SONG_YTDLP]
    result = c.call("search", {"q": "blinding lights"})
    item = result.data[0]
    assert item["title"] == "Blinding Lights"
    assert item["artist"] == "The Weeknd"
    assert item["video_id"] == "4NRXx6U8ABQ"
    assert item["url"] == "https://music.youtube.com/watch?v=4NRXx6U8ABQ"


def test_search_empty_returns_empty_list():
    c = _make_connector()
    c._ytdlp_search = lambda q, max_results: []
    result = c.call("search", {"q": "nonexistent"})
    assert result.ok is True
    assert result.data == []


def test_search_requires_q_param():
    c = _make_connector()
    result = c.call("search", {})
    assert result.ok is False
    assert result.error == "validation_error"


# ---------------------------------------------------------------------------
# Output shape — now_playing
# ---------------------------------------------------------------------------


def test_now_playing_none_when_no_mpv():
    c = _make_connector()
    c._mpv = None
    result = c.call("now_playing")
    assert result.ok is True
    assert result.data is None


def test_now_playing_none_when_mpv_stopped():
    c = _make_connector()
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0  # process exited
    c._mpv = mock_proc
    result = c.call("now_playing")
    assert result.ok is True
    assert result.data is None


def test_now_playing_output_shape():
    c = _make_connector()
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # still running
    c._mpv = mock_proc

    ipc_responses = {
        ("get_property", "media-title"): "Blinding Lights",
        ("get_property", "pause"): False,
        ("get_property", "time-pos"): 45.3,
        ("get_property", "duration"): 200.0,
    }
    c._mpv_cmd = lambda *args: ipc_responses.get(args)

    result = c.call("now_playing")
    assert result.ok is True
    assert set(result.data.keys()) == _EXPECTED_NOW_PLAYING_KEYS
    assert result.data["title"] == "Blinding Lights"
    assert result.data["is_playing"] is True
    assert result.data["progress_s"] == 45.3
    assert result.data["duration_s"] == 200.0


# ---------------------------------------------------------------------------
# Output shape — get_library_playlists (uses _ytm, optional auth)
# ---------------------------------------------------------------------------


def test_get_library_playlists_output_shape():
    c = _make_connector()
    c._ytm.get_library_playlists.return_value = _PLAYLISTS
    result = c.call("get_library_playlists")
    assert result.ok is True
    assert isinstance(result.data, list)
    assert set(result.data[0].keys()) == _EXPECTED_PLAYLIST_KEYS


def test_get_library_playlists_values():
    c = _make_connector()
    c._ytm.get_library_playlists.return_value = _PLAYLISTS
    result = c.call("get_library_playlists")
    assert result.data[0]["id"] == "PLabc123"
    assert result.data[0]["url"] == "https://music.youtube.com/playlist?list=PLabc123"


# ---------------------------------------------------------------------------
# play command — launches mpv
# ---------------------------------------------------------------------------


def test_play_with_video_id():
    c = _make_connector()
    launched = []
    c._launch_mpv = lambda url: launched.append(url)
    result = c.call("play", {"video_id": "4NRXx6U8ABQ"})
    assert result.ok is True
    assert result.data is True
    assert launched == ["https://music.youtube.com/watch?v=4NRXx6U8ABQ"]


def test_play_with_playlist_id():
    c = _make_connector()
    launched = []
    c._launch_mpv = lambda url: launched.append(url)
    result = c.call("play", {"playlist_id": "PLabc123"})
    assert result.ok is True
    assert launched == ["https://music.youtube.com/playlist?list=PLabc123"]


def test_play_with_query_searches_and_plays_top_result():
    c = _make_connector()
    launched = []
    c._launch_mpv = lambda url: launched.append(url)
    c._ytdlp_search = lambda q, max_results: [_SONG_YTDLP]
    result = c.call("play", {"query": "blinding lights"})
    assert result.ok is True
    assert launched == ["https://music.youtube.com/watch?v=4NRXx6U8ABQ"]


def test_play_no_params_returns_error():
    c = _make_connector()
    result = c.call("play", {})
    assert result.ok is False


# ---------------------------------------------------------------------------
# Playback control commands
# ---------------------------------------------------------------------------


def test_pause_sends_cycle_pause():
    c = _make_connector()
    sent = []
    c._mpv_cmd = lambda *args: sent.append(args)
    result = c.call("pause")
    assert result.ok is True
    assert ("cycle", "pause") in sent


def test_skip_next_sends_playlist_next():
    c = _make_connector()
    sent = []
    c._mpv_cmd = lambda *args: sent.append(args)
    result = c.call("skip_next")
    assert result.ok is True
    assert ("playlist-next",) in sent


def test_skip_prev_sends_playlist_prev():
    c = _make_connector()
    sent = []
    c._mpv_cmd = lambda *args: sent.append(args)
    result = c.call("skip_prev")
    assert result.ok is True
    assert ("playlist-prev",) in sent


def test_set_volume_sends_correct_level():
    c = _make_connector()
    sent = []
    c._mpv_cmd = lambda *args: sent.append(args)
    result = c.call("set_volume", {"level": 70})
    assert result.ok is True
    assert ("set_property", "volume", 70) in sent


def test_set_volume_clamps_above_100():
    c = _make_connector()
    sent = []
    c._mpv_cmd = lambda *args: sent.append(args)
    c.call("set_volume", {"level": 150})
    assert ("set_property", "volume", 100) in sent


def test_set_volume_clamps_below_0():
    c = _make_connector()
    sent = []
    c._mpv_cmd = lambda *args: sent.append(args)
    c.call("set_volume", {"level": -5})
    assert ("set_property", "volume", 0) in sent


def test_set_volume_missing_level_rejected():
    c = _make_connector()
    result = c.call("set_volume", {})
    assert result.ok is False
    assert result.error == "validation_error"


# ---------------------------------------------------------------------------
# CAP-5: Error envelope
# ---------------------------------------------------------------------------


def test_search_error_propagates():
    c = _make_connector()

    def _fail(q, max_results):
        raise RuntimeError("yt-dlp unavailable")

    c._ytdlp_search = _fail
    result = c.call("search", {"q": "test"})
    assert result.ok is False


def test_timeout_error_propagates():
    c = _make_connector()

    def _fail(q, max_results):
        raise TimeoutError

    c._ytdlp_search = _fail
    result = c.call("search", {"q": "test"})
    assert result.ok is False
    assert result.error == "timeout"
