# PersonaAI

**Personal AI RAG Chatbot**

PersonaAI is an AI chatbot designed to represent a user's professional profile using **Retrieval-Augmented Generation (RAG)**.

The system will be able to answer questions about:

- Education
- Skills
- Work experience
- Internships
- Projects
- Achievements
- Career goals
- Technical background
- Interests

## 🚧 Development Status

**PersonaAI is currently under active development.**

The project is being built step by step to understand the internal architecture of a RAG system rather than relying on frameworks such as LangChain or LlamaIndex.

## RAG Pipeline

```text
Personal Information
        ↓
Text Processing
        ↓
Chunking
        ↓
Embeddings
        ↓
FAISS
        ↓
Query Embedding
        ↓
Similarity Search
        ↓
Relevant Context
        ↓
Groq LLM
        ↓
Grounded Answer
