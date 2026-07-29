"""Finds the most relevant chunks for a query via Python-computed cosine
similarity over an agent's embedded chunks.

No pgvector on this deployment (see README) — an agent's chunks are loaded
into memory and ranked with numpy. This is the one function to replace with
a native `<=>` ANN query if pgvector is installed later; nothing else in the
RAG pipeline needs to change. Fine at MVP scale: even a few thousand 384-dim
float32 vectors is a few MB and a single vectorized dot product away from a
ranked result — there's no per-agent knowledge base size expected to
challenge that in the near term.
"""

from __future__ import annotations

import uuid

import numpy as np
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import Chunk


async def agent_has_chunks(db: AsyncSession, agent_id: uuid.UUID) -> bool:
    """Cheap existence check so a query for an agent with no knowledge base
    yet skips the embedding call entirely — no point encoding a query
    against nothing to compare it with."""
    return bool(await db.scalar(select(exists().where(Chunk.agent_id == agent_id))))


async def find_relevant_chunks(
    db: AsyncSession,
    agent_id: uuid.UUID,
    query_embedding: list[float],
    *,
    top_k: int,
    min_similarity: float,
) -> list[Chunk]:
    rows = list(
        await db.scalars(
            select(Chunk)
            .where(Chunk.agent_id == agent_id)
            .options(joinedload(Chunk.document))
        )
    )
    if not rows:
        return []

    matrix = np.asarray([r.embedding for r in rows], dtype=np.float32)
    query = np.asarray(query_embedding, dtype=np.float32)
    # Both sides are L2-normalized at embedding time (app/services/
    # embeddings.py), so a plain dot product equals cosine similarity.
    scores = matrix @ query

    order = np.argsort(-scores)[:top_k]
    return [rows[i] for i in order if scores[i] >= min_similarity]
