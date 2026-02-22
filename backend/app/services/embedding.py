"""
embedding.py — Embeddings via HuggingFace Inference API (BAAI/bge-large-en-v1.5).

WHY HF INFERENCE API INSTEAD OF LOCAL?
  Running bge-large-en-v1.5 locally requires ~1.5 GB RAM.  Hosted environments
  (Render free tier, Railway hobby) cap at 512 MB, causing OOM crashes.
  Calling HuggingFace's hosted Inference API offloads the model to HF's servers —
  zero local RAM cost, same model, same 1024-dim vectors, same quality.

KEY BGE QUIRK — RETRIEVAL PREFIX:
  BGE models are trained with two modes:
    • Indexing documents  → embed the raw text as-is.
    • Querying            → prepend the string
        "Represent this sentence for searching relevant passages: "
      to the query before embedding.
  This module handles the prefix automatically so callers don't need to worry.

HF FREE TIER NOTES:
  - Rate limited but fine for POC usage.
  - The model may be "cold" after inactivity; the API returns HTTP 503 with
    {"error": "Model is currently loading"} in that case.  We retry with
    exponential back-off (up to 3 attempts, 20s wait) to handle cold starts.

USED BY:
  • embed_notes.py (indexing)  — calls embed_documents()
  • vector_search.py (runtime) — calls embed_query()
"""

import time

import httpx

from app.core.config import settings

# ------------------------------------------------------------------ #
# BGE retrieval prefix
# ------------------------------------------------------------------ #
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# ------------------------------------------------------------------ #
# HF Inference API endpoint
# ------------------------------------------------------------------ #
_HF_API_URL = (
    f"https://router.huggingface.co/hf-inference/models/{settings.EMBEDDING_MODEL}/pipeline/feature-extraction"
)


# ------------------------------------------------------------------ #
# Internal helper
# ------------------------------------------------------------------ #
def _call_hf_api(texts: list[str]) -> list[list[float]]:
    """
    POST texts to the HF Inference API and return a list of embeddings.

    Retries up to 3 times if the model is cold (HTTP 503 + loading message).
    Each retry waits 20 seconds to let HF warm the model up.

    Args:
        texts: One or more strings to embed.

    Returns:
        List of 1024-dim float vectors, one per input string.

    Raises:
        httpx.HTTPStatusError: On non-retryable HTTP errors.
        RuntimeError: If the model is still loading after all retries.
    """
    headers = {"Authorization": f"Bearer {settings.HF_TOKEN}"}

    for attempt in range(3):
        response = httpx.post(
            _HF_API_URL,
            headers=headers,
            json={"inputs": texts},
            timeout=60.0,   # generous timeout — cold HF models can be slow
        )

        # HF returns 503 while the model warms up; wait and retry
        if response.status_code == 503:
            error_body = response.json()
            if "loading" in str(error_body).lower():
                wait = error_body.get("estimated_time", 20)
                print(f"HF model loading, waiting {wait}s (attempt {attempt + 1}/3)…")
                time.sleep(wait)
                continue

        response.raise_for_status()
        result = response.json()

        # HF feature-extraction can return shape [batch, dims] or [batch, tokens, dims].
        # For sentence-level embeddings we want [batch, dims].
        # If we get a 3-D response, take the first token (CLS) vector.
        if result and isinstance(result[0][0], list):
            result = [item[0] for item in result]

        return result

    raise RuntimeError("HF model still loading after 3 retries — try again in a moment.")


# ------------------------------------------------------------------ #
# Public helpers (same interface as the old local-model version)
# ------------------------------------------------------------------ #
def embed_documents(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of document strings (no prefix added).

    Used by embed_notes.py when indexing case notes into the DB.

    Args:
        texts: List of raw note chunk texts to embed.

    Returns:
        List of 1024-dimensional float vectors, one per input.
    """
    return _call_hf_api(texts)


def embed_query(query: str) -> list[float]:
    """
    Embed a single user query WITH the BGE retrieval prefix.

    Used at chat time to embed the user's question before the
    pgvector similarity search.

    Args:
        query: The raw question string typed by the user.

    Returns:
        A 1024-dimensional float vector.
    """
    return _call_hf_api([BGE_QUERY_PREFIX + query])[0]
