from __future__ import annotations

import numpy as np

from app.services import embeddings


async def test_embed_texts_returns_one_vector_per_input():
    vectors = await embeddings.embed_texts(["hello", "world"])
    assert len(vectors) == 2
    assert len(vectors[0]) == len(vectors[1]) == 384  # all-MiniLM-L6-v2's known dimension


async def test_embed_texts_of_an_empty_list_returns_an_empty_list():
    assert await embeddings.embed_texts([]) == []


async def test_embeddings_are_l2_normalized():
    """normalize_embeddings=True is the invariant retrieval depends on to use
    a plain dot product as cosine similarity — verify it directly rather
    than trusting the library default silently stays true."""
    (vector,) = await embeddings.embed_texts(["some arbitrary sentence"])
    assert abs(float(np.linalg.norm(vector)) - 1.0) < 1e-4


async def test_embed_query_matches_embed_texts_of_the_same_single_item():
    query_vector = await embeddings.embed_query("hello")
    (batch_vector,) = await embeddings.embed_texts(["hello"])
    assert query_vector == batch_vector


async def test_identical_text_produces_identical_vectors():
    a = await embeddings.embed_query("What are your business hours?")
    b = await embeddings.embed_query("What are your business hours?")
    assert a == b


async def test_semantically_related_text_scores_higher_than_unrelated_text():
    """The one real-model integration test in this suite: proves the actual
    production path (config -> model load -> encode -> normalize) produces
    usable embeddings. Everywhere else (test_documents.py, test_chat.py)
    fakes this module for speed and deterministic control — this test is
    what justifies trusting those fakes reflect real behavior.
    """
    query = np.array(await embeddings.embed_query("What are your business hours?"))
    related = np.array(
        await embeddings.embed_query("We are open Monday to Friday, 9am to 5pm.")
    )
    unrelated = np.array(await embeddings.embed_query("The recipe calls for two cups of flour."))

    related_score = float(query @ related)
    unrelated_score = float(query @ unrelated)
    assert related_score > unrelated_score
