"""
main.py — FastAPI application entry point.

WHAT THIS FILE DOES:
  1. Creates the FastAPI app instance.
  2. Configures CORS so the React frontend (localhost:5173) can call the API.
  3. Registers all API routers (cases, sessions, chat).
  4. Provides a simple health-check endpoint.

HOW TO RUN:
  cd backend
  source .venv/bin/activate
  uvicorn app.main:app --reload       # dev mode — reloads on file changes
  uvicorn app.main:app --port 8000    # production-style (no reload)

CORS NOTE:
  ALLOWED_ORIGINS is read from settings (defaults to ["http://localhost:5173"]).
  In production, replace with your actual frontend domain.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import cases, sessions, chat, debug

# ------------------------------------------------------------------ #
# App instance
# ------------------------------------------------------------------ #
app = FastAPI(
    title="CaseNotes Chatbot API",
    description=(
        "RAG-based chatbot for child welfare case notes. "
        "Retrieves relevant notes via pgvector and answers questions with Gemini 2.5 Flash."
    ),
    version="0.1.0",
)

# ------------------------------------------------------------------ #
# CORS middleware
# ------------------------------------------------------------------ #
# allow_origins        – which browser origins may call this API
# allow_credentials    – allow cookies (not needed for this POC)
# allow_methods        – allow all HTTP methods (GET, POST, etc.)
# allow_headers        – allow all request headers (needed for Content-Type)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------ #
# Routers
# ------------------------------------------------------------------ #
# Each router is prefixed internally (e.g. /api/cases, /api/sessions, /api/chat).
app.include_router(cases.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(debug.router)   # chunk inspection — dev only

# ------------------------------------------------------------------ #
# Health check
# ------------------------------------------------------------------ #
@app.get("/health", tags=["meta"])
async def health():
    """
    Returns 200 OK.  Used to verify the server is running before
    running scripts or frontend dev.
    """
    return {"status": "ok"}
