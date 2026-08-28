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
from app.services.job_service import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PROCESSING,
    create_job,
    update_job,
)
from app.services.vector_store import (
    METADATA_PATH,
    DimensionMismatchError,
    EmptyIndexError,
    IndexRemovalError,
    VectorStore,
    create_store,
    get_store,
    set_active_store,
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


class KnowledgeReplaceError(Exception):
    """Raised when a valid replacement could not be completed safely."""


class KnowledgeReindexError(Exception):
    """Raised when a full index rebuild could not be completed safely."""


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


def validate_upload(filename: str, file_bytes: bytes) -> tuple[str, str]:
    """
    Cheap, fast checks only (name/extension/size) — safe to run
    synchronously in the request before handing off the heavy pipeline
    steps to a background task.
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

    return safe_name, extension


def _prepare_upload(filename: str, file_bytes: bytes) -> tuple[str, str, list[dict]]:
    """
    Runs the existing validate -> extract -> clean -> chunk -> embed
    pipeline for one uploaded file. Shared by both add and replace (and,
    via add_document_to_knowledge_base, by the background upload job) so
    there's a single place that does this work.
    """
    safe_name, extension = validate_upload(filename, file_bytes)

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
    return safe_name, extension, embedded_chunks


def _build_metadatas(embedded_chunks, source, document_id, file_type, uploaded_at) -> list[dict]:
    return [
        {
            "chunk_id": chunk["chunk_id"],
            "source": source,
            "text": chunk["text"],
            "document_id": document_id,
            "file_type": file_type,
            "uploaded_at": uploaded_at,
        }
        for chunk in embedded_chunks
    ]


def add_document_to_knowledge_base(filename: str, file_bytes: bytes) -> dict:
    """
    Runs the existing extract -> clean -> chunk -> embed pipeline for one
    uploaded file, then appends the result to the existing FAISS store
    (creating it only if none exists yet) instead of replacing it.
    """
    safe_name, extension, embedded_chunks = _prepare_upload(filename, file_bytes)
    dimension = get_embedding_dimension()

    try:
        store = get_store()
    except EmptyIndexError:
        store = create_store(dimension)

    document_id = uuid.uuid4().hex
    uploaded_at = datetime.now(timezone.utc).isoformat()
    vectors = [chunk["embedding"] for chunk in embedded_chunks]
    metadatas = _build_metadatas(embedded_chunks, safe_name, document_id, extension, uploaded_at)

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


def start_upload_job(filename: str, file_bytes: bytes) -> dict:
    """
    Validates the upload quickly (cheap checks only) and registers a
    pending job. The caller is expected to schedule run_upload_job to
    execute afterward (e.g. via FastAPI's BackgroundTasks) so the heavy
    extract/chunk/embed/FAISS-update work happens outside the request.
    """
    safe_name, _extension = validate_upload(filename, file_bytes)
    job_id = create_job("upload", safe_name)
    return {"job_id": job_id, "filename": safe_name}


def run_upload_job(job_id: str, filename: str, file_bytes: bytes) -> None:
    """
    Executed in the background, after the upload request has already
    returned a "pending" response. Runs the exact same
    add_document_to_knowledge_base pipeline used by every other upload
    path — no second implementation — just wrapped with job-status
    bookkeeping so the admin UI can poll progress.

    A document is only ever reflected in the FAISS store once this
    succeeds in full: add_document_to_knowledge_base validates, extracts,
    chunks, and embeds BEFORE it ever calls store.add()/store.save(), so
    any failure at any stage here leaves the active index exactly as it
    was — never partially written. The broad except is intentional: this
    runs with no HTTP response to report to, so any unexpected error must
    still resolve the job to "failed" rather than leaving it stuck in
    "processing" forever.
    """
    update_job(job_id, status=STATUS_PROCESSING)
    try:
        result = add_document_to_knowledge_base(filename, file_bytes)
    except KnowledgeUploadError as error:
        update_job(job_id, status=STATUS_FAILED, error=str(error))
        return
    except Exception as error:
        update_job(
            job_id,
            status=STATUS_FAILED,
            error=f"An unexpected error occurred while processing '{filename}'.",
        )
        return

    update_job(job_id, status=STATUS_COMPLETED, result=result)


def replace_document(document_id: str, filename: str, file_bytes: bytes) -> dict:
    """
    Replaces an existing document's chunks with a freshly processed
    version of a new file, keeping the same document_id where possible.

    The new file is fully validated, extracted, chunked, and embedded
    BEFORE anything about the existing document is touched — if any of
    that fails, the old document is left completely intact. Once the new
    vectors are ready, they're added to the store first and the old ones
    (identified by the positions captured before adding) are removed
    second, so a failure removing the old data can never leave the
    document missing outright.
    """
    if not _is_valid_document_id(document_id):
        raise DocumentNotFoundError("Invalid document identifier.")

    try:
        store = get_store()
    except EmptyIndexError:
        raise DocumentNotFoundError("No knowledge base is currently loaded.")

    old_positions = {
        position for position, meta in store.metadata.items() if _document_key(meta) == document_id
    }
    if not old_positions:
        raise DocumentNotFoundError("Document not found.")

    old_filename = store.metadata[next(iter(old_positions))].get("source")

    # Validate and process the replacement fully before removing anything.
    safe_name, extension, embedded_chunks = _prepare_upload(filename, file_bytes)

    # Legacy records (no stable document_id of their own) get a real one
    # once they go through this pipeline; regular records keep their id.
    new_document_id = uuid.uuid4().hex if document_id.startswith("legacy:") else document_id
    uploaded_at = datetime.now(timezone.utc).isoformat()
    vectors = [chunk["embedding"] for chunk in embedded_chunks]
    metadatas = _build_metadatas(embedded_chunks, safe_name, new_document_id, extension, uploaded_at)

    try:
        store.add(vectors, metadatas)
    except (ValueError, DimensionMismatchError) as error:
        raise KnowledgeUploadError(str(error)) from error

    try:
        store.remove_by_positions(old_positions)
    except IndexRemovalError as error:
        raise KnowledgeReplaceError(
            f"The new version was added, but the old version could not be removed: {error}"
        ) from error

    try:
        store.save()
    except OSError as error:
        raise KnowledgeReplaceError("Replaced in memory but failed to save changes to disk.") from error

    return {
        "document_id": new_document_id,
        "filename": safe_name,
        "old_filename": old_filename,
        "total_chunks": len(embedded_chunks),
        "status": "replaced",
    }


def rebuild_index() -> dict:
    """
    Rebuilds the FAISS index from scratch, treating the chunk text already
    stored in metadata as the source of truth — no original files are
    needed since each chunk's text was preserved at upload time.

    Safety: the new index is built and fully validated as a separate,
    independent VectorStore in memory. Nothing about the currently active
    index or its on-disk files is touched until the rebuilt one is
    confirmed complete and successfully saved. If anything fails along
    the way, the previous valid index keeps serving requests untouched.
    """
    try:
        current_store = get_store()
    except EmptyIndexError:
        return {"status": "empty", "total_chunks": 0, "documents": 0}

    source_chunks = [dict(meta) for _, meta in sorted(current_store.metadata.items())]
    if not source_chunks:
        return {"status": "empty", "total_chunks": 0, "documents": 0}

    dimension = get_embedding_dimension()

    try:
        embedded_chunks = embed_chunks(source_chunks)
    except Exception as error:
        raise KnowledgeReindexError(
            f"Rebuild failed while generating embeddings — the previous index is unchanged: {error}"
        ) from error

    new_store = VectorStore(dimension)
    vectors = [chunk["embedding"] for chunk in embedded_chunks]
    metadatas = [{key: value for key, value in chunk.items() if key != "embedding"} for chunk in embedded_chunks]

    try:
        new_store.add(vectors, metadatas)
    except (ValueError, DimensionMismatchError) as error:
        raise KnowledgeReindexError(
            f"Rebuild failed while assembling the new index — the previous index is unchanged: {error}"
        ) from error

    if new_store.total_vectors != len(source_chunks):
        raise KnowledgeReindexError(
            "Rebuild produced an incomplete index — the previous index is unchanged."
        )

    try:
        new_store.save()
    except OSError as error:
        raise KnowledgeReindexError(
            f"Rebuild succeeded in memory but failed to save to disk — the previous index is unchanged: {error}"
        ) from error

    # Only swap the active store once the rebuilt one is fully saved.
    set_active_store(new_store)

    document_count = len({_document_key(meta) for meta in new_store.metadata.values()})
    return {
        "status": "rebuilt",
        "total_chunks": new_store.total_vectors,
        "documents": document_count,
    }