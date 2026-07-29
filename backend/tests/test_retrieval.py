from __future__ import annotations

import math
import uuid

from app.models import Chunk, Document
from app.services.retrieval import agent_has_chunks, find_relevant_chunks
from tests.test_auth import register
from tests.test_public import make_active_agent


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec]


QUERY = _unit([1, 0, 0])
CLOSE = _unit([1, 0.1, 0])  # cosine similarity ~0.995
MODERATE = _unit([1, 1, 0])  # cosine similarity ~0.707
FAR = _unit([0, 1, 0])  # cosine similarity = 0.0


async def _make_agent_with_chunks(client, tokens, db_session, vectors: list[list[float]]):
    agent = await make_active_agent(client, tokens)

    # tenant_id isn't in AgentRead's response body — fetch the row directly.
    from sqlalchemy import select

    from app.models import Agent as AgentModel

    agent_row = await db_session.scalar(
        select(AgentModel).where(AgentModel.id == uuid.UUID(agent["id"]))
    )
    document = Document(
        tenant_id=agent_row.tenant_id,
        agent_id=agent_row.id,
        source_type="text",
        title="Test doc",
        status="ready",
    )
    db_session.add(document)
    await db_session.flush()

    for i, vector in enumerate(vectors):
        db_session.add(
            Chunk(
                document_id=document.id,
                tenant_id=agent_row.tenant_id,
                agent_id=agent_row.id,
                chunk_index=i,
                content=f"chunk content {i}",
                embedding=vector,
            )
        )
    await db_session.commit()
    return agent_row.id


async def test_agent_has_chunks_is_false_before_any_are_created(client, db_session):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)
    assert not await agent_has_chunks(db_session, uuid.UUID(agent["id"]))


async def test_agent_has_chunks_is_true_after_creation(client, db_session):
    tokens = await register(client)
    agent_id = await _make_agent_with_chunks(client, tokens, db_session, [CLOSE])
    assert await agent_has_chunks(db_session, agent_id)


async def test_results_are_ranked_by_similarity_descending(client, db_session):
    tokens = await register(client)
    agent_id = await _make_agent_with_chunks(client, tokens, db_session, [FAR, CLOSE, MODERATE])

    results = await find_relevant_chunks(
        db_session, agent_id, QUERY, top_k=10, min_similarity=-1.0
    )
    assert [r.content for r in results] == [
        "chunk content 1",  # CLOSE
        "chunk content 2",  # MODERATE
        "chunk content 0",  # FAR
    ]


async def test_top_k_limits_the_number_of_results(client, db_session):
    tokens = await register(client)
    agent_id = await _make_agent_with_chunks(client, tokens, db_session, [CLOSE, MODERATE, FAR])

    results = await find_relevant_chunks(db_session, agent_id, QUERY, top_k=2, min_similarity=-1.0)
    assert len(results) == 2


async def test_min_similarity_excludes_weak_matches(client, db_session):
    tokens = await register(client)
    agent_id = await _make_agent_with_chunks(client, tokens, db_session, [CLOSE, FAR])

    results = await find_relevant_chunks(db_session, agent_id, QUERY, top_k=10, min_similarity=0.5)
    assert [r.content for r in results] == ["chunk content 0"]  # only CLOSE clears the bar


async def test_no_chunks_for_agent_returns_empty_list(client, db_session):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)
    results = await find_relevant_chunks(
        db_session, uuid.UUID(agent["id"]), QUERY, top_k=5, min_similarity=-1.0
    )
    assert results == []


async def test_retrieval_is_isolated_per_agent(client, db_session):
    tokens = await register(client)
    agent_a_id = await _make_agent_with_chunks(client, tokens, db_session, [CLOSE])
    agent_b = await make_active_agent(client, tokens, name="Second Bot")

    results = await find_relevant_chunks(
        db_session, uuid.UUID(agent_b["id"]), QUERY, top_k=10, min_similarity=-1.0
    )
    assert results == []  # agent B has no chunks of its own, despite agent A having one


async def test_returned_chunks_have_their_document_eager_loaded(client, db_session):
    """find_relevant_chunks joinedloads Chunk.document so callers (citation
    building, system-prompt augmentation) can read chunk.document.title
    without tripping the lazy="raise" policy on Chunk.document."""
    tokens = await register(client)
    agent_id = await _make_agent_with_chunks(client, tokens, db_session, [CLOSE])

    (result,) = await find_relevant_chunks(
        db_session, agent_id, QUERY, top_k=10, min_similarity=-1.0
    )
    assert result.document.title == "Test doc"  # would raise if not eager-loaded
