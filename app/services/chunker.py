"""
Chunker
-------

Turns clean text into a list of smaller, meaningful chunks.

    Clean Text -> Chunker -> List of Chunks

This module knows nothing about files, FastAPI, or embeddings. It only
takes a string and returns chunks. Keeping it separate from
document_processor.py mirrors the real pipeline:

    document_processor.py:  File -> Extract -> Clean -> Text
    chunker.py:              Text -> Chunks
"""

from __future__ import annotations

# Target size for each chunk, in characters. This is a starting point for
# learning the concept, not a hard limit — see _split_large_paragraph for
# how oversized paragraphs are handled.
CHUNK_SIZE = 500

# How many characters from the end of one chunk get repeated at the start
# of the next chunk. Overlap exists so that a sentence or idea that falls
# right on a chunk boundary isn't only visible in one chunk. Without it,
# a similarity search for "TensorFlow" might miss a chunk where the word
# TensorFlow appeared right at the very end of the previous chunk's text,
# because retrieval treats each chunk as a self-contained unit of context.
CHUNK_OVERLAP = 50


class EmptyTextError(Exception):
    """Raised when there is no text to chunk."""


def _split_into_paragraphs(text: str) -> list[str]:
    # Paragraphs in our cleaned text are separated by a blank line ("\n\n").
    raw_paragraphs = text.split("\n\n")
    # Drop any paragraph that's empty after stripping whitespace.
    return [paragraph.strip() for paragraph in raw_paragraphs if paragraph.strip()]


def _split_large_paragraph(paragraph: str, size: int) -> list[str]:
    """
    A single paragraph can be bigger than CHUNK_SIZE (e.g. a long project
    description). When that happens we split it on sentence boundaries
    first, and only fall back to a hard character split if a single
    "sentence" is still too big to fit.
    """
    if len(paragraph) <= size:
        return [paragraph]

    # Split on ". " so we break between sentences, not mid-sentence.
    sentences = paragraph.split(". ")
    pieces = []
    current = ""

    for i, sentence in enumerate(sentences):
        # Re-add the period we split on, except for the very last piece.
        piece = sentence if i == len(sentences) - 1 else sentence + ". "

        if len(current) + len(piece) <= size:
            current += piece
        else:
            if current:
                pieces.append(current.strip())
            if len(piece) > size:
                # Even one sentence is too long — hard split as a last resort.
                for start in range(0, len(piece), size):
                    pieces.append(piece[start:start + size].strip())
                current = ""
            else:
                current = piece

    if current.strip():
        pieces.append(current.strip())

    return pieces


def _combine_paragraphs(paragraphs: list[str], size: int) -> list[str]:
    """
    Greedily combines paragraphs together until adding the next one would
    exceed the target size, so we avoid both tiny fragments and giant blobs.
    """
    combined_blocks = []
    current_block = ""

    for paragraph in paragraphs:
        # If a single paragraph is already too big, split it first.
        pieces = _split_large_paragraph(paragraph, size)

        for piece in pieces:
            candidate = f"{current_block}\n\n{piece}" if current_block else piece

            if len(candidate) <= size:
                current_block = candidate
            else:
                if current_block:
                    combined_blocks.append(current_block)
                current_block = piece

    if current_block:
        combined_blocks.append(current_block)

    return combined_blocks


def _apply_overlap(blocks: list[str], overlap: int) -> list[str]:
    """
    Prepends the tail end of each block to the start of the next block,
    so context isn't lost right at the seam between two chunks.
    """
    if overlap <= 0 or len(blocks) <= 1:
        return blocks

    overlapped = [blocks[0]]

    for i in range(1, len(blocks)):
        previous_tail = blocks[i - 1][-overlap:]
        overlapped.append(f"{previous_tail} {blocks[i]}")

    return overlapped


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    """
    Runs the full chunking pipeline and returns a list of chunk dicts:

        {"chunk_id": 0, "text": "...", "characters": 245}
    """
    if not text or not text.strip():
        raise EmptyTextError("Cannot chunk empty text.")

    paragraphs = _split_into_paragraphs(text)
    blocks = _combine_paragraphs(paragraphs, chunk_size)
    blocks = _apply_overlap(blocks, chunk_overlap)

    chunks = []
    for chunk_id, block in enumerate(blocks):
        chunks.append({
            "chunk_id": chunk_id,
            "text": block,
            "characters": len(block),
        })

    return chunks