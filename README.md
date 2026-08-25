# PersonaAI

PersonaAI is a personal AI chatbot powered by Retrieval-Augmented Generation (RAG). It represents a person's professional profile using their own knowledge base, answering questions with grounded, source-backed responses rather than inventing personal information.

## Features

- Personal knowledge base built from your own documents
- PDF, DOCX, and TXT support
- Text extraction and cleaning
- Paragraph-aware chunking
- Sentence Transformer embeddings
- FAISS vector search
- Groq LLM for answer generation
- Grounded responses — no invented personal facts
- Source references for every answer
- Persistent knowledge base (FAISS index + metadata survive restarts)
- SQLite-backed conversation history
- Conversation memory across follow-up questions
- ChatGPT-style conversation sidebar (new, open, rename, delete)
- Responsive UI (desktop, tablet, mobile)
- Light/dark mode

## RAG Pipeline

```
Personal Information
    → Document Processing
    → Text Cleaning
    → Chunking
    → Embeddings
    → FAISS
    → Similarity Search
    → Relevant Context
    → Conversation Memory
    → Groq LLM
    → Grounded Response
    → Source References
```

## Technology Stack

**Backend:**
- Python
- FastAPI

**Frontend:**
- HTML
- CSS
- Bootstrap
- Vanilla JavaScript

**AI / RAG:**
- Groq API
- Sentence Transformers
- FAISS

**Storage:**
- SQLite
- JSON
- Local file storage

**Document Processing:**
- PyMuPDF
- python-docx

## Project Status

PersonaAI is currently under development. The core RAG pipeline and conversational architecture — document ingestion, chunking, embeddings, FAISS retrieval, grounded generation, and persistent conversation memory — are implemented and working.

Authentication, admin knowledge-base management, security hardening, performance optimization, testing, and deployment are still being developed.

## Future Work

- Admin authentication
- Protected `/admin` dashboard
- Knowledge-base management UI
- Document upload/update/delete
- Automatic FAISS re-indexing
- Embedding model lifecycle optimization
- Security improvements
- RAG evaluation
- Performance optimization
- Final UI/UX improvements
- Production deployment
- Optional voice input/responses
- Optional hybrid search
- Optional re-ranking

## Architecture

```
Public Chat
    → RAG
    → FAISS
    → Context
    → Groq
    → Grounded Answer

/admin (planned)
    → Login
    → Admin Dashboard
    → Knowledge Base Management
    → FAISS
```

Conversation history is handled separately by SQLite, independent of the FAISS knowledge base.

## Design Principles

- No React, Vue, or Angular — vanilla JavaScript only
- No LangChain or LlamaIndex — the RAG pipeline is built directly
- Personal facts must come from the knowledge base, never from model memory
- The LLM must not invent personal information
- FAISS is used for knowledge retrieval
- SQLite is used for conversation history
- Public users do not need accounts
- Only the owner/admin can manage the knowledge base

## Development Approach

PersonaAI is being built incrementally, phase by phase, with each phase focused on understanding one real RAG concept — extraction, chunking, embeddings, vector search, grounding, memory — rather than hiding the architecture behind a framework.

## License

This project is currently under development. A license will be added at a later stage.