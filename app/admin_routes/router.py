from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.auth_service import (
    SESSION_COOKIE_NAME,
    RateLimitedError,
    check_rate_limit,
    cookies_require_secure,
    create_session_token,
    invalidate_session_token,
    record_failed_attempt,
    record_successful_attempt,
    verify_credentials,
    verify_session_token,
)
from app.services.conversation_service import get_conversations
from app.services.database import DatabaseError
from app.services.job_service import get_job, list_jobs
from app.services.knowledge_service import (
    DocumentNotFoundError,
    KnowledgeDeleteError,
    KnowledgeReindexError,
    KnowledgeReplaceError,
    KnowledgeUploadError,
    delete_document,
    get_document_detail,
    get_knowledge_overview,
    rebuild_index,
    replace_document,
    run_upload_job,
    start_upload_job,
)
from app.services.vector_store import EmptyIndexError, get_store

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def get_current_admin(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return verify_session_token(token)


def _get_dashboard_stats() -> dict:
    stats = {
        "chunk_count": None,
        "document_count": None,
        "conversation_count": None,
        "llm_configured": bool(os.environ.get("GROQ_API_KEY")),
    }

    try:
        store = get_store()
        stats["chunk_count"] = store.total_vectors
        stats["document_count"] = len(
            {meta.get("source") for meta in store.metadata.values() if meta.get("source")}
        )
    except EmptyIndexError:
        stats["chunk_count"] = 0
        stats["document_count"] = 0

    try:
        stats["conversation_count"] = len(get_conversations())
    except DatabaseError:
        pass

    return stats


def _format_display_time(iso_string: str | None) -> str | None:
    """Formats a stored ISO timestamp for display only — the raw ISO value
    is left untouched everywhere else (JSON API responses, stored metadata)."""
    if not iso_string:
        return iso_string
    try:
        value = datetime.fromisoformat(iso_string)
    except ValueError:
        return iso_string
    return value.strftime("%b %d, %Y · %I:%M %p UTC")


def require_admin_api(request: Request) -> str:
    """Dependency for JSON admin API routes: unauthenticated requests get a 401."""
    admin = get_current_admin(request)
    if not admin:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return admin


@router.get("/admin/login")
def admin_login_page(request: Request):
    if get_current_admin(request):
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(request=request, name="admin_login.html", context={"error": None})


@router.post("/admin/login")
async def admin_login_submit(request: Request):
    form = await request.form()
    username = str(form.get("username") or "").strip()
    password = str(form.get("password") or "")
    client_ip = _client_ip(request)

    generic_error = "Invalid username or password."

    try:
        check_rate_limit(client_ip)
    except RateLimitedError:
        return templates.TemplateResponse(
            request=request,
            name="admin_login.html",
            context={"error": "Too many failed attempts. Please wait a few minutes and try again."},
            status_code=429,
        )

    if not username or not password or not verify_credentials(username, password):
        record_failed_attempt(client_ip)
        return templates.TemplateResponse(
            request=request,
            name="admin_login.html",
            context={"error": generic_error},
            status_code=401,
        )

    record_successful_attempt(client_ip)
    token = create_session_token(username)

    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=cookies_require_secure(),
        samesite="lax",
        max_age=12 * 60 * 60,
        path="/",
    )
    return response


@router.get("/admin")
def admin_dashboard(request: Request):
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse(url="/admin/login", status_code=303)
    context = {"admin_username": admin, "active_page": "dashboard", **_get_dashboard_stats()}
    return templates.TemplateResponse(request=request, name="admin_dashboard.html", context=context)


@router.get("/admin/knowledge")
def admin_knowledge_page(request: Request):
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse(url="/admin/login", status_code=303)
    context = {"admin_username": admin, "active_page": "knowledge", **get_knowledge_overview()}
    context["last_updated"] = _format_display_time(context.get("last_updated"))
    context["documents"] = [
        {**doc, "uploaded_at": _format_display_time(doc.get("uploaded_at"))}
        for doc in context.get("documents", [])
    ]
    return templates.TemplateResponse(request=request, name="admin_knowledge.html", context=context)


@router.post("/admin/knowledge/upload")
async def admin_knowledge_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    admin: str = Depends(require_admin_api),
):
    file_bytes = await file.read()
    try:
        job_info = start_upload_job(file.filename, file_bytes)
    except KnowledgeUploadError as error:
        raise HTTPException(status_code=400, detail=str(error))

    background_tasks.add_task(run_upload_job, job_info["job_id"], job_info["filename"], file_bytes)
    return {"job_id": job_info["job_id"], "filename": job_info["filename"], "status": "pending"}


@router.get("/admin/knowledge/jobs")
def admin_knowledge_jobs(admin: str = Depends(require_admin_api)):
    return list_jobs(job_type="upload")


@router.get("/admin/knowledge/jobs/{job_id}")
def admin_knowledge_job_detail(job_id: str, admin: str = Depends(require_admin_api)):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.get("/admin/knowledge/documents/{document_id}")
def admin_knowledge_document_detail(document_id: str, admin: str = Depends(require_admin_api)):
    try:
        return get_document_detail(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.delete("/admin/knowledge/documents/{document_id}")
def admin_knowledge_document_delete(document_id: str, admin: str = Depends(require_admin_api)):
    try:
        return delete_document(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except KnowledgeDeleteError as error:
        raise HTTPException(status_code=500, detail=str(error))


@router.post("/admin/knowledge/documents/{document_id}/replace")
async def admin_knowledge_document_replace(
    document_id: str,
    file: UploadFile = File(...),
    admin: str = Depends(require_admin_api),
):
    file_bytes = await file.read()
    try:
        return replace_document(document_id, file.filename, file_bytes)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except KnowledgeUploadError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except KnowledgeReplaceError as error:
        raise HTTPException(status_code=500, detail=str(error))


@router.post("/admin/knowledge/rebuild")
def admin_knowledge_rebuild(admin: str = Depends(require_admin_api)):
    try:
        return rebuild_index()
    except KnowledgeReindexError as error:
        raise HTTPException(status_code=500, detail=str(error))


@router.get("/admin/logout")
def admin_logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    invalidate_session_token(token)
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return response