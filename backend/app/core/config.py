"""
config.py — Application settings loaded from environment variables.

We use pydantic-settings so every variable is type-checked at startup.
The values are read from a `.env` file in the `backend/` directory
(or from real environment variables in production).

Required variables:
  DATABASE_URL  - Neon asyncpg connection string
                  e.g. postgresql+asyncpg://user:pass@host/dbname?sslmode=require
  GOOGLE_API_KEY - Gemini API key from Google AI Studio
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    # Full asyncpg-compatible URL for SQLAlchemy's async engine.
    # Must start with "postgresql+asyncpg://"
    DATABASE_URL: str

    # ------------------------------------------------------------------ #
    # LLM
    # ------------------------------------------------------------------ #
    # Google AI Studio key that authorises calls to Gemini 2.5 Flash
    GOOGLE_API_KEY: str

    # ------------------------------------------------------------------ #
    # Embedding model
    # ------------------------------------------------------------------ #
    # HuggingFace model id — downloaded once and cached locally by
    # sentence-transformers.  We pin this here so it's easy to swap.
    EMBEDDING_MODEL: str = "BAAI/bge-large-en-v1.5"

    # Dimensionality produced by bge-large-en-v1.5 (must match the
    # VECTOR(n) column in the database schema)
    EMBEDDING_DIM: int = 1024

    # ------------------------------------------------------------------ #
    # RAG retrieval
    # ------------------------------------------------------------------ #
    # How many case-note chunks to surface per user query
    TOP_K: int = 6

    # ------------------------------------------------------------------ #
    # CORS
    # ------------------------------------------------------------------ #
    # Origins allowed to call the API.  The Vite dev server runs on 5173.
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:5173",
        "https://casenotes-chatbot.vercel.app",
    ]

    # ------------------------------------------------------------------ #
    # pydantic-settings config: tell it where the .env file lives
    # ------------------------------------------------------------------ #
    model_config = SettingsConfigDict(
        env_file=".env",           # relative to wherever uvicorn is started
        env_file_encoding="utf-8",
        extra="ignore",            # silently ignore unknown env vars
    )


# Module-level singleton — import this everywhere instead of
# re-instantiating Settings() in each file.
settings = Settings()
