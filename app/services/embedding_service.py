"""
Embedding Service
------------------

Turns chunk text into numerical vectors using a local Sentence Transformer
model.

    Chunks -> Embedding Model -> Vectors

This module knows nothing about files, FastAPI, or chunking rules. It only
takes text and returns vectors. Responsibilities so far:

    document_processor.py:  File   -> Extract -> Clean -> Text
    chunker.py:              Text   -> Chunks
    embedding_service.py:    Chunks -> Vectors
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

# A small, well-known model that runs comfortably on a laptop CPU.
# It is NOT sent to any external API — it downloads once, then runs locally.
MODEL_NAME = "all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """
    Loads the Sentence Transformer model and reuses it for every call.

    Loading a model means reading millions of trained weight values from
    disk and setting up the neural network in memory — a relatively slow,
    one-time cost (roughly a second or two). If we reloaded the model for
    every single chunk, embedding a 20-chunk document would mean paying
    that cost 20 times instead of once. @lru_cache(maxsize=1) makes this
    function do the loading work only the first time it's called; every
    call after that just returns the same already-loaded model object.
    """
    return SentenceTransformer(MODEL_NAME)


def get_embedding_dimension() -> int:
    # The embedding model itself determines the vector size — we ask it
    # rather than hardcoding a number that might be wrong or go stale if
    # the model is ever swapped out.
    model = get_model()
    return model.get_sentence_embedding_dimension()


def embed_text(text: str) -> list[float]:
    """
    Embeds a single piece of text and returns a plain Python list of
    floats (JSON-serializable).

    normalize_embeddings=True rescales each vector to length 1 (a "unit
    vector"). This matters for later similarity comparisons: with
    normalized vectors, cosine similarity reduces to a simple dot product,
    and no chunk's vector is artificially "louder" just because its text
    happened to be longer.
    """
    model = get_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def embed_chunks(chunks: list[dict]) -> list[dict]:
    """
    Takes the chunk dicts produced by chunker.py (each with a "text" key)
    and returns new dicts with an added "embedding" key — one vector per
    chunk, preserving a strict 1 chunk = 1 vector relationship.
    """
    model = get_model()
    texts = [chunk["text"] for chunk in chunks]

    # Encoding every chunk together in one batch lets the model process
    # them as a group, which is faster than calling embed_text() in a loop.
    vectors = model.encode(texts, normalize_embeddings=True)

    embedded_chunks = []
    for chunk, vector in zip(chunks, vectors):
        embedded_chunks.append({**chunk, "embedding": vector.tolist()})

    return embedded_chunks


def cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    """
    Cosine similarity measures how similar the *direction* of two vectors
    is (ranges from -1 to 1; higher means more semantically alike). Because
    our vectors are already unit-length (normalized), this is just their
    dot product — the normalization is what makes that shortcut valid.
    """
    a = np.array(vector_a)
    b = np.array(vector_b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def run_similarity_experiment() -> dict:
    """
    A small, self-contained demonstration that semantically related
    sentences end up with higher cosine similarity than an unrelated one —
    this is the entire reason embeddings are useful for retrieval later.
    No FAISS, no search — just three vectors and two similarity numbers.
    """
    sentence_a = "I studied Artificial Intelligence."
    sentence_b = "I completed a degree in AI."
    sentence_c = "I enjoy cooking food."

    vector_a = embed_text(sentence_a)
    vector_b = embed_text(sentence_b)
    vector_c = embed_text(sentence_c)

    similarity_a_b = cosine_similarity(vector_a, vector_b)
    similarity_a_c = cosine_similarity(vector_a, vector_c)

    return {
        "sentence_a": sentence_a,
        "sentence_b": sentence_b,
        "sentence_c": sentence_c,
        "similarity_a_b": round(similarity_a_b, 4),
        "similarity_a_c": round(similarity_a_c, 4),
        "related_pair_more_similar": similarity_a_b > similarity_a_c,
    }