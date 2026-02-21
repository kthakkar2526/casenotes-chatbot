"""
vector_search.py — pgvector cosine similarity search on note_chunks.

HOW THE RAG RETRIEVAL WORKS:
  1. The user's question is embedded into a 1024-dim vector (by embedding.py,
     with the BGE retrieval prefix prepended).
  2. We query note_chunks using pgvector's <=> (cosine distance) operator.
  3. We filter by:
       case_id   — only chunks belonging to the selected case
       created_at — only chunks whose parent note falls within the 6-month window
       embedding IS NOT NULL — skip un-embedded chunks (shouldn't happen in prod)
  4. We return the TOP_K most similar chunks, ordered by similarity descending.

NO JOIN NEEDED:
  case_id, created_at, caseworker_name, and note_type are denormalised onto
  note_chunks by embed_notes.py, so this query touches only one table.

WHY COSINE DISTANCE (<=>)?
  bge-large-en-v1.5 is encoded with normalize_embeddings=True, so all vectors
  have unit length.  For unit vectors cosine distance and dot-product distance
  produce identical rankings.  We use <=> (cosine) to match the ivfflat index
  created with vector_cosine_ops.
"""

import uuid
from datetime import date, datetime, time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


async def find_similar_chunks(
    db: AsyncSession,
    case_id: uuid.UUID,
    start_date: date,
    end_date: date,
    query_vector: list[float],
) -> list[dict]:
    """
    Retrieve the TOP_K note chunks most semantically similar to `query_vector`
    within the given case and date window.

    Args:
        db:           Active async SQLAlchemy session (injected by FastAPI).
        case_id:      UUID of the case to restrict results to.
        start_date:   Start of the user's 6-month window (inclusive).
        end_date:     End of the user's 6-month window (inclusive).
        query_vector: 1024-dim float list produced by embedding.embed_query().

    Returns:
        List of dicts, each containing:
            chunk_id        – note_chunk UUID (str)
            note_id         – parent CaseNote UUID (str); useful for deduplication
            chunk_index     – 0-based position of the chunk within the note
            chunk_text      – the actual chunk text (sent to the LLM as context)
            created_at      – datetime of the parent note (for display in UI)
            note_type       – contact method ('in-person', 'virtual', etc.)
            caseworker_name – who wrote the note
            similarity      – float in [0, 1]; higher = more similar
    """

    # Build a Postgres VECTOR literal from the Python list.
    # pgvector recognises the "[x, y, z, …]" string format when cast with ::vector.
    vector_literal = "[" + ",".join(str(x) for x in query_vector) + "]"

    # Raw SQL because SQLAlchemy's ORM has no native pgvector operator support.
    # `1 - (embedding <=> query)` converts cosine *distance* to *similarity*.
    sql = text("""
        SELECT
            id::text            AS chunk_id,
            note_id::text       AS note_id,
            chunk_index,
            chunk_text,
            created_at,
            note_type,
            caseworker_name,
            1 - (embedding <=> (:query_vec)::vector) AS similarity
        FROM note_chunks
        WHERE
            case_id    = (:case_id)::uuid
            AND created_at >= :start_date
            AND created_at <= :end_date
            AND embedding IS NOT NULL
        ORDER BY embedding <=> (:query_vec)::vector
        LIMIT :top_k;
    """)

    result = await db.execute(
        sql,
        {
            "query_vec":  vector_literal,
            "case_id":    str(case_id),
            "start_date": start_date,
            # Use end-of-day datetime so notes created ON end_date are included.
            # Must be a real datetime object — asyncpg rejects plain strings.
            "end_date":   datetime.combine(end_date, time(23, 59, 59)),
            "top_k":      settings.TOP_K,
        },
    )

    rows = result.fetchall()

    return [
        {
            "chunk_id":        row.chunk_id,
            "note_id":         row.note_id,
            "chunk_index":     row.chunk_index,
            "chunk_text":      row.chunk_text,
            "created_at":      row.created_at,
            "note_type":       row.note_type,
            "caseworker_name": row.caseworker_name,
            "similarity":      float(row.similarity),
        }
        for row in rows
    ]
