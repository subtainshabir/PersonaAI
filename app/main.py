from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

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
    CorruptedStoreError,
    DimensionMismatchError,
    EmptyIndexError,
    create_store,
    get_store,
    load_store_from_disk,
)
from app.services.context_builder import build_context
from app.services.llm_service import LLMRequestError, MissingAPIKeyError, generate_answer
from app.services.database import DatabaseError, init_db
from app.services.conversation_service import (
    ConversationNotFoundError,
    InvalidRoleError,
    add_message,
    create_conversation,
    delete_conversation,
    get_conversation,
    get_conversations,
    get_messages,
    get_recent_messages,
    rename_conversation,
)
from app.admin_routes.router import router as admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        load_store_from_disk()
    except CorruptedStoreError as error:
        print(f"Warning: saved knowledge base could not be loaded: {error}")
    yield


app = FastAPI(title="PersonaAI", lifespan=lifespan)

# BASE_DIR points to this file's folder (app/), no matter where uvicorn is
# started from. This keeps "static" and "templates" resolvable either way.
BASE_DIR = Path(__file__).resolve().parent

# Mount the static folder so CSS/JS files are reachable at /static/...
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Jinja2 will render HTML from the templates folder
templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.include_router(admin_router)


# This defines the shape of the JSON the frontend must send us.
# FastAPI will automatically reject requests that don't match this shape.
class ChatRequest(BaseModel):
    query: str
    conversation_id: int


class SearchRequest(BaseModel):
    query: str
    top_k: int = 3


class ConversationCreateRequest(BaseModel):
    title: Optional[str] = None


class ConversationRenameRequest(BaseModel):
    title: str


class MessageCreateRequest(BaseModel):
    role: str
    content: str


@app.get("/")
def read_root(request: Request):
    # Renders templates/index.html and sends it to the browser
    return templates.TemplateResponse(request=request, name="index.html")


RETRIEVAL_TOP_K = 3
CONVERSATION_HISTORY_LIMIT = 6

# Returned whenever retrieval doesn't find sufficiently relevant context —
# the LLM is never asked to guess, so this exact message only ever comes
# from the retrieval step finding nothing usable, never from Groq itself.
NO_CONTEXT_MESSAGE = "I don't have that information in my knowledge base."


class RetrievalError(Exception):
    pass


def _retrieve_context(query: str, top_k: int = RETRIEVAL_TOP_K) -> dict:
    store = get_store()

    try:
        query_vector = embed_text(query)
        results = store.search(query_vector, top_k=top_k)
    except (EmptyIndexError, DimensionMismatchError):
        raise
    except Exception as error:
        raise RetrievalError(f"Failed to retrieve relevant information: {error}") from error

    formatted_results = [
        {
            "chunk_id": result.get("chunk_id"),
            "source": result.get("source") or "Unknown source",
            "score": round(result["score"], 4),
            "text": result.get("text"),
        }
        for result in results
    ]

    return build_context(formatted_results)


GREETINGS = {
    "hi", "hello", "hey", "hiya", "yo",
    "good morning", "good afternoon", "good evening",
    "how are you", "how's it going", "whats up", "what's up",
}


def _is_greeting(query: str) -> bool:
    normalized = query.strip().lower().strip("!.?")
    return normalized in GREETINGS


@app.post("/api/chat")
def chat(chat_request: ChatRequest):
    # Flow: Question -> Retrieval -> History -> Combined Prompt -> Groq -> Answer -> Save
    query = chat_request.query
    conversation_id = chat_request.conversation_id

    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    try:
        get_conversation(conversation_id)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except DatabaseError:
        raise HTTPException(status_code=500, detail="A database error occurred.")

    if _is_greeting(query):
        answer = "Hello! I'm PersonaAI. Ask me anything about my professional profile — education, skills, projects, or experience."
        sources = []
    else:
        try:
            context_result = _retrieve_context(query)
        except (EmptyIndexError, CorruptedStoreError):
            context_result = {"found_relevant_context": False, "context": "", "retrieved_chunks": []}
        except DimensionMismatchError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except RetrievalError:
            raise HTTPException(
                status_code=500,
                detail="Something went wrong while retrieving relevant information. Please try again.",
            )

        if not context_result["found_relevant_context"]:
            # Retrieval found nothing relevant enough — per spec, we do NOT
            # ask Groq to guess. Answer immediately without an API call.
            answer = NO_CONTEXT_MESSAGE
            sources = []
        else:
            try:
                history = get_recent_messages(conversation_id, CONVERSATION_HISTORY_LIMIT)
            except DatabaseError:
                history = []

            try:
                answer = generate_answer(query, context_result["context"], history)
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

    try:
        add_message(conversation_id, "user", query)
        add_message(conversation_id, "assistant", answer)
    except (InvalidRoleError, ValueError, DatabaseError):
        pass  # the answer is still returned even if saving history fails

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
        store.save()
    except (ValueError, DimensionMismatchError) as error:
        raise HTTPException(status_code=400, detail=str(error))
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Failed to save knowledge base to disk: {error}")

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
    except CorruptedStoreError as error:
        raise HTTPException(status_code=500, detail=f"Knowledge base is corrupted: {error}")
    except DimensionMismatchError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except RetrievalError:
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while retrieving relevant information. Please try again.",
        )

    return {
        "query": search_request.query,
        "retrieved_chunks": context_result["retrieved_chunks"],
        "context": context_result["context"],
        "found_relevant_context": context_result["found_relevant_context"],
    }


@app.post("/api/conversations")
def create_conversation_endpoint(request: ConversationCreateRequest):
    try:
        return create_conversation(request.title)
    except DatabaseError:
        raise HTTPException(status_code=500, detail="A database error occurred.")


@app.get("/api/conversations")
def list_conversations_endpoint():
    try:
        return get_conversations()
    except DatabaseError:
        raise HTTPException(status_code=500, detail="A database error occurred.")


@app.get("/api/conversations/{conversation_id}")
def get_conversation_endpoint(conversation_id: int):
    try:
        return get_conversation(conversation_id)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except DatabaseError:
        raise HTTPException(status_code=500, detail="A database error occurred.")


@app.patch("/api/conversations/{conversation_id}")
def rename_conversation_endpoint(conversation_id: int, request: ConversationRenameRequest):
    try:
        return rename_conversation(conversation_id, request.title)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except DatabaseError:
        raise HTTPException(status_code=500, detail="A database error occurred.")


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation_endpoint(conversation_id: int):
    try:
        delete_conversation(conversation_id)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except DatabaseError:
        raise HTTPException(status_code=500, detail="A database error occurred.")
    return {"status": "deleted", "id": conversation_id}


@app.post("/api/conversations/{conversation_id}/messages")
def add_message_endpoint(conversation_id: int, request: MessageCreateRequest):
    try:
        return add_message(conversation_id, request.role, request.content)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except (InvalidRoleError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))
    except DatabaseError:
        raise HTTPException(status_code=500, detail="A database error occurred.")


@app.get("/api/conversations/{conversation_id}/messages")
def get_messages_endpoint(conversation_id: int):
    try:
        return get_messages(conversation_id)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except DatabaseError:
        raise HTTPException(status_code=500, detail="A database error occurred.")