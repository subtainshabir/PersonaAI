from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.services.document_processor import UnsupportedFileTypeError, process_document
from app.services.chunker import EmptyTextError, chunk_text
from app.services.embedding_service import (
    MODEL_NAME,
    embed_chunks,
    get_embedding_dimension,
    run_similarity_experiment,
)

app = FastAPI(title="PersonaAI")

# BASE_DIR points to this file's folder (app/), no matter where uvicorn is
# started from. This keeps "static" and "templates" resolvable either way.
BASE_DIR = Path(__file__).resolve().parent

# Mount the static folder so CSS/JS files are reachable at /static/...
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Jinja2 will render HTML from the templates folder
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# This defines the shape of the JSON the frontend must send us.
# FastAPI will automatically reject requests that don't match this shape.
class ChatRequest(BaseModel):
    message: str


@app.get("/")
def read_root(request: Request):
    # Renders templates/index.html and sends it to the browser
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/api/chat")
def chat(chat_request: ChatRequest):
    # Phase 1 has no knowledge base or LLM yet, so we return a fixed reply.
    # This lets us confirm the frontend and backend are talking to each other.
    return {
        "response": "I'm PersonaAI. My knowledge base is not connected yet. "
                     "This functionality will be added in the RAG phases."
    }


@app.post("/api/documents/process")
async def process_document_endpoint(file: UploadFile = File(...)):
    # Phase 2 only extracts and cleans text. Nothing here touches
    # embeddings, FAISS, or an LLM.
    file_bytes = await file.read()

    try:
        result = process_document(file.filename, file_bytes)
    except UnsupportedFileTypeError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Could not process file: {error}")

    return result


@app.post("/api/documents/chunk")
async def chunk_document_endpoint(file: UploadFile = File(...)):
    # Flow: Upload -> document_processor (extract + clean) -> chunker -> JSON
    file_bytes = await file.read()

    try:
        processed = process_document(file.filename, file_bytes)
    except UnsupportedFileTypeError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Could not process file: {error}")

    try:
        chunks = chunk_text(processed["text"])
    except EmptyTextError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return {
        "filename": processed["filename"],
        "clean_text": processed["text"],
        "total_chunks": len(chunks),
        "chunks": chunks,
    }


# How many numbers from each vector to show in API responses. The full
# vector (384 numbers) still exists in memory during processing — we just
# don't want to ship hundreds of floats over JSON for a learning exercise.
EMBEDDING_PREVIEW_LENGTH = 5


@app.post("/api/documents/embed")
async def embed_document_endpoint(file: UploadFile = File(...)):
    # Flow: Upload -> document_processor -> chunker -> embedding_service -> JSON
    file_bytes = await file.read()

    try:
        processed = process_document(file.filename, file_bytes)
    except UnsupportedFileTypeError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Could not process file: {error}")

    try:
        chunks = chunk_text(processed["text"])
    except EmptyTextError as error:
        raise HTTPException(status_code=400, detail=str(error))

    embedded_chunks = embed_chunks(chunks)
    dimension = get_embedding_dimension()

    response_chunks = [
        {
            "chunk_id": chunk["chunk_id"],
            "text": chunk["text"],
            "characters": chunk["characters"],
            "embedding_preview": chunk["embedding"][:EMBEDDING_PREVIEW_LENGTH],
        }
        for chunk in embedded_chunks
    ]

    return {
        "filename": processed["filename"],
        "embedding_model": MODEL_NAME,
        "embedding_dimension": dimension,
        "total_chunks": len(response_chunks),
        "chunks": response_chunks,
    }


@app.get("/api/embeddings/similarity-demo")
def similarity_demo_endpoint():
    # A small, self-contained demo: two related sentences vs. one unrelated
    # sentence, compared with cosine similarity. No FAISS, no retrieval —
    # just proof that semantically similar text produces similar vectors.
    return run_similarity_experiment()