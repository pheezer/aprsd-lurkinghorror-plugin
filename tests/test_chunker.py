from aprsd_lurkinghorror_plugin.aprsd_lurkinghorror_plugin import (
    APRS_MAX_LEN,
    chunk_for_aprs,
)


def test_empty_text_returns_ok():
    assert chunk_for_aprs("", 4) == "Ok."
    assert chunk_for_aprs("   \n  ", 4) == "Ok."


def test_short_text_returns_single_string():
    result = chunk_for_aprs("You are in a maze.", 4)
    assert isinstance(result, str)
    assert result == "You are in a maze."


def test_newlines_and_runs_collapse_to_spaces():
    result = chunk_for_aprs("Line one.\n\nLine   two.\tEnd.", 4)
    assert result == "Line one. Line two. End."


def test_long_text_splits_on_word_boundaries_within_width():
    text = " ".join([f"word{i:02d}" for i in range(40)])
    result = chunk_for_aprs(text, max_msgs=10)
    assert isinstance(result, list)
    for chunk in result:
        assert len(chunk) <= APRS_MAX_LEN
        # No chunk starts or ends with a stray space.
        assert chunk == chunk.strip()


def test_cap_adds_more_marker_and_respects_width():
    text = " ".join(["alpha"] * 200)
    result = chunk_for_aprs(text, max_msgs=3)
    assert isinstance(result, list)
    assert len(result) == 3
    assert result[-1].endswith("(more)")
    for chunk in result:
        assert len(chunk) <= APRS_MAX_LEN


def test_word_longer_than_width_is_hard_wrapped():
    giant = "x" * (APRS_MAX_LEN * 2 + 5)
    result = chunk_for_aprs(giant, max_msgs=10)
    assert isinstance(result, list)
    for chunk in result:
        assert len(chunk) <= APRS_MAX_LEN
    # All the x's survive (reassembled).
    assert "".join(result).count("x") == len(giant)
