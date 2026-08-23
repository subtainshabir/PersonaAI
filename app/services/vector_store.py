"""
Vector Store
------------

Wraps a FAISS index plus the chunk metadata needed to turn a search
result (a vector position) back into readable text.

    Embeddings -> FAISS Index -> Stored Vectors
    FAISS position -> metadata mapping -> Chunk text

This module only stores and searches vectors it's handed — it knows
nothing about files, chunking, or how vectors are produced:

    document_processor.py:  File   -> Extract -> Clean -> Text
    chunker.py:              Text   -> Chunks
    embedding_service.py:    Chunks -> Vectors
    vector_store.py:         Vectors -> Searchable index
"""

from __future__ import annotations

import faiss
import numpy as np


class DimensionMismatchError(Exception):
    """Raised when a vector's dimension doesn't match the index's dimension."""


class EmptyIndexError(Exception):
    """Raised when searching before any vectors have been added."""


class VectorStore:
    def __init__(self, dimension: int):
        if not isinstance(dimension, int) or dimension <= 0:
            raise ValueError(f"dimension must be a positive integer, got {dimension!r}.")

        self.dimension = dimension

        # IndexFlatIP does an exact search using inner product. Our
        # embeddings are normalized to unit length (see embedding_service),
        # and for unit-length vectors, inner product IS cosine similarity —
        # so this index gives us cosine-similarity search without any
        # extra math on our end.
        self.index = faiss.IndexFlatIP(dimension)

        # FAISS only knows vector positions (0, 1, 2, ...), not what they
        # mean. This dict is the separate lookup that maps a position back
        # to the chunk it came from — kept outside FAISS on purpose, so the
        # two responsibilities (search vs. meaning) stay distinct.
        self.metadata: dict[int, dict] = {}

    def add(self, vectors: list[list[float]], metadatas: list[dict]) -> None:
        if len(vectors) == 0:
            raise ValueError("Cannot add an empty list of vectors.")
        if len(vectors) != len(metadatas):
            raise ValueError(
                f"vectors ({len(vectors)}) and metadatas ({len(metadatas)}) "
                "must be the same length."
            )

        matrix = np.array(vectors, dtype="float32")
        if matrix.ndim != 2 or matrix.shape[1] != self.dimension:
            actual = matrix.shape[1] if matrix.ndim == 2 else "unknown"
            raise DimensionMismatchError(
                f"Expected vectors of dimension {self.dimension}, got {actual}."
            )

        # New vectors are appended after whatever's already in the index,
        # so position numbers stay unique as more documents get indexed.
        start_position = self.index.ntotal
        self.index.add(matrix)

        for offset, meta in enumerate(metadatas):
            self.metadata[start_position + offset] = meta

    def search(self, query_vector: list[float], top_k: int = 3) -> list[dict]:
        if self.index.ntotal == 0:
            raise EmptyIndexError("The index is empty — add vectors before searching.")

        query = np.array([query_vector], dtype="float32")
        if query.ndim != 2 or query.shape[1] != self.dimension:
            actual = query.shape[1] if query.ndim == 2 else "unknown"
            raise DimensionMismatchError(
                f"Expected a query vector of dimension {self.dimension}, got {actual}."
            )

        # Can't ask FAISS for more results than vectors it actually holds.
        k = min(top_k, self.index.ntotal)
        scores, positions = self.index.search(query, k)

        results = []
        for score, position in zip(scores[0], positions[0]):
            if position == -1:
                continue  # FAISS pads with -1 when there are fewer than k matches.
            meta = self.metadata.get(int(position), {})
            results.append({"score": float(score), **meta})

        return results

    @property
    def total_vectors(self) -> int:
        return self.index.ntotal


# ---------- MODULE-LEVEL STORE ----------
# PersonaAI has no database yet, so for this dev/testing phase we keep one
# "current" index in memory for as long as the server process runs.
# Indexing a new document replaces it — this is intentionally simple until
# persistent storage is introduced in a later phase.
_current_store: VectorStore | None = None


def create_store(dimension: int) -> VectorStore:
    global _current_store
    _current_store = VectorStore(dimension)
    return _current_store


def get_store() -> VectorStore:
    if _current_store is None:
        raise EmptyIndexError("No document has been indexed yet. Call /api/documents/index first.")
    return _current_store