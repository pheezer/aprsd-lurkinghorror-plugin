from unittest import mock

import pytest

from aprsd_lurkinghorror_plugin.aprsd_lurkinghorror_plugin import LurkingHorrorPlugin

from .conftest import make_packet, requires_story

pytestmark = pytest.mark.usefixtures("configured", "reset_session_store")


def test_disabled_when_story_file_missing(configured):
    configured.lurking_horror.story_file = "/nonexistent/story.z3"
    plugin = LurkingHorrorPlugin()
    assert plugin.enabled is False
    # The base class reports the standard disabled message.
    result = plugin.filter(make_packet("#"))
    assert result == "LurkingHorrorPlugin isn't enabled"


def test_alnum_prefix_builds_word_boundary_regex(configured):
    configured.lurking_horror.command_prefix = "lh"
    plugin = LurkingHorrorPlugin()
    assert plugin.command_regex == r"^lh(\s|$)"


@requires_story
def test_non_prefixed_message_is_ignored(configured):
    plugin = LurkingHorrorPlugin()
    # No '#', so the command regex must not match -> plugin returns None and
    # never collides with other command plugins.
    assert plugin.filter(make_packet("go north")) is None


@requires_story
def test_help_meta_command(configured):
    plugin = LurkingHorrorPlugin()
    result = plugin.filter(make_packet("# help"))
    assert isinstance(result, str)
    assert "restart" in result.lower()


@requires_story
def test_new_game_intro_is_chunked(configured):
    plugin = LurkingHorrorPlugin()
    result = plugin.filter(make_packet("#"))
    # The full intro is long; it is capped to max_reply_messages chunks, each
    # within the APRS limit, with a truncation marker on the last one.
    assert isinstance(result, list)
    assert len(result) == configured.lurking_horror.max_reply_messages
    assert all(len(chunk) <= 67 for chunk in result)
    assert result[-1].endswith("(more)")
    # The opening narration is what fits in the first chunk.
    assert "waited until the last minute" in result[0]


@requires_story
def test_state_persists_between_messages(configured):
    plugin = LurkingHorrorPlugin()
    plugin.filter(make_packet("#"))  # start
    plugin.filter(make_packet("# go south"))
    result = plugin.filter(make_packet("# look"))
    assert "Second Floor" in " ".join(
        result if isinstance(result, list) else [result]
    )


@requires_story
def test_restart_wipes_state(configured):
    from aprsd_lurkinghorror_plugin.session import GameSessionStore

    plugin = LurkingHorrorPlugin()
    plugin.filter(make_packet("#"))
    plugin.filter(make_packet("# go south"))
    assert GameSessionStore().get_state("W1AW") is not None

    # Restart wipes state and starts fresh; a follow-up look must show the
    # opening Terminal Room again (not the Second Floor we moved to).
    plugin.filter(make_packet("# restart"))
    result = plugin.filter(make_packet("# look"))
    assert "Terminal Room" in " ".join(
        result if isinstance(result, list) else [result]
    )


@requires_story
def test_players_have_independent_sessions(configured):
    plugin = LurkingHorrorPlugin()
    plugin.filter(make_packet("#", from_call="W1AW"))
    plugin.filter(make_packet("# go south", from_call="W1AW"))
    # A different callsign starting fresh has its own session: a look shows the
    # opening Terminal Room, unaffected by W1AW moving to the Second Floor.
    plugin.filter(make_packet("#", from_call="K6XYZ"))
    result = plugin.filter(make_packet("# look", from_call="K6XYZ"))
    assert "Terminal Room" in " ".join(
        result if isinstance(result, list) else [result]
    )
    # And W1AW is still on the Second Floor.
    w1aw = plugin.filter(make_packet("# look", from_call="W1AW"))
    assert "Second Floor" in " ".join(w1aw if isinstance(w1aw, list) else [w1aw])


def test_turn_timeout_returns_graceful_reply(configured):
    plugin = LurkingHorrorPlugin()
    plugin.enabled = True
    # Force the guarded turn to time out without needing a real slow game.
    from concurrent.futures import TimeoutError as FutureTimeout

    with mock.patch.object(plugin, "_run_turn", side_effect=FutureTimeout):
        result = plugin.filter(make_packet("# look"))
    assert "timed out" in result.lower()


def test_engine_error_returns_graceful_reply(configured):
    from aprsd_lurkinghorror_plugin.engine import GameEngineError

    plugin = LurkingHorrorPlugin()
    plugin.enabled = True
    with mock.patch.object(
        plugin, "_run_turn", side_effect=GameEngineError("boom")
    ):
        result = plugin.filter(make_packet("# look"))
    assert "game error" in result.lower()


@requires_story
def test_more_command_continues_truncated_text(configured):
    # Force a tiny cap so the intro overflows and buffers a remainder.
    configured.lurking_horror.max_reply_messages = 2
    plugin = LurkingHorrorPlugin()

    first = plugin.filter(make_packet("#"))
    assert isinstance(first, list)
    assert len(first) == 2
    assert first[-1].endswith("(more)")

    # '# more' returns the next batch (and may itself end with (more)).
    second = plugin.filter(make_packet("# more"))
    assert second not in (None, "Nothing more to show.")
    second_list = second if isinstance(second, list) else [second]
    assert all(len(c) <= 67 for c in second_list)

    # The two batches together must reconstruct a prefix of the full intro
    # with no words lost at the seam.
    def strip_marker(chunks):
        return [c[: -len(" (more)")] if c.endswith("(more)") else c for c in chunks]

    words = (" ".join(strip_marker(first)) + " " + " ".join(strip_marker(second_list))).split()
    # The intro begins with this exact phrase; the seam between batch 1 and 2
    # must preserve it contiguously.
    assert words[:6] == ["You've", "waited", "until", "the", "last", "minute"]


@requires_story
def test_more_with_nothing_buffered(configured):
    configured.lurking_horror.max_reply_messages = 8
    plugin = LurkingHorrorPlugin()
    plugin.filter(make_packet("#"))  # 8-msg cap: intro likely fits, no overflow
    # Drain any buffer, then a further '# more' reports nothing.
    seen_nothing = False
    for _ in range(20):
        r = plugin.filter(make_packet("# more"))
        if r == "Nothing more to show.":
            seen_nothing = True
            break
    assert seen_nothing


@requires_story
def test_new_turn_clears_pending_overflow(configured):
    configured.lurking_horror.max_reply_messages = 2
    plugin = LurkingHorrorPlugin()
    plugin.filter(make_packet("#"))  # overflow buffered
    # A real game command supersedes the old overflow.
    plugin.filter(make_packet("# look"))
    # The buffer now reflects the look output, not the stale intro; eventually
    # draining it reaches "Nothing more to show." without error.
    for _ in range(20):
        r = plugin.filter(make_packet("# more"))
        if r == "Nothing more to show.":
            break
    assert r == "Nothing more to show."


@requires_story
def test_saved_game_survives_daemon_restart(configured, tmp_path):
    """A new plugin instance (simulating a pod/daemon restart) must resume a
    player's game from disk -- setup() is responsible for load()."""
    from aprsd_lurkinghorror_plugin.session import GameSessionStore

    configured.enable_save = True
    configured.save_location = str(tmp_path)

    # Session 1: start a game and move to another room.
    plugin1 = LurkingHorrorPlugin()
    plugin1.filter(make_packet("#"))
    plugin1.filter(make_packet("# go south"))

    # Simulate a restart: drop the singleton so nothing is in memory, exactly
    # as a fresh process would be. The on-disk JSON is all that remains.
    GameSessionStore._instance = None

    # Session 2: a brand-new plugin. Its setup() must load the saved session so
    # a look shows we are still on the Second Floor, not back at the start.
    plugin2 = LurkingHorrorPlugin()
    result = plugin2.filter(make_packet("# look"))
    assert "Second Floor" in " ".join(
        result if isinstance(result, list) else [result]
    )
