import datetime

import pytest

from aprsd_lurkinghorror_plugin.session import (
    GameSessionStore,
    sanitize_callsign,
)

pytestmark = pytest.mark.usefixtures("reset_session_store")


def test_sanitize_callsign_strips_ssid_punctuation():
    assert sanitize_callsign("w1aw-7") == "W1AW-7"
    assert sanitize_callsign("k j 6!@#abc") == "KJ6ABC"
    assert sanitize_callsign(None) == ""


def test_get_state_none_when_no_session():
    store = GameSessionStore()
    assert store.get_state("W1AW") is None


def test_record_and_get_roundtrip_bytes():
    store = GameSessionStore()
    blob = bytes(range(256)) * 4  # arbitrary binary, exercises base64
    store.record_turn("W1AW", blob)
    assert store.get_state("W1AW") == blob


def test_record_turn_increments_and_tracks_metadata():
    store = GameSessionStore()
    store.record_turn("W1AW", b"a")
    store.record_turn("W1AW", b"bb")
    entry = store.get("W1AW")
    assert entry["turns"] == 2
    assert "started_at" in entry and "last_activity" in entry
    # Latest blob wins.
    assert store.get_state("W1AW") == b"bb"


def test_ssid_variants_map_to_same_session():
    store = GameSessionStore()
    store.record_turn("w1aw", b"x")
    assert store.get_state("W1AW") == b"x"


def test_delete_removes_session():
    store = GameSessionStore()
    store.record_turn("W1AW", b"x")
    store.delete("W1AW")
    assert store.get_state("W1AW") is None


def test_corrupt_state_is_dropped_gracefully():
    store = GameSessionStore()
    store.data[sanitize_callsign("W1AW")] = {"state_b64": "!!!not base64!!!"}
    assert store.get_state("W1AW") is None
    assert store.get("W1AW") is None


def test_expire_idle_removes_old_sessions():
    store = GameSessionStore()
    store.record_turn("OLD", b"x")
    store.record_turn("NEW", b"y")
    # Backdate OLD well beyond the timeout.
    old_ts = (datetime.datetime.now() - datetime.timedelta(hours=2)).isoformat()
    store.data[sanitize_callsign("OLD")]["last_activity"] = old_ts

    expired = store.expire_idle(timeout_seconds=3600)
    assert sanitize_callsign("OLD") in expired
    assert store.get_state("OLD") is None
    assert store.get_state("NEW") == b"y"


def test_expire_idle_disabled_when_timeout_zero():
    store = GameSessionStore()
    store.record_turn("W1AW", b"x")
    assert store.expire_idle(0) == []
    assert store.get_state("W1AW") == b"x"


def test_state_persists_to_disk_and_reloads(tmp_path):
    """record_turn writes JSON to disk; a fresh store instance load()s it back,
    simulating survival across a daemon restart."""
    from oslo_config import cfg

    CONF = cfg.CONF
    CONF.enable_save = True
    CONF.save_location = str(tmp_path)

    blob = bytes(range(200))
    store = GameSessionStore()
    store.record_turn("W1AW", blob)

    # Simulate a restart: drop the singleton and reload from disk.
    GameSessionStore._instance = None
    reloaded = GameSessionStore()
    reloaded.load()
    assert reloaded.get_state("W1AW") == blob
