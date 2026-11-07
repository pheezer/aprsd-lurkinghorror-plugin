import pytest

from aprsd_lurkinghorror_plugin.engine import GameEngineError, ZMachineEngine

from .conftest import FIXTURE, requires_story

pytestmark = requires_story


@pytest.fixture
def engine():
    return ZMachineEngine(FIXTURE)


def test_new_game_prints_intro_and_returns_state(engine):
    text, blob = engine.run_turn(None, None)
    assert "THE LURKING HORROR" in text
    assert "Terminal Room" in text
    assert isinstance(blob, bytes) and len(blob) > 0


def test_look_from_opening_state(engine):
    _, s0 = engine.run_turn(None, None)
    text, _ = engine.run_turn(s0, "look")
    assert "Terminal Room" in text


def test_turn_is_deterministic_from_same_state(engine):
    _, s0 = engine.run_turn(None, None)
    t1, s1 = engine.run_turn(s0, "look")
    t2, s2 = engine.run_turn(s0, "look")
    assert t1 == t2
    assert s1 == s2


def test_movement_persists_across_snapshots(engine):
    """Moving south then back north returns to the Terminal Room, proving the
    snapshot/restore chain carries world state, not just the opening room."""
    _, s = engine.run_turn(None, None)
    t_south, s = engine.run_turn(s, "go south")
    assert "Second Floor" in t_south
    t_north, s = engine.run_turn(s, "go north")
    assert "Terminal Room" in t_north


def test_restore_rejects_corrupt_blob(engine):
    with pytest.raises(GameEngineError):
        engine.run_turn(b"\x00\x01\x02 not a real snapshot", "look")


def test_bad_story_file_raises():
    with pytest.raises(OSError):
        ZMachineEngine("/nonexistent/path/to/story.z3")
