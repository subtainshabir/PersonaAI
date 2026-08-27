from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "vector_store"
INDEX_PATH = DATA_DIR / "index.faiss"
METADATA_PATH = DATA_DIR / "metadata.json"


class DimensionMismatchError(Exception):
    pass


class EmptyIndexError(Exception):
    pass


class CorruptedStoreError(Exception):
    pass


class IndexRemovalError(Exception):
    pass


class VectorStore:
    def __init__(self, dimension: int):
        if not isinstance(dimension, int) or dimension <= 0:
            raise ValueError(f"dimension must be a positive integer, got {dimension!r}.")

        self.dimension = dimension
        self.index = faiss.IndexFlatIP(dimension)
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

        k = min(top_k, self.index.ntotal)
        scores, positions = self.index.search(query, k)

        results = []
        for score, position in zip(scores[0], positions[0]):
            if position == -1:
                continue
            meta = self.metadata.get(int(position), {})
            results.append({"score": float(score), **meta})

        return results

    @property
    def total_vectors(self) -> int:
        return self.index.ntotal

    def remove_where(self, predicate) -> int:
        """
        Removes every vector whose metadata matches predicate(meta), using
        FAISS's native remove_ids (exact removal on a flat index — no
        re-embedding or re-chunking involved). Remaining vectors keep their
        relative order; metadata positions are rebuilt to match the
        compacted index so the two never drift out of sync.
        """
        positions_to_remove = sorted(
            position for position, meta in self.metadata.items() if predicate(meta)
        )
        if not positions_to_remove:
            return 0

        try:
            id_selector = faiss.IDSelectorBatch(np.array(positions_to_remove, dtype="int64"))
            self.index.remove_ids(id_selector)
        except RuntimeError as error:
            raise IndexRemovalError(f"Could not remove vectors from the index: {error}") from error

        removed = set(positions_to_remove)
        remaining_positions = sorted(p for p in self.metadata if p not in removed)
        self.metadata = {
            new_position: self.metadata[old_position]
            for new_position, old_position in enumerate(remaining_positions)
        }
        return len(positions_to_remove)

    def save(self, index_path: Path = INDEX_PATH, metadata_path: Path = METADATA_PATH) -> None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(index_path))
        payload = {
            "dimension": self.dimension,
            "metadata": {str(position): meta for position, meta in self.metadata.items()},
        }
        metadata_path.write_text(json.dumps(payload))

    @classmethod
    def load(cls, index_path: Path = INDEX_PATH, metadata_path: Path = METADATA_PATH) -> "VectorStore":
        if not index_path.exists() or not metadata_path.exists():
            raise EmptyIndexError("No saved knowledge base found on disk.")

        try:
            index = faiss.read_index(str(index_path))
            payload = json.loads(metadata_path.read_text())
            metadata_raw = payload["metadata"]
            dimension = payload["dimension"]
        except Exception as error:
            raise CorruptedStoreError(f"Saved knowledge base is unreadable: {error}") from error

        if index.d != dimension:
            raise CorruptedStoreError(
                f"Saved index dimension ({index.d}) does not match stored metadata dimension ({dimension})."
            )
        if index.ntotal != len(metadata_raw):
            raise CorruptedStoreError(
                f"Saved index has {index.ntotal} vectors but metadata has {len(metadata_raw)} entries."
            )

        store = cls(dimension)
        store.index = index
        store.metadata = {int(position): meta for position, meta in metadata_raw.items()}
        return store


_current_store: VectorStore | None = None


def create_store(dimension: int) -> VectorStore:
    global _current_store
    _current_store = VectorStore(dimension)
    return _current_store


def get_store() -> VectorStore:
    if _current_store is None:
        raise EmptyIndexError("No document has been indexed yet. Call /api/documents/index first.")
    return _current_store


def load_store_from_disk() -> None:
    global _current_store
    try:
        _current_store = VectorStore.load()
    except EmptyIndexError:
        pass