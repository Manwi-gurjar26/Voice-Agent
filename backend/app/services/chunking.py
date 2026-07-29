"""Splits extracted document text into overlapping chunks for embedding.

No tokenizer involved — this is a character-based sliding window, not a
Claude-token-accurate split. Chunk boundaries only need to be "reasonable
sized pieces of text", not billing-precise; a rough heuristic that avoids
cutting words in half is enough for retrieval quality.
"""

from __future__ import annotations

import re

_WHITESPACE_RUN = re.compile(r"\s+")


def _normalize(text: str) -> str:
    # Collapse runs of whitespace (including newlines) to single spaces so
    # chunk-size character counts reflect actual content, not formatting.
    return _WHITESPACE_RUN.sub(" ", text).strip()


def chunk_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    """Slide a `chunk_size`-character window over `text`, snapping breaks to
    whitespace so words aren't split, advancing by `chunk_size - overlap`
    each step so consecutive chunks share roughly `overlap` characters of
    context.

    Returns an empty list for blank input — callers should treat that as
    "nothing to embed", not an error. The step is always positive (enforced
    below), so the loop is guaranteed to terminate without needing a special
    infinite-loop guard.
    """
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    normalized = _normalize(text)
    if not normalized:
        return []

    if len(normalized) <= chunk_size:
        return [normalized]

    chunks: list[str] = []
    start = 0
    length = len(normalized)
    step = chunk_size - overlap

    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            # Don't cut mid-word: back up to the last space in range, unless
            # there isn't one after `start` (e.g. one very long "word", like
            # a URL) — in that case, just hard-cut at chunk_size.
            snapped = normalized.rfind(" ", start, end)
            if snapped > start:
                end = snapped
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break

        start += step
        # `end` was snapped back to a word boundary above, but `start` here
        # is just a fixed offset — it can land mid-word (e.g. inside
        # "word24", producing "rd24" as the next chunk's first token). Snap
        # forward to the next space so a chunk never *begins* mid-word
        # either — but only within `chunk_size` characters. Searching
        # unboundedly is wrong: for one very long token with no spaces at
        # all (e.g. a URL), `find(" ", start)` would return -1 or a match
        # far away, jumping `start` to (or near) `length` and silently
        # discarding everything in between. Bounding the search means a
        # pathological long token just gets hard-cut, same as `end` above,
        # rather than losing content.
        if start < length and normalized[start - 1] != " ":
            next_space = normalized.find(" ", start, min(start + chunk_size, length))
            if next_space != -1:
                start = next_space + 1

    return chunks
