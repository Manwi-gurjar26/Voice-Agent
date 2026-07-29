"""Local embedding model access.

A single lazily-loaded model behind two functions, mirroring the pattern in
app/services/llm.py: tests monkeypatch `embed_texts`/`embed_query` directly
rather than loading the real ~90MB model on every test run.

`SentenceTransformer.encode(...)` is CPU-bound and can take a noticeable
amount of time (especially the first call, which loads the model into
memory) — running it directly in an async function would block the whole
event loop, freezing every other in-flight request on this process. Both
functions offload the actual encode() call via `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio

from app.core.config import settings

_model = None


def get_embedding_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(settings.embedding_model_name)
    return _model


def _reset_model_for_tests() -> None:
    global _model
    _model = None


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-embed. Prefer this over calling embed_query in a loop — the
    underlying model batches internally and is meaningfully faster than one
    call per text for anything beyond a couple of items."""
    if not texts:
        return []

    def _encode() -> list[list[float]]:
        model = get_embedding_model()
        # normalize_embeddings=True: L2-normalizes each vector so cosine
        # similarity reduces to a plain dot product at retrieval time.
        return model.encode(texts, normalize_embeddings=True).tolist()

    return await asyncio.to_thread(_encode)


async def embed_query(text: str) -> list[float]:
    (embedding,) = await embed_texts([text])
    return embedding
