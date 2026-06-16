"""
tests/test_tui.py — TUI tests using Textual Pilot.

Two tiers:

Unit tests (no marker, no Docker):
  Pure modal interaction (open / validate / cancel) and regressions that do not
  require data to come from a real database.  These run in ~5s and need no
  external services.

Integration tests (@pytest.mark.tui_integration, requires Docker):
  Everything whose correctness depends on data loaded from PostgreSQL —
  session lists, profile lists, navigation between multiple items, create /
  delete round-trips, hint-bar content.  These spin up a real postgres:16-alpine
  container via testcontainers.

  Rule: if the TUI state being tested is populated from the DB, the test MUST
  use a real DB so we validate the full data-loading path, not a hardcoded stub.
  Exception: pure modal interaction (open/close/validate) may stay mocked because
  the modal mechanics are independent of DB shape.

Run:
    pytest tests/test_tui.py -v                    # unit tests only
    pytest tests/test_tui.py -v -m tui_integration # full integration suite
    pytest tests/test_tui.py -v --tb=short         # both
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
from datetime import UTC
from datetime import datetime as dt
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import core
import profiles as _profiles
from strings import t
from textual.widgets import Input, Label
from tui import (
    _NEW,
    NewProfileScreen,
    ProfileSessionScreen,
    RenameProfileScreen,
    YANAApp,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NO_OP_TURN = lambda msgs: "ok"  # noqa: E731  — lightweight LLM stub


def _app(
    profiles: list[dict] | None = None,
    active: str = "",
    sessions: list | None = None,
) -> YANAApp:
    """Build a minimal YANAApp for unit tests — no voice, no real LLM."""
    return YANAApp(
        sessions=sessions or [],
        profiles=profiles or [],
        active_profile_id=active,
        on_turn=_NO_OP_TURN,
    )


def _seed_session(db, profile_id: str, preview: str = "test") -> str:
    """Insert one session row and return its id."""
    sid = f"2024-01-01_10-00-00_{uuid.uuid4().hex[:6]}"
    db.create_session_sync(sid, profile_id, dt.now(UTC).isoformat(), preview, json.dumps([]))
    return sid


# ---------------------------------------------------------------------------
# Unit tests — pure modal interaction + regressions
#
# These tests exercise TUI state-machine logic that is independent of DB shape:
# modal open/cancel/validate, Enter-leak regression, thinking indicator.
# Use mocks sparingly — only to satisfy calls that would reach the DB.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_breath_skips_session_browser():
    """With no profiles and no sessions, app skips the session browser (First Breath)."""
    app = YANAApp(sessions=[], profiles=[], active_profile_id="", on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert not isinstance(app.screen, ProfileSessionScreen)
        assert app.query_one(Input).display is True


@pytest.mark.asyncio
async def test_new_profile_modal_opens_on_n():
    """Pressing 'n' on the session screen pushes NewProfileScreen."""
    app = _app(profiles=[{"id": "some-uuid", "label": "Fred"}], active="some-uuid")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, NewProfileScreen)


@pytest.mark.asyncio
async def test_new_profile_modal_cancel_on_escape():
    """Escape closes NewProfileScreen and returns to ProfileSessionScreen."""
    app = _app(profiles=[{"id": "some-uuid", "label": "Fred"}], active="some-uuid")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, NewProfileScreen)

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ProfileSessionScreen)


@pytest.mark.asyncio
async def test_new_profile_invalid_name_keeps_modal_open():
    """Typing a too-short name and pressing Enter keeps the modal open."""
    app = _app(profiles=[{"id": "some-uuid", "label": "Fred"}], active="some-uuid")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        # Single character — below the 2-char minimum
        await pilot.press("x", "enter")
        await pilot.pause()
        assert isinstance(app.screen, NewProfileScreen)


@pytest.mark.asyncio
async def test_enter_in_modal_does_not_start_chat():
    """
    Regression: after confirming the modal with Enter, the user must remain on
    ProfileSessionScreen — not be dropped into the chat.

    Previously the Enter key leaked through to ProfileSessionScreen.action_confirm()
    which immediately started a new session.
    """
    created: list[str] = []

    def _fake_add(label: str) -> str:
        pid = f"uuid-{label}"
        created.append(pid)
        return pid

    with patch.object(core, "add_profile", side_effect=_fake_add):
        app = _app(
            profiles=[{"id": "some-uuid", "label": "Fred"}],
            active="some-uuid",
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            for ch in "trabalho":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, ProfileSessionScreen)
            assert any("trabalho" in p.lower() for p in created)


@pytest.mark.asyncio
async def test_modal_text_does_not_leak_into_new_profile_chat():
    """
    Regression: text typed in the new-profile modal must not pre-fill the chat
    input after the user opens a session in the newly created profile.

    Previously, Input.value in YANAApp retained characters typed in the modal,
    causing them to appear as a ready-to-send message.  The fix adds a
    _chat_started guard in on_input_submitted.
    """

    def _fake_add(label: str) -> str:
        return f"uuid-{label}"

    with patch.object(core, "add_profile", side_effect=_fake_add):
        app = _app(
            profiles=[{"id": "some-uuid", "label": "Fred"}],
            active="some-uuid",
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            for ch in "trabalho":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            await pilot.press("enter")  # select _NEW in new profile
            await pilot.pause()

            assert app.query_one(Input).value == ""
            assert app._messages == []


@pytest.mark.asyncio
async def test_chat_turn_renders_reply():
    """Typing a message and pressing Enter calls on_turn and stores the reply."""
    turns: list[list[dict]] = []

    def _stub(msgs: list[dict]) -> str:
        turns.append(list(msgs))
        return "hello from YANA"

    app = YANAApp(sessions=[], profiles=[], active_profile_id="", on_turn=_stub)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert not isinstance(app.screen, ProfileSessionScreen)

        for ch in "hi":
            await pilot.press(ch)
        await pilot.press("enter")

        for _ in range(30):
            await pilot.pause(0.1)
            if turns:
                break

        assert len(turns) == 1
        assert turns[0][-1]["content"] == "hi"
        assert any(m["content"] == "hello from YANA" for m in app._messages)


@pytest.mark.asyncio
async def test_thinking_indicator_visible_during_turn():
    """#thinking label is shown while LLM is processing, hidden after reply arrives."""
    started = threading.Event()
    unblock = threading.Event()

    def _blocking_turn(msgs: list[dict]) -> str:
        started.set()
        unblock.wait(timeout=5.0)
        return "reply"

    app = YANAApp(sessions=[], profiles=[], active_profile_id="", on_turn=_blocking_turn)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        for ch in "hi":
            await pilot.press(ch)
        await pilot.press("enter")

        for _ in range(30):
            await pilot.pause(0.1)
            if started.is_set():
                break
        assert started.is_set(), "LLM worker thread never started"

        await pilot.pause()
        thinking = app.query_one("#thinking", Label)
        assert thinking.display is True
        assert str(thinking.content).strip() != "", "thinking label is visible but has no content"
        assert app.query_one(Input).display is True, (
            "Input must remain visible while thinking — user can pre-type"
        )

        unblock.set()
        for _ in range(30):
            await pilot.pause(0.1)
            if not thinking.display:
                break
        assert thinking.display is False


@pytest.mark.asyncio
async def test_thinking_visible_during_first_user_turn_after_auto_greet():
    """After auto-greet, thinking indicator shows when user sends their first message."""
    auto_greet_done = threading.Event()
    turn_started = threading.Event()
    unblock = threading.Event()
    turn_count = [0]

    def _on_turn(msgs: list[dict]) -> str:
        turn_count[0] += 1
        if turn_count[0] == 1:
            auto_greet_done.set()
            return "Hello!"
        turn_started.set()
        unblock.wait(timeout=5.0)
        return "reply"

    app = YANAApp(sessions=[], profiles=[], active_profile_id="", on_turn=_on_turn, auto_greet=True)
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(50):
            await pilot.pause(0.1)
            if auto_greet_done.is_set():
                break
        assert auto_greet_done.is_set(), "auto-greet never completed"
        await pilot.pause(0.3)

        for ch in "hi":
            await pilot.press(ch)
        await pilot.press("enter")

        for _ in range(30):
            await pilot.pause(0.1)
            if turn_started.is_set():
                break
        assert turn_started.is_set(), "user turn never started"

        thinking = app.query_one("#thinking", Label)
        assert thinking.display is True, (
            "thinking not visible during first user turn after auto-greet"
        )
        assert str(thinking.content).strip() != "", "thinking label is visible but has no content"
        assert app.query_one(Input).display is True, (
            "Input must remain visible while thinking — user can pre-type"
        )

        unblock.set()
        for _ in range(30):
            await pilot.pause(0.1)
            if not thinking.display:
                break
        assert thinking.display is False


@pytest.mark.asyncio
async def test_auto_greet_thinking_indicator_visible_immediately():
    """On First Breath (auto_greet=True), the thinking indicator is visible as soon
    as the app opens — before the LLM finishes generating the first message."""
    started = threading.Event()
    unblock = threading.Event()

    def _blocking_turn(msgs: list[dict]) -> str:
        started.set()
        unblock.wait(timeout=5.0)
        return "hello"

    app = YANAApp(
        sessions=[], profiles=[], active_profile_id="", on_turn=_blocking_turn, auto_greet=True
    )
    async with app.run_test(size=(80, 24)) as pilot:
        # Wait for the auto-greet worker to start
        for _ in range(30):
            await pilot.pause(0.1)
            if started.is_set():
                break
        assert started.is_set(), "auto-greet worker never started"

        # Thinking indicator must be visible while LLM is running;
        # Input must remain accessible so user can pre-type
        thinking = app.query_one("#thinking", Label)
        assert thinking.display is True
        assert str(thinking.content).strip() != "", "thinking label is visible but has no content"
        assert app.query_one(Input).display is True, (
            "Input must remain visible during auto-greet — user can pre-type"
        )

        unblock.set()
        for _ in range(30):
            await pilot.pause(0.1)
            if not thinking.display:
                break
        assert thinking.display is False


@pytest.mark.asyncio
async def test_ctrl_d_blocked_when_busy():
    """ctrl+d while a turn is in progress does not exit the app."""
    started = threading.Event()
    unblock = threading.Event()

    def _blocking_turn(msgs: list[dict]) -> str:
        started.set()
        unblock.wait(timeout=5.0)
        return "reply"

    app = YANAApp(sessions=[], profiles=[], active_profile_id="", on_turn=_blocking_turn)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        for ch in "hi":
            await pilot.press(ch)
        await pilot.press("enter")

        for _ in range(30):
            await pilot.pause(0.1)
            if started.is_set():
                break
        assert started.is_set()
        assert app._busy

        # ctrl+d while busy — must be blocked
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert app._busy, "app exited early while turn was still running"

        # Unblock — turn completes, app continues running
        unblock.set()
        for _ in range(30):
            await pilot.pause(0.1)
            if not app._busy:
                break
        assert not app._busy
        assert app._chat_started  # still in chat (didn't exit)


@pytest.mark.asyncio
async def test_escape_from_browser_exits_app():
    """Pressing Escape on the session browser exits the app without starting a chat."""
    app = _app(profiles=[{"id": "some-uuid", "label": "Fred"}], active="some-uuid")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ProfileSessionScreen)
        await pilot.press("escape")
        await pilot.pause()

    assert not app._chat_started


@pytest.mark.asyncio
async def test_rename_profile_modal_opens_on_r():
    """Pressing 'r' on the session browser pushes RenameProfileScreen pre-filled with the current label."""
    app = _app(profiles=[{"id": "some-uuid", "label": "Fred — Default"}], active="some-uuid")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ProfileSessionScreen)

        await pilot.press("r")
        await pilot.pause()

        assert isinstance(app.screen, RenameProfileScreen)
        inp = app.screen.query_one("#rename-profile-input", Input)
        assert inp.value == "Fred — Default"


@pytest.mark.asyncio
async def test_rename_profile_modal_cancel_on_escape():
    """Escape on RenameProfileScreen returns to ProfileSessionScreen without changing the label."""
    app = _app(profiles=[{"id": "some-uuid", "label": "Fred — Default"}], active="some-uuid")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert isinstance(app.screen, RenameProfileScreen)

        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(app.screen, ProfileSessionScreen)
        assert app.screen._profiles[0]["label"] == "Fred — Default"


@pytest.mark.asyncio
async def test_rename_profile_short_name_keeps_modal_open():
    """Typing a single character and pressing Enter keeps RenameProfileScreen open."""
    app = _app(profiles=[{"id": "some-uuid", "label": "Fred — Default"}], active="some-uuid")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert isinstance(app.screen, RenameProfileScreen)

        # Clear the pre-filled value and type a single char
        inp = app.screen.query_one("#rename-profile-input", Input)
        inp.value = ""
        await pilot.press("x", "enter")
        await pilot.pause()

        assert isinstance(app.screen, RenameProfileScreen)


# ---------------------------------------------------------------------------
# Integration tests — real PostgreSQL via testcontainers
#
# All tests that validate TUI state populated from the database live here.
# The `db` fixture (see conftest.py) points store.py at a fresh postgres:16
# container; tables are TRUNCATE'd after each test for isolation.
# ---------------------------------------------------------------------------


# -- Session browser state loaded from DB ------------------------------------


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_profile_session_screen_shows_new_entry(db):
    """After loading a real profile from DB, _NEW is the first entry."""
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    _profiles.set_runtime_profile(profile_id)

    profiles = db.list_profiles_sync()
    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)
        assert screen._entries[0][0] == _NEW


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_single_profile_no_sessions_entry_count(db):
    """With one DB profile and zero sessions, the browser shows exactly one entry (_NEW)."""
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    _profiles.set_runtime_profile(profile_id)

    profiles = db.list_profiles_sync()
    sessions = db.list_sessions_sync(profile_id)
    app = YANAApp(
        sessions=sessions, profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)
        assert len(screen._entries) == 1


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_select_new_session_starts_chat(db):
    """Pressing Enter on _NEW (loaded from real profile) dismisses browser and enters chat."""
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    _profiles.set_runtime_profile(profile_id)

    profiles = db.list_profiles_sync()
    sessions = db.list_sessions_sync(profile_id)
    app = YANAApp(
        sessions=sessions, profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ProfileSessionScreen)

        await pilot.press("enter")
        await pilot.pause()

        assert not isinstance(app.screen, ProfileSessionScreen)
        assert app.query_one(Input).display is True


# -- Hint bar ----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_hint_bar_shows_new_profile_shortcut(db):
    """
    With a single profile the hint bar shows the 'n' new-profile shortcut
    but NOT the 'd' delete shortcut (deleting the last profile is blocked).
    """
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    _profiles.set_runtime_profile(profile_id)

    profiles = db.list_profiles_sync()
    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)

        hint = str(screen.query_one("#session-hint", Label).content)
        assert t("profiles_hint_new") in hint
        assert t("profiles_hint_delete") not in hint


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_hint_bar_multiple_profiles_shows_delete_and_nav(db):
    """
    With two profiles the hint bar shows 'd' delete and the profile navigation
    arrows in addition to the 'n' new-profile shortcut.
    """
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    db.add_profile_sync(owner_id, "Fred — Trabalho")
    _profiles.set_runtime_profile(profile_id)

    profiles = db.list_profiles_sync()
    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)

        hint = str(screen.query_one("#session-hint", Label).content)
        assert t("profiles_hint_new") in hint
        assert t("profiles_hint_delete") in hint
        assert t("profiles_hint_nav") in hint  # contains ← → arrows


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_hint_bar_updates_after_profile_delete(db):
    """
    After deleting one of two profiles the hint bar drops the 'd' delete shortcut
    (only one profile remains — delete is blocked).
    """
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    db.add_profile_sync(owner_id, "Fred — Trabalho")
    _profiles.set_runtime_profile(profile_id)

    profiles = db.list_profiles_sync()
    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)

        hint_before = str(screen.query_one("#session-hint", Label).content)
        assert t("profiles_hint_delete") in hint_before

        await pilot.press("d")
        await pilot.pause()

        hint_after = str(screen.query_one("#session-hint", Label).content)
        assert t("profiles_hint_delete") not in hint_after


# -- Navigation --------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_cursor_moves_up_and_down(db):
    """Up/down arrows navigate DB-loaded sessions; cursor stops at both boundaries."""
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    _profiles.set_runtime_profile(profile_id)
    _seed_session(db, profile_id, "first")
    _seed_session(db, profile_id, "second")

    profiles = db.list_profiles_sync()
    sessions = db.list_sessions_sync(profile_id)
    assert len(sessions) == 2

    app = YANAApp(
        sessions=sessions, profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)
        assert screen._cursor == 0  # starts on _NEW

        await pilot.press("down")
        await pilot.pause()
        assert screen._cursor == 1

        await pilot.press("down")
        await pilot.pause()
        assert screen._cursor == 2  # last entry (_NEW + 2 sessions)

        # Lower boundary — stays at 2
        await pilot.press("down")
        await pilot.pause()
        assert screen._cursor == 2

        await pilot.press("up")
        await pilot.pause()
        assert screen._cursor == 1

        # Upper boundary — stays at 0
        await pilot.press("up")
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        assert screen._cursor == 0


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_profile_navigation_right_changes_active(db):
    """Right arrow advances through DB-loaded profiles; sets active profile in core."""
    owner_id = db.add_owner_sync("Fred")
    db.add_profile_sync(owner_id, "Fred — Default")
    db.add_profile_sync(owner_id, "Fred — Trabalho")

    profiles = db.list_profiles_sync()
    first_id = profiles[0]["id"]
    second_id = profiles[1]["id"]
    _profiles.set_runtime_profile(first_id)

    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=first_id, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)
        assert screen._profile_idx == 0

        await pilot.press("right")
        await pilot.pause()
        assert screen._profile_idx == 1
        assert _profiles.get_active_profile() == second_id

        # Right boundary — already at last profile
        await pilot.press("right")
        await pilot.pause()
        assert screen._profile_idx == 1


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_left_arrow_profile_navigation(db):
    """Left arrow navigates back through DB-loaded profiles and stops at the left boundary."""
    owner_id = db.add_owner_sync("Fred")
    db.add_profile_sync(owner_id, "Fred — Default")
    db.add_profile_sync(owner_id, "Fred — Trabalho")

    profiles = db.list_profiles_sync()
    first_id = profiles[0]["id"]
    second_id = profiles[1]["id"]
    _profiles.set_runtime_profile(second_id)

    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=second_id, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)
        assert screen._profile_idx == 1  # started at second profile

        await pilot.press("left")
        await pilot.pause()
        assert screen._profile_idx == 0
        assert _profiles.get_active_profile() == first_id

        # Left boundary — stays at 0
        await pilot.press("left")
        await pilot.pause()
        assert screen._profile_idx == 0


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_three_profile_navigation_reaches_middle(db):
    """With 3 profiles, each right/left press moves exactly one step — middle must be reachable.
    Regression: double-dispatch bug (BINDINGS + on_key) caused right to skip 0→2, left to skip 2→0.
    """
    owner_id = db.add_owner_sync("Fred")
    db.add_profile_sync(owner_id, "Fred — A")
    db.add_profile_sync(owner_id, "Fred — B")
    db.add_profile_sync(owner_id, "Fred — C")

    profiles = db.list_profiles_sync()
    assert len(profiles) == 3
    first_id = profiles[0]["id"]
    _profiles.set_runtime_profile(first_id)

    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=first_id, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert screen._profile_idx == 0

        await pilot.press("right")
        await pilot.pause()
        assert screen._profile_idx == 1, (
            "middle profile must be reachable (was double-dispatch bug)"
        )

        await pilot.press("right")
        await pilot.pause()
        assert screen._profile_idx == 2

        # Right boundary — stays at 2
        await pilot.press("right")
        await pilot.pause()
        assert screen._profile_idx == 2

        await pilot.press("left")
        await pilot.pause()
        assert screen._profile_idx == 1, "middle profile must be reachable going back"

        await pilot.press("left")
        await pilot.pause()
        assert screen._profile_idx == 0

        # Left boundary — stays at 0
        await pilot.press("left")
        await pilot.pause()
        assert screen._profile_idx == 0


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_profile_switch_reloads_session_list(db):
    """
    Switching to a different profile reloads the session list from the DB.
    Profile A has sessions; profile B does not — after switching to B only _NEW is shown.
    """
    owner_id = db.add_owner_sync("Fred")
    profile_id_1 = db.add_profile_sync(owner_id, "Fred — Default")
    db.add_profile_sync(owner_id, "Fred — Trabalho")

    _seed_session(db, profile_id_1, "session in default")
    # second profile intentionally has no sessions

    profiles = db.list_profiles_sync()
    sessions = db.list_sessions_sync(profile_id_1)
    assert len(sessions) == 1

    # Determine where profile_id_1 lands in UUID-ordered list
    p1_idx = next(i for i, p in enumerate(profiles) if p["id"] == profile_id_1)
    other_idx = 1 - p1_idx
    nav_key = "right" if p1_idx == 0 else "left"
    _profiles.set_runtime_profile(profile_id_1)

    app = YANAApp(
        sessions=sessions, profiles=profiles, active_profile_id=profile_id_1, on_turn=_NO_OP_TURN
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)
        assert len(screen._entries) == 2  # _NEW + 1 session for profile_id_1

        await pilot.press(nav_key)  # switch to the other (empty) profile
        await pilot.pause()

        assert screen._profile_idx == other_idx
        assert len(screen._entries) == 1  # only _NEW — other profile has no sessions


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_select_existing_session_loads_messages(db):
    """
    Selecting an existing session from the browser loads its stored messages
    into app._messages so the conversation continues from where it left off.
    """
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    _profiles.set_runtime_profile(profile_id)

    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    sid = f"2024-01-01_10-00-00_{uuid.uuid4().hex[:6]}"
    db.create_session_sync(
        sid,
        profile_id,
        dt.now(UTC).isoformat(),
        "hello",
        json.dumps(messages),
    )

    sessions = db.list_sessions_sync(profile_id)
    profiles = db.list_profiles_sync()
    app = YANAApp(
        sessions=sessions, profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)
        assert len(screen._entries) == 2  # _NEW + 1 session

        await pilot.press("down")  # move cursor to the existing session
        await pilot.pause()
        assert screen._cursor == 1

        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.1)
            if app._chat_started:
                break

        assert app._chat_started
        assert app._chosen_session == sid
        assert any(m["content"] == "hello" for m in app._messages)
        assert any(m["content"] == "hi there" for m in app._messages)


# -- Delete ------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_delete_blocked_when_only_one_profile(db):
    """Pressing 'd' with a single DB profile does not remove it from TUI or DB."""
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    _profiles.set_runtime_profile(profile_id)

    profiles = db.list_profiles_sync()
    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

        assert isinstance(app.screen, ProfileSessionScreen)
        assert len(app.screen._profiles) == 1

    # DB must also be unchanged
    assert len(db.list_profiles_sync()) == 1


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_delete_removes_profile_from_tui_and_db(db):
    """Pressing 'd' with two DB profiles removes the active one from TUI state and DB."""
    owner_id = db.add_owner_sync("Fred")
    profile_id_1 = db.add_profile_sync(owner_id, "Fred — Default")
    profile_id_2 = db.add_profile_sync(owner_id, "Fred — Trabalho")
    _profiles.set_runtime_profile(profile_id_1)

    profiles = db.list_profiles_sync()
    app = YANAApp(
        sessions=[], profiles=profiles, active_profile_id=profile_id_1, on_turn=_NO_OP_TURN
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)
        assert len(screen._profiles) == 1

    remaining = db.list_profiles_sync()
    ids = [p["id"] for p in remaining]
    assert profile_id_1 not in ids
    assert profile_id_2 in ids


# -- Rename profile ----------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_rename_profile_updates_label_in_tui_and_db(db):
    """
    Renaming a profile via 'r' updates the profile bar immediately
    AND persists the new label to PostgreSQL.
    """
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    _profiles.set_runtime_profile(profile_id)

    profiles = db.list_profiles_sync()
    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)

        await pilot.press("r")
        await pilot.pause()
        assert isinstance(app.screen, RenameProfileScreen)

        # Clear pre-filled value and type new name
        inp = app.screen.query_one("#rename-profile-input", Input)
        inp.value = ""
        for ch in "Fred Pessoal":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ProfileSessionScreen)
        assert screen._profiles[0]["label"] == "Fred Pessoal"

    # Persisted in DB
    updated = db.list_profiles_sync()
    assert updated[0]["label"] == "Fred Pessoal"


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_renamed_profile_label_persists_after_reopen(db):
    """
    A renamed profile label survives closing and reopening the app
    (data reloaded from PostgreSQL).
    """
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    _profiles.set_runtime_profile(profile_id)

    # First run — rename the profile
    profiles = db.list_profiles_sync()
    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        inp = app.screen.query_one("#rename-profile-input", Input)
        inp.value = ""
        for ch in "Fred Pessoal":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()

    # Second run — reload from DB
    profiles2 = db.list_profiles_sync()
    app2 = YANAApp(
        sessions=[], profiles=profiles2, active_profile_id=profile_id, on_turn=_NO_OP_TURN
    )
    async with app2.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen2 = app2.screen
        assert isinstance(screen2, ProfileSessionScreen)
        assert screen2._profiles[0]["label"] == "Fred Pessoal"


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_hint_bar_shows_rename_shortcut(db):
    """The 'r rename' shortcut is visible in the hint bar (always, regardless of profile count)."""
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    _profiles.set_runtime_profile(profile_id)

    profiles = db.list_profiles_sync()
    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)

        hint = str(screen.query_one("#session-hint", Label).content)
        assert t("profiles_hint_rename") in hint


# -- Create profile ----------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_new_profile_appears_in_bar_and_db(db):
    """After creating a profile via TUI it appears in the profile bar AND is in DB."""
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    _profiles.set_runtime_profile(profile_id)

    profiles = db.list_profiles_sync()
    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        for ch in "trabalho":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)
        assert len(screen._profiles) == 2
        assert any(p["label"] == "trabalho" for p in screen._profiles)

    db_profiles = db.list_profiles_sync()
    assert any(p["label"] == "trabalho" for p in db_profiles)


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_new_profile_with_three_existing_profiles(db):
    """
    Regression: pressing 'n' with 3 existing profiles must open NewProfileScreen
    and create the profile cleanly — no error flash, stays on ProfileSessionScreen.

    Previously this worked with 1 profile but may fail with 3 due to DB state,
    profile navigation state, or TUI rendering with more profiles in the bar.
    """
    owner_id = db.add_owner_sync("Fred")
    p1 = db.add_profile_sync(owner_id, "Fred — Work")
    db.add_profile_sync(owner_id, "Fred — Personal")
    db.add_profile_sync(owner_id, "Fred — Study")
    _profiles.set_runtime_profile(p1)

    profiles = db.list_profiles_sync()
    assert len(profiles) == 3

    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=p1, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ProfileSessionScreen)
        assert len(app.screen._profiles) == 3

        # Press 'n' — must push NewProfileScreen, no error
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, NewProfileScreen), "NewProfileScreen did not open"

        # Type a valid name and submit
        for ch in "pessoal2":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        # Must return to session browser — not chat, not error overlay
        assert isinstance(app.screen, ProfileSessionScreen), (
            "Expected ProfileSessionScreen after creating profile with 3 existing"
        )
        assert len(app.screen._profiles) == 4, "New profile must appear in TUI"
        assert any(p["label"] == "pessoal2" for p in app.screen._profiles)

    # Must persist to DB
    db_profiles = db.list_profiles_sync()
    assert any(p["label"] == "pessoal2" for p in db_profiles), "New profile not in DB"


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_new_profile_from_navigated_profile(db):
    """
    Regression: creating a new profile after navigating to the second profile
    (so the active profile in core changed via _on_profile_changed) must not fail.

    The add_profile call uses get_active_profile() to find the owner — this
    must reflect the profile the user navigated to, not the startup default.
    """
    owner_id = db.add_owner_sync("Fred")
    db.add_profile_sync(owner_id, "Fred — A")
    db.add_profile_sync(owner_id, "Fred — B")

    profiles = db.list_profiles_sync()
    first_id = profiles[0]["id"]
    second_id = profiles[1]["id"]
    _profiles.set_runtime_profile(first_id)

    app = YANAApp(sessions=[], profiles=profiles, active_profile_id=first_id, on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)

        # Navigate to the second profile first
        await pilot.press("right")
        await pilot.pause()
        assert screen._profile_idx == 1
        assert _profiles.get_active_profile() == second_id

        # Now press 'n' — owner lookup must use second_id's owner, same owner UUID
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, NewProfileScreen)

        for ch in "newprofile":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, ProfileSessionScreen)
        assert len(app.screen._profiles) == 3
        assert any(p["label"] == "newprofile" for p in app.screen._profiles)

    db_profiles = db.list_profiles_sync()
    assert any(p["label"] == "newprofile" for p in db_profiles)


# -- Session persistence -----------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_create_profile_and_session_persisted_in_db(db):
    """
    Full happy path: create a new profile, open a session, send a message,
    close the app — both profile and session must exist in PostgreSQL.
    """
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    _profiles.set_runtime_profile(profile_id)

    saved: list[tuple[str, str]] = []  # (session_id, profile_id)

    def on_exit(messages: list[dict], session_id: str | None) -> None:
        sid = session_id or f"test-{uuid.uuid4().hex[:8]}"
        active = _profiles.get_active_profile() or profile_id
        db.create_session_sync(
            sid,
            active,
            dt.now(UTC).isoformat(),
            messages[0]["content"][:60] if messages else "",
            json.dumps(messages, ensure_ascii=False),
        )
        saved.append((sid, active))

    profiles = db.list_profiles_sync()
    app = YANAApp(
        sessions=[],
        profiles=profiles,
        active_profile_id=profile_id,
        on_turn=_NO_OP_TURN,
        on_exit=on_exit,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Create new profile via TUI (no mock — writes to real DB)
        await pilot.press("n")
        await pilot.pause()
        for ch in "trabalho":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        # Select new session in the new profile
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.1)
            if app._chat_started:
                break
        assert app._chat_started, "_start_chat() was never called after selecting new session"

        # Send a message (required for on_exit to fire)
        for ch in "oi":
            await pilot.press(ch)
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.1)
            if not app._busy:
                break
        assert len(app._messages) == 2

        # Exit — ctrl+d has priority=True so it beats the Input widget
        await pilot.press("ctrl+d")
        for _ in range(50):
            await pilot.pause(0.1)
            if saved:
                break

    assert len(saved) == 1
    _, saved_profile_id = saved[0]
    # The saved profile is a UUID (the new "trabalho" profile created via TUI)
    assert saved_profile_id != profile_id  # must be the new profile, not the original
    db_profiles = db.list_profiles_sync()
    assert any(p["id"] == saved_profile_id for p in db_profiles)
    assert any(p["label"] == "trabalho" for p in db_profiles)


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_session_visible_in_browser_after_reopen(db):
    """
    A session stored in PostgreSQL appears in the session browser when the app is
    reopened with sessions loaded from the DB.
    """
    owner_id = db.add_owner_sync("Fred")
    profile_id = db.add_profile_sync(owner_id, "Fred — Default")
    _profiles.set_runtime_profile(profile_id)

    session_id = _seed_session(db, profile_id, "hello world")

    sessions = db.list_sessions_sync(profile_id)
    profiles = db.list_profiles_sync()
    app = YANAApp(
        sessions=sessions, profiles=profiles, active_profile_id=profile_id, on_turn=_NO_OP_TURN
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProfileSessionScreen)
        assert len(screen._entries) == 2  # _NEW + 1 stored session
        assert session_id in [sid for sid, _ in screen._entries]


# -- Data isolation ----------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_delete_profile_purges_sessions_no_data_recovery(db):
    """
    Deleting a profile removes all its sessions from PostgreSQL.
    A newly created profile (with a new UUID) starts with no sessions
    — no ghost data from any previous profile.
    """
    owner_id = db.add_owner_sync("Fred")
    profile_id_1 = db.add_profile_sync(owner_id, "Fred — Default")
    profile_id_2 = db.add_profile_sync(owner_id, "Fred — Trabalho")
    _profiles.set_runtime_profile(profile_id_1)

    _seed_session(db, profile_id_2, "old session")
    assert len(db.list_sessions_sync(profile_id_2)) == 1

    # Delete second profile via TUI — start already on profile_id_2 to avoid
    # relying on UUID sort order when navigating with arrow keys
    profiles = db.list_profiles_sync()
    app = YANAApp(
        sessions=[], profiles=profiles, active_profile_id=profile_id_2, on_turn=_NO_OP_TURN
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

    # Sessions for the deleted profile must be gone
    assert len(db.list_sessions_sync(profile_id_2)) == 0

    # Create a brand-new profile via TUI — must start with zero sessions
    remaining_profiles = db.list_profiles_sync()
    app2 = YANAApp(
        sessions=[],
        profiles=remaining_profiles,
        active_profile_id=profile_id_1,
        on_turn=_NO_OP_TURN,
    )
    async with app2.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        for ch in "trabalho":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

    # New profile has a fresh UUID — verify it has no sessions
    all_profiles = db.list_profiles_sync()
    new_profile = next((p for p in all_profiles if p["label"] == "trabalho"), None)
    assert new_profile is not None
    assert new_profile["id"] != profile_id_2  # different UUID
    assert len(db.list_sessions_sync(new_profile["id"])) == 0


# ---------------------------------------------------------------------------
# ctrl+b — switch session shortcut
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ctrl_b_opens_session_browser_from_chat():
    """ctrl+b in Chat pushes ProfileSessionScreen (session browser)."""
    profiles = [{"id": "p1", "label": "Fred"}]
    app = YANAApp(
        sessions=[],
        profiles=profiles,
        active_profile_id="p1",
        on_turn=_NO_OP_TURN,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ProfileSessionScreen)

        # Open a new session (Enter on _NEW)
        with patch.object(core, "list_sessions", return_value=[]):
            await pilot.press("enter")
            await pilot.pause()
        assert app._chat_started

        # ctrl+b must push the session browser
        with patch.object(core, "list_sessions", return_value=[]):
            await pilot.press("ctrl+b")
            await pilot.pause()

        assert isinstance(app.screen, ProfileSessionScreen)


@pytest.mark.asyncio
async def test_ctrl_b_dismissed_stays_in_chat():
    """Pressing Escape on the session browser opened via ctrl+b returns to Chat without resetting it."""
    profiles = [{"id": "p1", "label": "Fred"}]
    app = YANAApp(
        sessions=[],
        profiles=profiles,
        active_profile_id="p1",
        on_turn=_NO_OP_TURN,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        with patch.object(core, "list_sessions", return_value=[]):
            await pilot.press("enter")
            await pilot.pause()
        assert app._chat_started

        with patch.object(core, "list_sessions", return_value=[]):
            await pilot.press("ctrl+b")
            await pilot.pause()
        assert isinstance(app.screen, ProfileSessionScreen)

        # Dismiss — must return to Chat
        await pilot.press("escape")
        await pilot.pause()

        assert app._chat_started
        assert not isinstance(app.screen, ProfileSessionScreen)
        assert app._messages == []  # no messages: nothing was reset


@pytest.mark.asyncio
async def test_ctrl_b_not_available_during_first_breath():
    """ctrl+b is a no-op during First Breath (no profiles exist)."""
    app = YANAApp(sessions=[], profiles=[], active_profile_id="", on_turn=_NO_OP_TURN)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app._chat_started  # First Breath → direct to Chat

        await pilot.press("ctrl+b")
        await pilot.pause()

        # No browser should have been pushed
        assert not isinstance(app.screen, ProfileSessionScreen)


@pytest.mark.asyncio
async def test_ctrl_b_blocked_when_busy():
    """ctrl+b while a turn is in progress does not open the session browser."""
    started = threading.Event()
    unblock = threading.Event()

    def _blocking_turn(msgs: list[dict]) -> str:
        started.set()
        unblock.wait(timeout=5.0)
        return "reply"

    profiles = [{"id": "p1", "label": "Fred"}]
    app = YANAApp(
        sessions=[],
        profiles=profiles,
        active_profile_id="p1",
        on_turn=_blocking_turn,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        with patch.object(core, "list_sessions", return_value=[]):
            await pilot.press("enter")
            await pilot.pause()
        assert app._chat_started

        for ch in "hi":
            await pilot.press(ch)
        await pilot.press("enter")

        for _ in range(30):
            await pilot.pause(0.1)
            if started.is_set():
                break
        assert app._busy

        await pilot.press("ctrl+b")
        await pilot.pause()

        # Browser must NOT have been pushed while busy
        assert not isinstance(app.screen, ProfileSessionScreen)

        # Unblock the turn and wait for it to finish before exiting
        unblock.set()
        for _ in range(30):
            await pilot.pause(0.1)
            if not app._busy:
                break
        assert not app._busy


# ---------------------------------------------------------------------------
# Profile ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_limit_blocks_new_profile_modal():
    """Pressing 'n' when 5 profiles exist shows a flash message and does not open the modal."""
    profiles = [{"id": f"p{i}", "label": f"Profile {i}"} for i in range(5)]
    app = YANAApp(
        sessions=[],
        profiles=profiles,
        active_profile_id="p0",
        on_turn=_NO_OP_TURN,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ProfileSessionScreen)

        await pilot.press("n")
        await pilot.pause()

        # Modal must NOT have been pushed
        assert isinstance(app.screen, ProfileSessionScreen)
        # Flash message must be active
        assert app.screen._flash_ticks > 0


@pytest.mark.asyncio
@pytest.mark.tui_integration
async def test_profiles_ordered_by_creation_time(db):
    """Profiles are returned in creation order, not UUID or label order."""
    owner_id = db.add_owner_sync("Fred")
    pid1 = db.add_profile_sync(owner_id, "zzz")  # created first
    pid2 = db.add_profile_sync(owner_id, "aaa")  # created second
    pid3 = db.add_profile_sync(owner_id, "mmm")  # created third

    profiles = db.list_profiles_sync()
    assert [p["id"] for p in profiles] == [pid1, pid2, pid3], (
        "profiles must preserve creation order regardless of label or UUID"
    )
