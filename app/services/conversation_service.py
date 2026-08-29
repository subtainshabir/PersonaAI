from __future__ import annotations

import functools
import re
import sqlite3
from datetime import datetime, timezone

from app.services.database import DatabaseError, get_connection

VALID_ROLES = {"user", "assistant"}
DEFAULT_TITLE = "New Conversation"
MAX_TITLE_LENGTH = 80

_HTML_TAG_RE = re.compile(r"<[^>]*>")
_CONTROL_CHARS_RE = re.compile(r"[\r\n\t\x00-\x1f\x7f]")


class ConversationNotFoundError(Exception):
    pass


class InvalidRoleError(Exception):
    pass


def _wrap_db_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except sqlite3.Error as error:
            raise DatabaseError(f"Database operation failed: {error}") from error
    return wrapper


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_title(title: str) -> str:
    """
    Strips any HTML tags, control characters (including newlines), and
    excess length from a title before it's ever stored — applied to every
    write path (auto-generated or a future manual rename) so no unsafe
    text reaches the sidebar.
    """
    title = _HTML_TAG_RE.sub("", title or "")
    title = _CONTROL_CHARS_RE.sub(" ", title)
    title = re.sub(r"\s+", " ", title).strip()
    title = title.strip("\"'")
    if len(title) > MAX_TITLE_LENGTH:
        title = title[:MAX_TITLE_LENGTH].rstrip()
    return title


def is_default_title(title: str) -> bool:
    return (title or "").strip().lower() == DEFAULT_TITLE.lower()


def generate_fallback_title(message: str) -> str:
    """
    A safe, non-LLM title used when generation fails or isn't available:
    just the first few words of the user's own message, sanitized the
    same way any other title is. Naturally preserves whatever language
    the user wrote in, since it's their own words.
    """
    words = (message or "").strip().split()
    fallback = " ".join(words[:8])
    return _sanitize_title(fallback) or DEFAULT_TITLE


@_wrap_db_errors
def create_conversation(title: str | None = None) -> dict:
    title = _sanitize_title(title or "") or DEFAULT_TITLE
    timestamp = _now()
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)",
            (title, timestamp, timestamp),
        )
        conversation_id = cursor.lastrowid
    return get_conversation(conversation_id)


@_wrap_db_errors
def get_conversation(conversation_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    if row is None:
        raise ConversationNotFoundError(f"Conversation {conversation_id} not found.")
    return dict(row)


@_wrap_db_errors
def get_conversations() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


@_wrap_db_errors
def rename_conversation(conversation_id: int, title: str) -> dict:
    title = _sanitize_title(title)
    if not title:
        raise ValueError("title cannot be empty.")
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), conversation_id),
        )
        if cursor.rowcount == 0:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found.")
    return get_conversation(conversation_id)


@_wrap_db_errors
def delete_conversation(conversation_id: int) -> None:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        if cursor.rowcount == 0:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found.")


@_wrap_db_errors
def add_message(conversation_id: int, role: str, content: str) -> dict:
    if role not in VALID_ROLES:
        raise InvalidRoleError(f"role must be one of {sorted(VALID_ROLES)}, got {role!r}.")
    if not content.strip():
        raise ValueError("content cannot be empty.")

    get_conversation(conversation_id)

    timestamp = _now()
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, timestamp),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (timestamp, conversation_id),
        )
        message_id = cursor.lastrowid

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, conversation_id, role, content, created_at FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
    return dict(row)


@_wrap_db_errors
def get_messages(conversation_id: int) -> list[dict]:
    get_conversation(conversation_id)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, conversation_id, role, content, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY created_at ASC, id ASC",
            (conversation_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@_wrap_db_errors
def get_recent_messages(conversation_id: int, limit: int) -> list[dict]:
    get_conversation(conversation_id)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, conversation_id, role, content, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]