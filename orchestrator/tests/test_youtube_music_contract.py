"""
Contract tests for YouTubeMusicConnector.

ytmusicapi is mocked at the YTMusic class level — no real auth or network needed.

Run with: python -m pytest tests/test_youtube_music_contract.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

_CONNECTOR_FILE = Path(__file__).parent.parent.parent / "connectors" / "youtube_music.py"
_spec = importlib.util.spec_from_file_location("youtube_music", _CONNECTOR_FILE)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]

# Mock ytmusicapi before module load
_mock_ytm_instance = MagicMock()
_mock_ytm_class = MagicMock(return_value=_mock_ytm_instance)
with patch.dict("sys.modules", {"ytmusicapi": MagicMock(YTMusic=_mock_ytm_class)}):
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]

YouTubeMusicConnector = _mod.YouTubeMusicConnector

# ---------------------------------------------------------------------------
# Shared response payloads
# ---------------------------------------------------------------------------

_SONG = {
    "title": "Blinding Lights",
    "artists": [{"name": "The Weeknd"}],
    "album": {"name": "After Hours"},
    "videoId": "4NRXx6U8ABQ",
    "duration": "3:20",
}

_SEARCH_RESULTS = [_SONG]

_PLAYLISTS = [
    {"playlistId": "PLabc123", "title": "Morning Mix", "count": 30},
    {"playlistId": "PLxyz789", "title": "Workout", "count": 45},
]

_PLAYLIST_DETAIL = {"tracks": [_SONG]}

_EXPECTED_RESULT_KEYS = {"title", "artist", "album", "video_id", "duration", "url"}
_EXPECTED_PLAYLIST_KEYS = {"id", "title", "count", "url"}


def _make_connector() -> YouTubeMusicConnector:
    mock_ytm = MagicMock()
    with patch.dict("sys.modules", {"ytmusicapi": MagicMock(YTMusic=MagicMock(return_value=mock_ytm))}):
        connector = YouTubeMusicConnector.__new__(YouTubeMusicConnector)
        connector._ytm = mock_ytm
        connector._player = "browser"
    return connector


# ---------------------------------------------------------------------------
# CAP-1: Operation discovery
# ---------------------------------------------------------------------------


def test_search_is_query():
    assert "search" in YouTubeMusicConnector._operations
    assert YouTubeMusicConnector._operations["search"].kind == "query"


def test_get_library_playlists_is_query():
    assert "get_library_playlists" in YouTubeMusicConnector._operations
    assert YouTubeMusicConnector._operations["get_library_playlists"].kind == "query"


def test_get_playlist_tracks_is_query():
    assert "get_playlist_tracks" in YouTubeMusicConnector._operations
    assert YouTubeMusicConnector._operations["get_playlist_tracks"].kind == "query"


def test_open_is_command():
    assert "open" in YouTubeMusicConnector._operations
    assert YouTubeMusicConnector._operations["open"].kind == "command"


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


def test_get_playlist_tracks_requires_playlist_id():
    params = YouTubeMusicConnector._operations["get_playlist_tracks"].params
    assert params["playlist_id"].required is True


def test_open_both_params_optional():
    params = YouTubeMusicConnector._operations["open"].params
    assert params["video_id"].required is False
    assert params["playlist_id"].required is False


# ---------------------------------------------------------------------------
# Output shape — search
# ---------------------------------------------------------------------------


def test_search_output_shape():
    c = _make_connector()
    c._ytm.search.return_value = _SEARCH_RESULTS
    result = c.call("search", {"q": "blinding lights"})
    assert result.ok is True
    assert isinstance(result.data, list)
    assert len(result.data) == 1
    assert set(result.data[0].keys()) == _EXPECTED_RESULT_KEYS


def test_search_values():
    c = _make_connector()
    c._ytm.search.return_value = _SEARCH_RESULTS
    result = c.call("search", {"q": "blinding lights"})
    item = result.data[0]
    assert item["title"] == "Blinding Lights"
    assert item["artist"] == "The Weeknd"
    assert item["album"] == "After Hours"
    assert item["video_id"] == "4NRXx6U8ABQ"
    assert item["url"] == "https://music.youtube.com/watch?v=4NRXx6U8ABQ"


def test_search_empty_returns_empty_list():
    c = _make_connector()
    c._ytm.search.return_value = []
    result = c.call("search", {"q": "nonexistent"})
    assert result.ok is True
    assert result.data == []


def test_search_requires_q_param():
    c = _make_connector()
    result = c.call("search", {})
    assert result.ok is False
    assert result.error == "validation_error"


# ---------------------------------------------------------------------------
# Output shape — get_library_playlists
# ---------------------------------------------------------------------------


def test_get_library_playlists_output_shape():
    c = _make_connector()
    c._ytm.get_library_playlists.return_value = _PLAYLISTS
    result = c.call("get_library_playlists")
    assert result.ok is True
    assert isinstance(result.data, list)
    assert len(result.data) == 2
    assert set(result.data[0].keys()) == _EXPECTED_PLAYLIST_KEYS


def test_get_library_playlists_values():
    c = _make_connector()
    c._ytm.get_library_playlists.return_value = _PLAYLISTS
    result = c.call("get_library_playlists")
    assert result.data[0]["id"] == "PLabc123"
    assert result.data[0]["title"] == "Morning Mix"
    assert result.data[0]["count"] == 30
    assert result.data[0]["url"] == "https://music.youtube.com/playlist?list=PLabc123"


# ---------------------------------------------------------------------------
# Output shape — get_playlist_tracks
# ---------------------------------------------------------------------------


def test_get_playlist_tracks_output_shape():
    c = _make_connector()
    c._ytm.get_playlist.return_value = _PLAYLIST_DETAIL
    result = c.call("get_playlist_tracks", {"playlist_id": "PLabc123"})
    assert result.ok is True
    assert isinstance(result.data, list)
    assert set(result.data[0].keys()) == _EXPECTED_RESULT_KEYS


# ---------------------------------------------------------------------------
# open command
# ---------------------------------------------------------------------------


def test_open_with_video_id_uses_browser(monkeypatch):
    c = _make_connector()
    opened_urls = []
    monkeypatch.setattr(_mod.webbrowser, "open", lambda url: opened_urls.append(url))
    result = c.call("open", {"video_id": "4NRXx6U8ABQ"})
    assert result.ok is True
    assert result.data is True
    assert opened_urls == ["https://music.youtube.com/watch?v=4NRXx6U8ABQ"]


def test_open_with_playlist_id_uses_playlist_url(monkeypatch):
    c = _make_connector()
    opened_urls = []
    monkeypatch.setattr(_mod.webbrowser, "open", lambda url: opened_urls.append(url))
    result = c.call("open", {"playlist_id": "PLabc123"})
    assert result.ok is True
    assert opened_urls == ["https://music.youtube.com/playlist?list=PLabc123"]


def test_open_with_mpv_calls_subprocess(monkeypatch):
    c = _make_connector()
    c._player = "mpv"
    launched = []
    monkeypatch.setattr(_mod.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd))
    result = c.call("open", {"video_id": "4NRXx6U8ABQ"})
    assert result.ok is True
    assert launched[0] == ["mpv", "https://music.youtube.com/watch?v=4NRXx6U8ABQ"]


def test_open_no_id_returns_error():
    c = _make_connector()
    result = c.call("open", {})
    assert result.ok is False


# ---------------------------------------------------------------------------
# CAP-5: Error envelope
# ---------------------------------------------------------------------------


def test_auth_error_propagates():
    c = _make_connector()
    c._ytm.search.side_effect = PermissionError
    result = c.call("search", {"q": "test"})
    assert result.ok is False
    assert result.error == "auth"


def test_timeout_error_propagates():
    c = _make_connector()
    c._ytm.search.side_effect = TimeoutError
    result = c.call("search", {"q": "test"})
    assert result.ok is False
    assert result.error == "timeout"
