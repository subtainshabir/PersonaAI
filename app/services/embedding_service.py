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

import logging
import os
import threading

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# A small, well-known model that runs comfortably on a laptop CPU.
# It is NOT sent to any external API — it downloads once, then runs locally.
# Configurable via the .env / environment so it can be swapped without
# touching code; falls back to the same default as before.
MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")


class EmbeddingModelLoadError(Exception):
    """Raised when the embedding model could not be loaded."""


_model: SentenceTransformer | None = None
_model_lock = threading.Lock()


def get_model() -> SentenceTransformer:
    """
    Loads the Sentence Transformer model once and reuses the same instance
    for every call after that — across every request, every service
    (document ingestion, FAISS re-indexing, chatbot query embedding), and
    every thread.

    Loading a model means reading millions of trained weight values from
    disk and setting up the neural network in memory — a relatively slow,
    one-time cost (roughly a second or two). Doing that once and reusing
    the result is the entire point of this function.

    The lock only matters for the very first load: FastAPI runs its sync
    route handlers in a thread pool, so two requests can genuinely arrive
    at the same instant. Without the lock, both could see "not loaded
    yet" and each start constructing their own model before either
    finishes — wasting memory and CPU and leaving two instances where one
    was intended. The lock makes that race impossible; every call after
    the first returns immediately without touching it.
    """
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is None:
            try:
                logger.info("Loading embedding model '%s'...", MODEL_NAME)
                _model = SentenceTransformer(MODEL_NAME)
                logger.info("Embedding model '%s' loaded successfully.", MODEL_NAME)
            except Exception as error:
                logger.error("Failed to load embedding model '%s': %s", MODEL_NAME, error)
                raise EmbeddingModelLoadError(
                    f"Could not load embedding model '{MODEL_NAME}': {error}"
                ) from error

    return _model


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