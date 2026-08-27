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
    IndexRemovalError,
    create_store,
    get_store,
)

MAX_UPLOAD_MB = int(os.environ.get("KB_MAX_UPLOAD_MB", "10"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

_UUID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")
_LEGACY_ID_RE = re.compile(r"^legacy:[A-Za-z0-9 ._-]{1,150}$")


class KnowledgeUploadError(Exception):
    """Raised for any upload failure with a message safe to show the admin."""


class DocumentNotFoundError(Exception):
    """Raised when a document identifier doesn't match anything in the store."""


class KnowledgeDeleteError(Exception):
    """Raised when a valid, existing document could not be deleted."""


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


def _document_key(meta: dict) -> str:
    # Phase 18+ uploads carry a document_id. Chunks indexed before that
    # (e.g. the original bootstrap document) don't, so they're grouped by
    # source filename instead under a clearly-marked "legacy:" key.
    document_id = meta.get("document_id")
    if document_id:
        return document_id
    return f"legacy:{meta.get('source', 'unknown')}"


def _is_valid_document_id(document_id: str) -> bool:
    if not isinstance(document_id, str):
        return False
    return bool(_UUID_HEX_RE.match(document_id) or _LEGACY_ID_RE.match(document_id))


def list_documents() -> list[dict]:
    """One row per uploaded document, aggregated from existing chunk metadata."""
    try:
        store = get_store()
    except EmptyIndexError:
        return []

    groups: dict[str, dict] = {}
    for meta in store.metadata.values():
        key = _document_key(meta)
        group = groups.get(key)
        if group is None:
            source = meta.get("source") or "Unknown source"
            file_type = meta.get("file_type") or (get_file_extension(source) or None)
            group = {
                "document_id": key,
                "filename": source,
                "file_type": file_type,
                "uploaded_at": meta.get("uploaded_at"),
                "chunk_count": 0,
                "characters": 0,
            }
            groups[key] = group
        group["chunk_count"] += 1
        group["characters"] += len(meta.get("text", ""))

    documents = list(groups.values())
    documents.sort(key=lambda d: d["uploaded_at"] or "", reverse=True)
    return documents


def get_document_detail(document_id: str) -> dict:
    if not _is_valid_document_id(document_id):
        raise DocumentNotFoundError("Invalid document identifier.")

    try:
        store = get_store()
    except EmptyIndexError:
        raise DocumentNotFoundError("No knowledge base is currently loaded.")

    filename = None
    file_type = None
    uploaded_at = None
    chunks = []

    for position in sorted(store.metadata):
        meta = store.metadata[position]
        if _document_key(meta) != document_id:
            continue
        filename = meta.get("source") or filename
        file_type = meta.get("file_type") or file_type
        uploaded_at = meta.get("uploaded_at") or uploaded_at
        text = meta.get("text", "")
        chunks.append({"chunk_id": meta.get("chunk_id"), "characters": len(text), "text": text})

    if not chunks:
        raise DocumentNotFoundError("Document not found.")

    if not file_type and filename:
        file_type = get_file_extension(filename) or None

    return {
        "document_id": document_id,
        "filename": filename,
        "file_type": file_type,
        "uploaded_at": uploaded_at,
        "chunk_count": len(chunks),
        "characters": sum(chunk["characters"] for chunk in chunks),
        "chunks": chunks,
    }


def delete_document(document_id: str) -> dict:
    if not _is_valid_document_id(document_id):
        raise DocumentNotFoundError("Invalid document identifier.")

    try:
        store = get_store()
    except EmptyIndexError:
        raise DocumentNotFoundError("No knowledge base is currently loaded.")

    filename = next(
        (meta.get("source") for meta in store.metadata.values() if _document_key(meta) == document_id),
        None,
    )
    if filename is None:
        raise DocumentNotFoundError("Document not found.")

    try:
        removed = store.remove_where(lambda meta: _document_key(meta) == document_id)
    except IndexRemovalError as error:
        raise KnowledgeDeleteError(str(error)) from error

    if removed == 0:
        raise DocumentNotFoundError("Document not found.")

    try:
        store.save()
    except OSError as error:
        raise KnowledgeDeleteError("Removed from memory but failed to save changes to disk.") from error

    return {"document_id": document_id, "filename": filename, "removed_chunks": removed}


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

    overview["status"] = "loaded"
    overview["total_chunks"] = store.total_vectors
    overview["documents"] = list_documents()
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