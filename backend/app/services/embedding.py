"""
embedding.py — Wrapper around BAAI/bge-large-en-v1.5 via sentence-transformers.

WHY BGE-LARGE-EN-V1.5?
  BGE (BAAI General Embedding) large English v1.5 is a top-ranked embedding
  model on the MTEB benchmark.  It produces 1024-dimensional vectors and runs
  locally — no external API or cost per token.

KEY BGE QUIRK — RETRIEVAL PREFIX:
  BGE models are trained with two modes:
    • Indexing documents  → embed the raw text as-is.
    • Querying            → prepend the string
        "Represent this sentence for searching relevant passages: "
      to the query before embedding.
  Skipping this prefix at query time degrades retrieval quality noticeably.
  This module handles the prefix automatically so callers don't need to worry.

SINGLETON PATTERN:
  Loading a large model (≈1.3 GB) takes several seconds.  We load it once
  at module import time and reuse the same SentenceTransformer instance for
  every request.  In a production multi-process setup you'd want to share the
  model via a dedicated embedding service, but for this POC a singleton is fine.
"""

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.core.config import settings

# ------------------------------------------------------------------ #
# Retrieval prefix (BGE-specific)
# ------------------------------------------------------------------ #
# Used only when embedding queries, NOT when embedding documents.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


# ------------------------------------------------------------------ #
# Model singleton
# ------------------------------------------------------------------ #
@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """
    Load the BGE model exactly once and cache it.

    lru_cache(maxsize=1) ensures that even if _get_model() is called from
    multiple coroutines at startup, only one model instance is ever created.
    The model is downloaded on first call and cached locally by HuggingFace
    (usually at ~/.cache/huggingface/hub/).
    """
    print(f"Loading embedding model: {settings.EMBEDDING_MODEL} …")
    model = SentenceTransformer(settings.EMBEDDING_MODEL)
    print(f"Embedding model loaded. Output dimension: {model.get_sentence_embedding_dimension()}")
    return model


# ------------------------------------------------------------------ #
# Public helpers
# ------------------------------------------------------------------ #
def embed_documents(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of document strings (no prefix added).

    Used by embed_notes.py when indexing case notes into the DB.

    Args:
        texts: List of raw note texts to embed.

    Returns:
        List of 1024-dimensional float vectors (one per input text).
    """
    model = _get_model()
    # normalize_embeddings=True makes cosine similarity equivalent to dot product,
    # which matches how pgvector's <=> operator works.
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def embed_query(query: str) -> list[float]:
    """
    Embed a single user query string WITH the BGE retrieval prefix.

    Used at chat time to embed the user's question before running the
    pgvector similarity search.

    Args:
        query: The raw question string typed by the user.

    Returns:
        A 1024-dimensional float vector.
    """
    model = _get_model()
    prefixed = BGE_QUERY_PREFIX + query
    vector = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
    return vector.tolist()
