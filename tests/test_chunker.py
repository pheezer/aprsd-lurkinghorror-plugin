from aprsd_lurkinghorror_plugin.aprsd_lurkinghorror_plugin import (
    APRS_MAX_LEN,
    chunk_for_aprs,
    take_batch,
    wrap_chunks,
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


# --- take_batch / wrap_chunks (the # more machinery) ---------------------


def test_wrap_chunks_is_lossless_and_within_width():
    text = " ".join([f"word{i:02d}" for i in range(50)])
    chunks = wrap_chunks(text)
    assert all(len(c) <= APRS_MAX_LEN for c in chunks)
    # Reassembling the words recovers the original token sequence.
    assert " ".join(chunks).split() == text.split()


def test_take_batch_no_overflow_returns_all_no_marker():
    chunks = ["alpha", "beta", "gamma"]
    to_send, remaining = take_batch(chunks, max_msgs=4)
    assert to_send == chunks  # list, no marker
    assert remaining == []


def test_take_batch_single_chunk_returns_str():
    to_send, remaining = take_batch(["only"], max_msgs=4)
    assert to_send == "only"
    assert remaining == []


def test_take_batch_overflow_marks_and_preserves_remainder():
    chunks = [f"c{i}" for i in range(10)]
    to_send, remaining = take_batch(chunks, max_msgs=4)
    assert isinstance(to_send, list)
    assert len(to_send) == 4
    assert to_send[-1].endswith("(more)")
    assert len(remaining) == 6


def test_take_batch_is_fully_lossless_across_more_calls():
    # Simulate: wrap a long text, then repeatedly take_batch the remainder
    # exactly as '# more' does, and confirm no words are ever lost.
    text = " ".join([f"token{i:03d}" for i in range(60)])
    original_words = text.split()
    chunks = wrap_chunks(text)

    collected = []
    guard = 0
    while chunks and guard < 100:
        guard += 1
        batch, chunks = take_batch(chunks, max_msgs=4)
        batch_list = [batch] if isinstance(batch, str) else batch
        # Drop the trailing "(more)" marker from the last line before comparing.
        batch_list = [c[: -len(" (more)")] if c.endswith("(more)") else c for c in batch_list]
        collected.extend(batch_list)
    assert " ".join(collected).split() == original_words


def test_empty_wrap_then_batch_is_ok():
    to_send, remaining = take_batch(wrap_chunks(""), max_msgs=4)
    assert to_send == "Ok."
    assert remaining == []
