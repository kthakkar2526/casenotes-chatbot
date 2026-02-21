# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Is the Project

A RAG-based chatbot for child welfare caseworkers. The user selects a case number and a 6-month date window, then asks natural-language questions. The backend finds the most semantically relevant case notes via pgvector and feeds them as context to Gemini 2.5 Flash, which generates a cited answer.

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React + Vite + TypeScript + Tailwind CSS v3 |
| Backend | Python + FastAPI (async) |
| Database | Neon (hosted Postgres + pgvector) |
| Embeddings | `BAAI/bge-large-en-v1.5` via `sentence-transformers` (1024 dims, local) |
| LLM | Gemini 2.5 Flash via `google-generativeai` |

## Dev Commands

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start the API server (runs on :8000)
uvicorn app.main:app --reload

# One-time setup: seed DB then embed notes
python scripts/seed_data.py
python scripts/embed_notes.py
```

Copy `backend/.env.example` to `backend/.env` and fill in `DATABASE_URL` and `GOOGLE_API_KEY` before running anything.

### Frontend

```bash
cd frontend
npm install
npm run dev       # runs on :5173
npm run build     # production build
```

`frontend/.env` already contains `VITE_API_BASE_URL=http://localhost:8000`.

## Architecture

### Request flow for POST /api/chat

```
User question
  → embed_query()          # bge-large-en-v1.5, adds BGE retrieval prefix
  → find_similar_notes()   # pgvector cosine search, filtered by case_id + date window
  → generate_answer()      # Gemini 2.5 Flash, context notes + chat history
  → persist messages       # chat_messages table
  → return {answer, sources}
```

### Key files

| File | Purpose |
|------|---------|
| `backend/app/core/config.py` | All env vars via pydantic-settings (`settings` singleton) |
| `backend/app/core/database.py` | Async SQLAlchemy engine + `get_db()` FastAPI dependency |
| `backend/app/models/tables.py` | ORM models: `Case`, `CaseNote`, `ChatSession`, `ChatMessage` |
| `backend/app/services/embedding.py` | `embed_query()` / `embed_documents()` — BGE model singleton |
| `backend/app/services/vector_search.py` | pgvector cosine similarity query with date filter |
| `backend/app/services/llm.py` | Gemini prompt assembly + API call |
| `backend/app/api/routes/chat.py` | Core RAG route — orchestrates all services |
| `backend/scripts/seed_data.py` | Generates 10 cases × 50–55 notes and inserts into DB |
| `backend/scripts/embed_notes.py` | Batch-embeds all notes with NULL embedding, writes vectors to DB |
| `frontend/src/api/client.ts` | Typed fetch wrappers for all backend endpoints |
| `frontend/src/App.tsx` | Two-state machine: CaseSelector → ChatInterface |

### Database schema

```
cases            (id, case_number, client_name, created_at)
case_notes       (id, case_id→cases, note_text, embedding VECTOR(1024),
                  caseworker_name, note_type, created_at)
chat_sessions    (id, case_id→cases, start_date, end_date, created_at)
chat_messages    (id, session_id→chat_sessions, role, content, created_at)
```

The ivfflat index on `case_notes.embedding` is created by `seed_data.py`.

### BGE embedding quirk

BGE models require a query prefix at **search time only** (not when indexing documents):
```
"Represent this sentence for searching relevant passages: " + user_query
```
This is handled automatically in `embedding.embed_query()`. Document embedding uses no prefix.

## Code Style Note

Every file in this project contains inline comments explaining:
- **Why** a decision was made (not just what the code does)
- **How** data flows through the function
- Any non-obvious behaviour (e.g. BGE prefix, async commit in `get_db`, ivfflat index requirement)
