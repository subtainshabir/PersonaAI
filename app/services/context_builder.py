"""
Context Builder
---------------

Turns FAISS search results into the context that will eventually be handed
to an LLM (Phase 8). This module only assembles context — it does not
embed text or search vectors.

    Relevant Chunks -> Context

Responsibilities so far:

    document_processor.py:  File    -> Extract -> Clean -> Text
    chunker.py:              Text    -> Chunks
    embedding_service.py:    Chunks  -> Vectors
    vector_store.py:         Vectors -> Search results
    context_builder.py:      Search results -> Context
"""

from __future__ import annotations

# Maximum total size of the assembled context string. Chunks are added
# highest-ranked first; once adding the next chunk would exceed this
# budget, it's left out entirely — a chunk is never cut mid-sentence just
# to fit, since a half-chunk could be misleading or ungrammatical context.
MAX_CONTEXT_CHARACTERS = 2000

# Minimum cosine similarity a chunk must have to count as relevant. Chunks
# scoring below this are noise relative to the question, not an answer to
# it, and are excluded from context entirely.
SIMILARITY_THRESHOLD = 0.3


def build_context(
    results: list[dict],
    max_context_characters: int = MAX_CONTEXT_CHARACTERS,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> dict:
    """
    results: chunk dicts from vector_store.search(), already sorted by
    score (highest first), each with chunk_id, source, score, text.

    Returns:
        {
            "retrieved_chunks": [...],       # chunks actually used as context
            "context": "...",                # assembled string ("" if none qualified)
            "found_relevant_context": bool,
        }
    """
    relevant = [r for r in results if r["score"] >= similarity_threshold]

    if not relevant:
        return {
            "retrieved_chunks": [],
            "context": "",
            "found_relevant_context": False,
        }

    included_chunks = []
    context_parts = []
    total_characters = 0

    for chunk in relevant:
        text = chunk["text"]
        separator_size = 2 if context_parts else 0  # "\n\n" between chunks
        addition_size = len(text) + separator_size

        # Stop once the budget would be exceeded — but only after we
        # already have at least one chunk. The single highest-ranked chunk
        # is always included whole, even if it alone exceeds the budget,
        # since returning zero context when a relevant chunk exists would
        # be worse than a single slightly-oversized one.
        if context_parts and total_characters + addition_size > max_context_characters:
            break

        context_parts.append(text)
        total_characters += addition_size
        included_chunks.append(chunk)

    return {
        "retrieved_chunks": included_chunks,
        "context": "\n\n".join(context_parts),
        "found_relevant_context": True,
    }