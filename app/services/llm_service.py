"""
LLM Service
-----------

Sends a user's question, plus context already retrieved from FAISS, to
Groq and returns a grounded answer.

    Question + Context -> Groq -> Grounded Answer

This module only talks to the LLM. It knows nothing about documents,
chunking, embeddings, or vector search — it receives a question and a
context string and returns text:

    document_processor.py:  File    -> Extract -> Clean -> Text
    chunker.py:              Text    -> Chunks
    embedding_service.py:    Chunks  -> Vectors
    vector_store.py:         Vectors -> Search results
    context_builder.py:      Search results -> Context
    llm_service.py:          Question + Context -> Answer
"""

from __future__ import annotations

import os

from groq import Groq

# A small, fast Groq-hosted model. Kept as a constant so it's easy to
# change later without hunting through the code.
GROQ_MODEL = "llama-3.1-8b-instant"

# Instructs the model to answer strictly from the provided context instead
# of its own general knowledge, and to say so plainly when the context
# doesn't cover the question — this is what keeps answers "grounded"
# rather than invented.
SYSTEM_PROMPT = """You are PersonaAI, an assistant that answers questions about a specific person's professional profile.

Rules you must follow:
- Answer only using the context provided below. Do not use any outside knowledge about the person.
- Do not invent, guess, or infer personal information that is not explicitly stated in the context.
- If the context does not contain the answer, respond with exactly this sentence and nothing else: "I don't have that information in my knowledge base."
- Treat the retrieved context as the source of truth, even if it seems incomplete.
- Answer naturally and professionally, as if you were speaking on the person's behalf.
- Do not mention retrieval, embeddings, vectors, chunks, or any other internal implementation detail unless the user explicitly asks how the system works."""


class MissingAPIKeyError(Exception):
    """Raised when GROQ_API_KEY isn't set in the environment."""


class LLMRequestError(Exception):
    """Raised when the Groq API call itself fails (network, auth, rate limit, etc.)."""


def _get_client() -> Groq:
    # Read lazily (not at import time) so a .env file loaded by main.py
    # after this module is imported is still picked up correctly.
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise MissingAPIKeyError(
            "GROQ_API_KEY is not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def generate_answer(query: str, context: str) -> str:
    """
    Sends the question and context to Groq and returns the grounded
    answer as plain text.

    Callers are responsible for deciding WHETHER to call this at all —
    this function assumes context is non-empty and relevant. The "I don't
    have that information" case for empty/irrelevant context is handled
    by the caller before this function is ever reached, so no API call
    (and no cost) is spent on questions we already know we can't answer.
    """
    if not query.strip():
        raise ValueError("query cannot be empty.")
    if not context.strip():
        raise ValueError("context cannot be empty — nothing to ground the answer in.")

    client = _get_client()
    user_message = f"Context:\n{context}\n\nQuestion: {query}"

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_tokens=512,
        )
    except Exception as error:
        raise LLMRequestError(f"Groq request failed: {error}") from error

    answer = response.choices[0].message.content
    return answer.strip() if answer else ""