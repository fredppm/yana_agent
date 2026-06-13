"""
Integration tests for SpotifyMCPConnector.

Requires a running Spotify MCP server and valid OAuth token.

First-time setup:
    1. Create a Spotify app at https://developer.spotify.com/dashboard
       Set redirect URI to http://localhost:8888/callback

    2. Fill in client_id and client_secret in connectors.yaml:
           config:
             client_id: "<your-client-id>"
             client_secret: "<your-client-secret>"
             token_file: "~/.yana/tokens/spotify_fred.json"

    3. Authenticate once (opens browser):
           pip install spotify-mcp
           python -m spotify_mcp auth

    Subsequent runs use the saved token — no browser needed.

Run:
    pytest -m integration tests/test_integration_spotify.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import connectors_setup


@pytest.fixture(scope="module")
def registry():
    return connectors_setup.build_registry()


@pytest.mark.integration
def test_now_playing_returns_dict_or_none(registry):
    result = registry.call("spotify_fred", "now_playing")
    assert result.ok is True, f"call failed: {result.error}"
    if result.data is not None:
        for key in ("track", "artist", "uri", "is_playing", "progress_ms", "duration_ms"):
            assert key in result.data


@pytest.mark.integration
def test_search_returns_list(registry):
    result = registry.call("spotify_fred", "search", {"q": "The Weeknd", "type": "track"})
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)
    if result.data:
        track = result.data[0]
        assert "name" in track
        assert "artist" in track
        assert "uri" in track


@pytest.mark.integration
def test_get_playlists_returns_list(registry):
    result = registry.call("spotify_fred", "get_playlists")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)
    if result.data:
        pl = result.data[0]
        assert "name" in pl
        assert "uri" in pl


@pytest.mark.integration
def test_play_resume_returns_true(registry):
    result = registry.call("spotify_fred", "play")
    assert result.ok is True, f"call failed: {result.error}"
    assert result.data is True


@pytest.mark.integration
def test_pause_returns_true(registry):
    result = registry.call("spotify_fred", "pause")
    assert result.ok is True, f"call failed: {result.error}"
    assert result.data is True


@pytest.mark.integration
def test_set_volume_returns_true(registry):
    result = registry.call("spotify_fred", "set_volume", {"level": 50})
    assert result.ok is True, f"call failed: {result.error}"
    assert result.data is True


@pytest.mark.integration
def test_contract_has_all_operations(registry):
    contract = registry.load_contract("spotify_fred")
    query_names = {q["name"] for q in contract["queries"]}
    command_names = {c["name"] for c in contract["commands"]}
    assert {"now_playing", "search", "get_playlists"} <= query_names
    assert {"play", "pause", "skip_next", "skip_prev", "set_volume"} <= command_names
