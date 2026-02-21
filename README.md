# CaseNotes Chatbot

A RAG-based chatbot that lets child welfare caseworkers ask natural-language questions about case notes. Select a case and a 6-month window, then chat — the system retrieves the most relevant note excerpts via pgvector and answers using Gemini 2.5 Flash.

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | React + Vite + TypeScript + Tailwind CSS |
| Backend | Python + FastAPI (async) |
| Database | Neon (hosted Postgres + pgvector) |
| Embeddings | `BAAI/bge-large-en-v1.5` via `sentence-transformers` (local, 1024 dims) |
| LLM | Gemini 2.5 Flash via `google-generativeai` |

---

## How it works

1. Case notes are chunked (≤1200 chars, with smart sentence-aware overlap) and embedded locally using BGE.
2. Embeddings are stored in Neon using the `pgvector` extension.
3. When a user asks a question, the query is embedded and the top-6 most similar chunks (filtered by case + date window) are retrieved via cosine similarity.
4. Retrieved chunks are passed as context to Gemini 2.5 Flash, which generates a grounded answer citing specific notes by date and caseworker.

---

## Local development

### Prerequisites

- Python 3.12+
- Node 18+
- A [Neon](https://neon.tech) project with the `vector` extension enabled
- A [Google AI Studio](https://aistudio.google.com/app/apikey) API key

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy and fill in env vars
cp .env.example .env
# Edit .env: set DATABASE_URL and GOOGLE_API_KEY

# Seed dummy data (10 cases, 50+ notes each)
python3 scripts/seed_data.py

# Chunk and embed all notes (takes a few minutes — downloads ~1.3 GB model on first run)
python3 scripts/embed_notes.py

# Start the API server
python3 -m uvicorn app.main:app --reload
# Runs on http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install

# Create env file
echo "VITE_API_BASE_URL=http://localhost:8000" > .env

npm run dev
# Runs on http://localhost:5173
```

---

## Deployment

### Frontend → Vercel

The frontend is a standard Vite app and deploys to Vercel in a few clicks.

**Step 1 — Push to GitHub**

Make sure your repo is on GitHub. Vercel imports directly from GitHub.

**Step 2 — Import to Vercel**

1. Go to [vercel.com](https://vercel.com) → **Add New Project**
2. Import your GitHub repository
3. Set the **Root Directory** to `frontend`
4. Vercel auto-detects Vite — keep the defaults:
   - Build command: `npm run build`
   - Output directory: `dist`

**Step 3 — Add environment variable**

In Vercel project settings → **Environment Variables**, add:

```
VITE_API_BASE_URL = https://your-backend-url.railway.app
```

(Fill in your actual backend URL after deploying the backend below.)

**Step 4 — Deploy**

Click **Deploy**. Future pushes to `main` auto-deploy.

---

### Backend → Railway

The backend cannot run on Vercel — the embedding model (`BAAI/bge-large-en-v1.5`) is ~1.3 GB, which exceeds Vercel's serverless function size limit. [Railway](https://railway.app) is the simplest alternative.

**Step 1 — Install the Railway CLI**

```bash
brew install railway
```

**Step 2 — Login and initialise**

```bash
railway login
cd backend
railway init        # creates a new Railway project linked to this folder
```

**Step 3 — Add a Procfile**

Create `backend/Procfile`:

```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

**Step 4 — Set environment variables on Railway**

In the Railway dashboard → your project → **Variables**, add:

```
DATABASE_URL    = <your Neon connection string>
GOOGLE_API_KEY  = <your Google AI Studio key>
```

**Step 5 — Deploy**

```bash
railway up
```

Railway builds the container, installs dependencies (including downloading the embedding model on first run), and starts the server. It gives you a public URL like `https://your-app.railway.app`.

**Step 6 — Update CORS**

In `backend/app/core/config.py`, add your Vercel frontend URL to `ALLOWED_ORIGINS`:

```python
ALLOWED_ORIGINS: list[str] = [
    "http://localhost:5173",
    "https://your-app.vercel.app",   # add this
]
```

Redeploy: `railway up`

**Step 7 — Update Vercel env var**

In Vercel → your project → **Environment Variables**, update:

```
VITE_API_BASE_URL = https://your-app.railway.app
```

Then trigger a redeploy (push a commit or click **Redeploy** in the Vercel dashboard).

---

## Project structure

```
casenotes_chatbot/
├── frontend/
│   └── src/
│       ├── api/client.ts           # fetch wrappers
│       ├── components/
│       │   ├── CaseSelector.tsx    # step 1: case + date window picker with timeline
│       │   ├── ChatInterface.tsx   # step 2: chat UI with auto-scroll
│       │   └── MessageBubble.tsx   # message bubble + collapsible sources accordion
│       ├── types/index.ts
│       └── App.tsx
│
└── backend/
    ├── app/
    │   ├── core/
    │   │   ├── config.py           # pydantic settings (env vars)
    │   │   └── database.py         # async SQLAlchemy engine (asyncpg)
    │   ├── models/tables.py        # ORM models: Case, CaseNote, NoteChunk, ChatSession, ChatMessage
    │   ├── services/
    │   │   ├── chunking.py         # NLTK sentence-aware chunker (≤1200 chars, smart overlap)
    │   │   ├── embedding.py        # BGE model wrapper with retrieval prefix
    │   │   ├── vector_search.py    # pgvector cosine similarity search on note_chunks
    │   │   └── llm.py              # Gemini 2.5 Flash prompt assembly + API call
    │   └── api/routes/
    │       ├── cases.py            # GET /api/cases (includes note date range per case)
    │       ├── sessions.py         # POST /api/sessions, GET /api/sessions/{id}/messages
    │       ├── chat.py             # POST /api/chat (full RAG pipeline)
    │       └── debug.py            # GET /api/debug/... (chunk inspection, dev only)
    └── scripts/
        ├── seed_data.py            # generate and insert 10 cases × 50+ notes
        └── embed_notes.py          # chunk all notes and embed with BGE
```
