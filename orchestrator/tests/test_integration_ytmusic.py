"""
Integration tests for YouTubeMusicConnector.

Requires ytmusicapi authenticated and mpv + yt-dlp installed.

First-time setup:
    1. Install dependencies:
           pip install ytmusicapi
           winget install mpv          # Windows
           pip install yt-dlp

    2. Authenticate ytmusicapi once (opens browser):
           python -c "
           from ytmusicapi import YTMusic
           YTMusic.setup(filepath='~/.yana/ytmusic_auth.json')
           "

    Subsequent runs use the saved token — no browser needed.

Run:
    pytest -m integration tests/test_integration_ytmusic.py -v

Note: test_play_* tests launch real mpv and play audio briefly.
      Run with headphones or mute system volume if needed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import connectors_setup


@pytest.fixture(scope="module")
def registry():
    return connectors_setup.build_registry()


@pytest.mark.integration
def test_search_returns_list(registry):
    result = registry.call("ytmusic_fred", "search", {"q": "The Weeknd", "filter": "songs"})
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)
    if result.data:
        item = result.data[0]
        assert "title" in item
        assert "artist" in item
        assert "video_id" in item
        assert "url" in item


@pytest.mark.integration
def test_search_empty_query_returns_results(registry):
    result = registry.call("ytmusic_fred", "search", {"q": "jazz", "filter": "songs", "max_results": 3})
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)
    assert len(result.data) <= 3


@pytest.mark.integration
def test_get_library_playlists_returns_list(registry):
    result = registry.call("ytmusic_fred", "get_library_playlists")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)
    if result.data:
        pl = result.data[0]
        assert "id" in pl
        assert "title" in pl
        assert "url" in pl


@pytest.mark.integration
def test_now_playing_none_when_idle(registry):
    # mpv not running at start — should return None cleanly
    result = registry.call("ytmusic_fred", "now_playing")
    assert result.ok is True, f"call failed: {result.error}"
    # data may be None (no mpv) or a dict (mpv was already running)
    assert result.data is None or isinstance(result.data, dict)


@pytest.mark.integration
def test_play_video_launches_mpv(registry):
    # Search for a short track and play it briefly
    search = registry.call("ytmusic_fred", "search", {"q": "lofi chill", "filter": "songs", "max_results": 1})
    assert search.ok and search.data, "search returned nothing"

    video_id = search.data[0]["video_id"]
    assert video_id, "no video_id in search result"

    result = registry.call("ytmusic_fred", "play", {"video_id": video_id})
    assert result.ok is True, f"play failed: {result.error}"
    assert result.data is True

    # Give mpv a moment to start
    time.sleep(2)

    now = registry.call("ytmusic_fred", "now_playing")
    assert now.ok is True


@pytest.mark.integration
def test_pause_after_play(registry):
    result = registry.call("ytmusic_fred", "pause")
    assert result.ok is True, f"pause failed: {result.error}"
    assert result.data is True


@pytest.mark.integration
def test_set_volume_returns_true(registry):
    result = registry.call("ytmusic_fred", "set_volume", {"level": 40})
    assert result.ok is True, f"set_volume failed: {result.error}"
    assert result.data is True


@pytest.mark.integration
def test_contract_has_all_operations(registry):
    contract = registry.load_contract("ytmusic_fred")
    query_names = {q["name"] for q in contract["queries"]}
    command_names = {c["name"] for c in contract["commands"]}
    assert {"now_playing", "search", "get_library_playlists", "get_playlist_tracks"} <= query_names
    assert {"play", "pause", "skip_next", "skip_prev", "set_volume"} <= command_names
