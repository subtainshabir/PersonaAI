from pathlib import Path

from dotenv import load_dotenv

# Loaded before any service reads os.environ, so GROQ_API_KEY from a local
# .env file is available by the time the first chat request comes in.
load_dotenv()

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.services.document_processor import UnsupportedFileTypeError, process_document
from app.services.chunker import EmptyTextError, chunk_text
from app.services.embedding_service import (
    MODEL_NAME,
    embed_chunks,
    embed_text,
    get_embedding_dimension,
    run_similarity_experiment,
)
from app.services.vector_store import (
    DimensionMismatchError,
    EmptyIndexError,
    create_store,
    get_store,
)
from app.services.context_builder import build_context
from app.services.llm_service import LLMRequestError, MissingAPIKeyError, generate_answer

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
    query: str


class SearchRequest(BaseModel):
    query: str
    top_k: int = 3


@app.get("/")
def read_root(request: Request):
    # Renders templates/index.html and sends it to the browser
    return templates.TemplateResponse(request=request, name="index.html")


RETRIEVAL_TOP_K = 3

# Returned whenever retrieval doesn't find sufficiently relevant context —
# the LLM is never asked to guess, so this exact message only ever comes
# from the retrieval step finding nothing usable, never from Groq itself.
NO_CONTEXT_MESSAGE = "I don't have that information in my knowledge base."


def _retrieve_context(query: str, top_k: int = RETRIEVAL_TOP_K) -> dict:
    """
    Shared by /api/chat and /api/search: embeds the query, searches the
    FAISS store, and assembles context — the exact
    Question -> Query Embedding -> FAISS Search -> Context pipeline, kept
    in one place so both endpoints stay consistent.
    """
    store = get_store()  # raises EmptyIndexError if nothing is indexed

    # Same embedding_service, same cached model used for document chunks —
    # query and chunk vectors must come from the same model to be comparable.
    query_vector = embed_text(query)
    results = store.search(query_vector, top_k=top_k)

    formatted_results = [
        {
            "chunk_id": result.get("chunk_id"),
            "source": result.get("source"),
            "score": round(result["score"], 4),
            "text": result.get("text"),
        }
        for result in results
    ]

    return build_context(formatted_results)


@app.post("/api/chat")
def chat(chat_request: ChatRequest):
    # Flow: Question -> Query Embedding -> FAISS Search -> Context -> Groq -> Answer
    query = chat_request.query

    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    try:
        context_result = _retrieve_context(query)
    except EmptyIndexError:
        # No document has been indexed yet — nothing to answer from, and
        # nothing to send to the LLM.
        return {"query": query, "answer": NO_CONTEXT_MESSAGE, "sources": []}
    except DimensionMismatchError as error:
        raise HTTPException(status_code=400, detail=str(error))

    if not context_result["found_relevant_context"]:
        # Retrieval found nothing relevant enough — per spec, we do NOT
        # ask Groq to guess. Answer immediately without an API call.
        return {"query": query, "answer": NO_CONTEXT_MESSAGE, "sources": []}

    try:
        answer = generate_answer(query, context_result["context"])
    except MissingAPIKeyError as error:
        raise HTTPException(status_code=500, detail=str(error))
    except LLMRequestError as error:
        raise HTTPException(status_code=502, detail=str(error))

    sources = [
        {
            "chunk_id": chunk["chunk_id"],
            "source": chunk["source"],
            "score": chunk["score"],
        }
        for chunk in context_result["retrieved_chunks"]
    ]

    return {"query": query, "answer": answer, "sources": sources}


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


INDEX_TYPE_NAME = "IndexFlatIP"


@app.post("/api/documents/index")
async def index_document_endpoint(file: UploadFile = File(...)):
    # Flow: Upload -> extract -> clean -> chunk -> embed -> FAISS index
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

    # Replaces whatever document was previously indexed. PersonaAI has no
    # database yet, so this dev-phase store only holds one document's
    # worth of vectors at a time, for as long as the server keeps running.
    store = create_store(dimension)

    vectors = [chunk["embedding"] for chunk in embedded_chunks]
    metadatas = [
        {
            "chunk_id": chunk["chunk_id"],
            "source": processed["filename"],
            "text": chunk["text"],
        }
        for chunk in embedded_chunks
    ]

    try:
        store.add(vectors, metadatas)
    except (ValueError, DimensionMismatchError) as error:
        raise HTTPException(status_code=400, detail=str(error))

    return {
        "filename": processed["filename"],
        "total_chunks": len(embedded_chunks),
        "embedding_dimension": dimension,
        "index_type": INDEX_TYPE_NAME,
        "status": "indexed",
    }


@app.post("/api/search")
def search_endpoint(search_request: SearchRequest):
    # Flow: query -> query embedding -> FAISS search -> matching chunks.
    # This endpoint is for understanding/testing retrieval only — it does
    # not call an LLM or produce a final answer.
    if not search_request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    if search_request.top_k < 1:
        raise HTTPException(status_code=400, detail="top_k must be at least 1.")

    try:
        context_result = _retrieve_context(search_request.query, top_k=search_request.top_k)
    except EmptyIndexError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except DimensionMismatchError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return {
        "query": search_request.query,
        "retrieved_chunks": context_result["retrieved_chunks"],
        "context": context_result["context"],
        "found_relevant_context": context_result["found_relevant_context"],
    }