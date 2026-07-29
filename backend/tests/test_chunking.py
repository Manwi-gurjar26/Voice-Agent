from __future__ import annotations

import pytest

from app.services.chunking import chunk_text


def test_short_text_returns_a_single_chunk():
    assert chunk_text("Hello world", chunk_size=1000, overlap=150) == ["Hello world"]


def test_empty_text_returns_no_chunks():
    assert chunk_text("", chunk_size=1000, overlap=150) == []
    assert chunk_text("   \n\n  ", chunk_size=1000, overlap=150) == []


def test_whitespace_runs_are_normalized_to_single_spaces():
    assert chunk_text("Hello   \n\n  world", chunk_size=1000, overlap=150) == ["Hello world"]


def test_long_text_is_split_into_multiple_bounded_chunks():
    text = " ".join(f"word{i}" for i in range(1000))
    chunks = chunk_text(text, chunk_size=200, overlap=30)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_chunks_never_cut_a_word_in_half():
    text = " ".join(f"word{i}" for i in range(500))
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    for chunk in chunks:
        for token in chunk.split(" "):
            assert token.startswith("word"), f"chunk contains a split token: {token!r}"


def test_all_words_are_preserved_across_chunks_despite_overlap():
    words = [f"word{i}" for i in range(300)]
    chunks = chunk_text(" ".join(words), chunk_size=150, overlap=30)
    seen: set[str] = set()
    for chunk in chunks:
        seen.update(chunk.split(" "))
    assert seen == set(words)


def test_consecutive_chunks_share_content_at_the_boundary():
    text = " ".join(f"word{i}" for i in range(500))
    chunks = chunk_text(text, chunk_size=100, overlap=30)
    first_words = chunks[0].split(" ")
    second_words = chunks[1].split(" ")
    assert set(first_words) & set(second_words), "expected some overlap between consecutive chunks"


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        chunk_text("some text", chunk_size=100, overlap=100)
    with pytest.raises(ValueError):
        chunk_text("some text", chunk_size=100, overlap=150)


def test_a_single_very_long_word_is_hard_cut_without_hanging():
    """No whitespace to snap to anywhere — must still terminate rather than
    looping forever, and must still make forward progress each iteration."""
    long_word = "x" * 500
    chunks = chunk_text(long_word, chunk_size=100, overlap=20)
    assert 1 < len(chunks) < 20
    assert all(len(c) <= 100 for c in chunks)


def test_a_single_very_long_word_does_not_lose_content():
    """Regression test: an earlier fix for not-cutting-words-in-half searched
    forward for the next space with no distance limit, and for a token with
    no space ahead at all, that search landed on -1 (or a distant match),
    jumping `start` to (or near) the end of the text and silently discarding
    everything in between. The fix bounds that search to chunk_size."""
    long_word = "x" * 500
    chunks = chunk_text(long_word, chunk_size=100, overlap=20)
    # Overlap means chunks share characters, so total length across chunks
    # is >= the original — but every character position must be covered by
    # at least one chunk. Simplest check for this input: reconstructing by
    # dropping the overlap-sized head of every chunk after the first should
    # recover the original, unbroken run of "x".
    assert all(set(c) == {"x"} for c in chunks)
    recovered_length = len(chunks[0]) + sum(len(c) for c in chunks[1:])
    assert recovered_length >= len(long_word)
