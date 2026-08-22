"""
Document Processor
-------------------

Turns an uploaded file (TXT, PDF, or DOCX) into clean text.

Pipeline for this module only:

    Document -> File Type Detection -> Extractor -> Cleaner -> Clean Text

This module knows nothing about FastAPI, chunking, embeddings, or Groq.
It only extracts and cleans text. Keeping it separate from main.py means
we can test it, reuse it, and later swap pieces without touching routes.
"""

from __future__ import annotations

import io
import re

import pymupdf  # PyMuPDF (the "fitz" import name is now deprecated)
from docx import Document as DocxDocument

SUPPORTED_EXTENSIONS = {"txt", "pdf", "docx"}


class UnsupportedFileTypeError(Exception):
    """Raised when the uploaded file's extension isn't one we support."""


def get_file_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


# ---------- EXTRACTORS ----------
# Each extractor takes raw file bytes and returns (text, pages).
# "pages" is None for formats where the concept doesn't apply (TXT, DOCX).

def extract_txt(file_bytes: bytes) -> tuple[str, None]:
    # decode() turns raw bytes into a Python string using UTF-8.
    text = file_bytes.decode("utf-8")
    return text, None


def extract_pdf(file_bytes: bytes) -> tuple[str, int]:
    # PyMuPDF opens a PDF from an in-memory byte stream (no temp file needed).
    pdf = pymupdf.open(stream=file_bytes, filetype="pdf")
    page_texts = []

    for page in pdf:
        page_texts.append(page.get_text())

    pdf.close()

    # If the PDF has no extractable text (e.g. scanned pages), we simply
    # return empty text rather than attempting OCR.
    combined_text = "\n\n".join(page_texts)
    return combined_text, len(page_texts)


def extract_docx(file_bytes: bytes) -> tuple[str, None]:
    # python-docx needs a file-like object, so we wrap the bytes in BytesIO.
    document = DocxDocument(io.BytesIO(file_bytes))
    paragraphs = [paragraph.text for paragraph in document.paragraphs]

    # Keep paragraph breaks meaningful instead of collapsing everything.
    combined_text = "\n\n".join(paragraphs)
    return combined_text, None


EXTRACTORS = {
    "txt": extract_txt,
    "pdf": extract_pdf,
    "docx": extract_docx,
}


# ---------- CLEANER ----------

def clean_text(raw_text: str) -> str:
    """
    Deterministic cleanup only. No summarizing, no rewriting, no
    classification. Just tidy whitespace while preserving paragraphs.
    """
    # Normalize Windows/Mac line endings to a single \n style.
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

    # Collapse runs of horizontal whitespace (spaces/tabs) into one space.
    text = re.sub(r"[ \t]+", " ", text)

    # Trim trailing whitespace at the end of each line.
    text = re.sub(r" +\n", "\n", text)

    # Collapse 3+ blank lines down to exactly one blank line (one paragraph gap).
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Trim leading/trailing whitespace on the whole document.
    text = text.strip()

    return text


# ---------- ORCHESTRATION ----------

def process_document(filename: str, file_bytes: bytes) -> dict:
    """
    Runs the full pipeline for one uploaded file and returns a result dict
    with everything the API endpoint needs to build its JSON response.
    """
    extension = get_file_extension(filename)

    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type: '.{extension or 'unknown'}'. "
            f"Supported types are: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )

    extractor = EXTRACTORS[extension]
    raw_text, pages = extractor(file_bytes)
    cleaned = clean_text(raw_text)

    return {
        "filename": filename,
        "file_type": extension,
        "pages": pages,
        "characters": len(cleaned),
        "text": cleaned,
    }