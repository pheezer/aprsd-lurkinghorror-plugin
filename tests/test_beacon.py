from unittest import mock

import pytest

from aprsd_lurkinghorror_plugin.aprsd_lurkinghorror_plugin import (
    GameBeaconThread,
    GameIdleThread,
)

from .conftest import requires_story

pytestmark = pytest.mark.usefixtures("configured", "reset_session_store")


def _enable_beacon(conf):
    conf.lurking_horror.beacon_enabled = True
    conf.lurking_horror.beacon_latitude = 38.224491
    conf.lurking_horror.beacon_longitude = -85.689713
    conf.lurking_horror.beacon_comment = "Lurking Horror over APRS"
    conf.lurking_horror.beacon_symbol = "("
    conf.lurking_horror.beacon_symbol_table = "/"


def test_beacon_builds_packet_with_custom_comment_and_fog_symbol(configured):
    _enable_beacon(configured)
    configured.callsign = "KK6SPK-3"
    thread = GameBeaconThread()
    with mock.patch(
        "aprsd_lurkinghorror_plugin.aprsd_lurkinghorror_plugin.tx.send"
    ) as mock_send:
        thread._send_beacon()
    assert mock_send.called
    pkt = mock_send.call_args.args[0]
    assert pkt.comment == "Lurking Horror over APRS"
    assert pkt.symbol == "("
    assert pkt.symbol_table == "/"
    assert pkt.from_call == "KK6SPK-3"
    # The rendered payload should carry the themed comment and fog symbol.
    pkt.prepare()
    assert "Lurking Horror over APRS" in pkt.raw
    assert "(" in pkt.raw


def test_beacon_failure_does_not_raise(configured):
    _enable_beacon(configured)
    thread = GameBeaconThread()
    with mock.patch(
        "aprsd_lurkinghorror_plugin.aprsd_lurkinghorror_plugin.tx.send",
        side_effect=RuntimeError("boom"),
    ):
        # Must swallow the error so the thread/daemon survives.
        thread._send_beacon()


def _thread_kinds(configured):
    """Build a plugin and inspect create_threads() WITHOUT letting the aprsd
    plugin base actually start the threads (started threads would run their
    sleep/beacon loops and leak into teardown)."""
    from aprsd_lurkinghorror_plugin.aprsd_lurkinghorror_plugin import (
        LurkingHorrorPlugin,
    )

    with mock.patch.object(LurkingHorrorPlugin, "start_threads"):
        plugin = LurkingHorrorPlugin()
    created = plugin.create_threads()
    # Stop anything create_threads() instantiated so its loop never runs.
    for t in created:
        t.stop()
    return {type(t).__name__ for t in created}


@requires_story
def test_create_threads_includes_beacon_when_enabled_and_located(configured):
    _enable_beacon(configured)
    configured.lurking_horror.session_idle_timeout = 0
    assert "GameBeaconThread" in _thread_kinds(configured)


@requires_story
def test_create_threads_omits_beacon_when_disabled(configured):
    configured.lurking_horror.beacon_enabled = False
    configured.lurking_horror.session_idle_timeout = 0
    assert "GameBeaconThread" not in _thread_kinds(configured)


@requires_story
def test_beacon_enabled_without_coords_is_skipped(configured):
    configured.lurking_horror.beacon_enabled = True
    configured.lurking_horror.beacon_latitude = None
    configured.lurking_horror.beacon_longitude = None
    configured.lurking_horror.session_idle_timeout = 0
    assert "GameBeaconThread" not in _thread_kinds(configured)


def test_idle_thread_still_constructs(configured):
    # Sanity: the sibling thread is unaffected by the beacon addition.
    configured.lurking_horror.session_idle_timeout = 600
    assert GameIdleThread().period >= 60
