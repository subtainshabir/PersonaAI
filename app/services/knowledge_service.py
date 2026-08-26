from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.services.chunker import EmptyTextError, chunk_text
from app.services.document_processor import (
    SUPPORTED_EXTENSIONS,
    UnsupportedFileTypeError,
    get_file_extension,
    process_document,
)
from app.services.embedding_service import MODEL_NAME, embed_chunks, get_embedding_dimension
from app.services.vector_store import (
    METADATA_PATH,
    DimensionMismatchError,
    EmptyIndexError,
    create_store,
    get_store,
)

MAX_UPLOAD_MB = int(os.environ.get("KB_MAX_UPLOAD_MB", "10"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024


class KnowledgeUploadError(Exception):
    """Raised for any upload failure with a message safe to show the admin."""


def _last_updated() -> str | None:
    try:
        timestamp = os.path.getmtime(METADATA_PATH)
    except OSError:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _sanitize_filename(filename: str) -> str:
    # Strip any directory components so a crafted name like "../../x.txt"
    # can never be treated as a path — only the base name is kept.
    name = Path(filename or "").name.strip()
    if not name:
        name = "document"
    name = re.sub(r"[^A-Za-z0-9 ._-]", "_", name)
    return name[:150]


def get_knowledge_overview() -> dict:
    """Read-only summary of the current knowledge base for the admin panel."""
    overview = {
        "status": "empty",
        "total_chunks": 0,
        "documents": [],
        "embedding_model": MODEL_NAME,
        "last_updated": _last_updated(),
        "max_upload_mb": MAX_UPLOAD_MB,
    }

    try:
        store = get_store()
    except EmptyIndexError:
        return overview

    if store.total_vectors == 0:
        return overview

    counts: dict[str, int] = {}
    for meta in store.metadata.values():
        source = meta.get("source") or "Unknown source"
        counts[source] = counts.get(source, 0) + 1

    overview["status"] = "loaded"
    overview["total_chunks"] = store.total_vectors
    overview["documents"] = [
        {"name": name, "chunk_count": count} for name, count in sorted(counts.items())
    ]
    return overview


def add_document_to_knowledge_base(filename: str, file_bytes: bytes) -> dict:
    """
    Runs the existing extract -> clean -> chunk -> embed pipeline for one
    uploaded file, then appends the result to the existing FAISS store
    (creating it only if none exists yet) instead of replacing it.
    """
    safe_name = _sanitize_filename(filename)
    extension = get_file_extension(safe_name)

    if extension not in SUPPORTED_EXTENSIONS:
        raise KnowledgeUploadError(
            f"Unsupported file type: '.{extension or 'unknown'}'. "
            f"Supported types are: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )

    if not file_bytes:
        raise KnowledgeUploadError("The uploaded file is empty.")

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise KnowledgeUploadError(f"File exceeds the {MAX_UPLOAD_MB} MB upload limit.")

    try:
        processed = process_document(safe_name, file_bytes)
    except UnsupportedFileTypeError as error:
        raise KnowledgeUploadError(str(error)) from error
    except Exception as error:
        raise KnowledgeUploadError(
            f"Could not read '{safe_name}'. The file may be corrupted or invalid."
        ) from error

    try:
        chunks = chunk_text(processed["text"])
    except EmptyTextError as error:
        raise KnowledgeUploadError(str(error)) from error

    embedded_chunks = embed_chunks(chunks)
    dimension = get_embedding_dimension()

    try:
        store = get_store()
    except EmptyIndexError:
        store = create_store(dimension)

    document_id = uuid.uuid4().hex
    uploaded_at = datetime.now(timezone.utc).isoformat()

    vectors = [chunk["embedding"] for chunk in embedded_chunks]
    metadatas = [
        {
            "chunk_id": chunk["chunk_id"],
            "source": safe_name,
            "text": chunk["text"],
            "document_id": document_id,
            "file_type": extension,
            "uploaded_at": uploaded_at,
        }
        for chunk in embedded_chunks
    ]

    try:
        store.add(vectors, metadatas)
        store.save()
    except (ValueError, DimensionMismatchError) as error:
        raise KnowledgeUploadError(str(error)) from error
    except OSError as error:
        raise KnowledgeUploadError("Failed to save the knowledge base.") from error

    return {
        "filename": safe_name,
        "document_id": document_id,
        "total_chunks": len(embedded_chunks),
        "status": "indexed",
    }