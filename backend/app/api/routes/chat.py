"""
chat.py — POST /api/chat

This is the core RAG endpoint.  A single request goes through the full
Retrieval-Augmented Generation pipeline:

  User question
    → embed query (BGE model, local)
    → pgvector similarity search (filtered by case + date window)
    → assemble prompt with retrieved notes + conversation history
    → Gemini 2.5 Flash generates answer
    → persist user message + assistant message to DB
    → return answer + source note metadata

FLOW IN DETAIL:
  1. Validate request body (session_id + message).
  2. Load the ChatSession to get case_id, start_date, end_date.
  3. Load existing ChatMessages for this session (provides conversation history).
  4. Call embedding.embed_query() → 1024-dim float list.
  5. Call vector_search.find_similar_chunks() → top-6 note chunks.
  6. Call llm.generate_answer() → string answer from Gemini.
  7. Persist user message and assistant message to chat_messages table.
  8. Return {answer, sources}.

ERROR HANDLING:
  - 404 if session_id doesn't exist.
  - 422 if request body is malformed (FastAPI / Pydantic handles this automatically).
  - 500 propagated if Gemini API call fails (let the client retry).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.tables import ChatMessage, ChatSession
from app.services import embedding, vector_search, llm

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ------------------------------------------------------------------ #
# Request / response schemas
# ------------------------------------------------------------------ #
class ChatRequest(BaseModel):
    """
    Body for POST /api/chat.

    session_id – UUID returned by POST /api/sessions.
    message    – The user's question (plain text).
    """
    session_id: uuid.UUID
    message:    str


# ------------------------------------------------------------------ #
# Route
# ------------------------------------------------------------------ #
@router.post("/")
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Run one full RAG turn and return the assistant's answer.

    Response shape:
    {
      "answer": "...",
      "sources": [
        {
          "id":              "<note-uuid>",
          "created_at":      "2024-03-15T14:00:00+00:00",
          "note_type":       "in-person",
          "caseworker_name": "Maria Santos",
          "snippet":         "First 200 chars of the note…",
          "similarity":      0.87
        },
        ...
      ]
    }
    """

    # ---- Step 1: Load session (includes its date window) ----------- #
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == body.session_id)
        .options(selectinload(ChatSession.messages))  # eager-load existing messages
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # ---- Step 2: Embed the user's question ------------------------- #
    # This runs locally (no external API call).
    # embed_query() prepends the BGE retrieval prefix automatically.
    query_vector = embedding.embed_query(body.message)

    # ---- Step 3: Vector similarity search in pgvector -------------- #
    # Searches note_chunks (not case_notes directly) because each note has
    # been split into ~1 200-char overlapping chunks — one embedding per chunk.
    # Returns up to settings.TOP_K chunks ordered by cosine similarity.
    similar_notes = await vector_search.find_similar_chunks(
        db=db,
        case_id=session.case_id,
        start_date=session.start_date,
        end_date=session.end_date,
        query_vector=query_vector,
    )

    # ---- Step 4: Build conversation history for the LLM ------------ #
    # Pass messages as simple dicts.  The current user message is NOT
    # included here — it is passed as user_question to generate_answer().
    prior_messages = [
        {"role": m.role, "content": m.content}
        for m in session.messages   # already ordered by created_at
    ]

    # ---- Step 5: Call Gemini 2.5 Flash ----------------------------- #
    answer_text = await llm.generate_answer(
        user_question=body.message,
        retrieved_notes=similar_notes,
        prior_messages=prior_messages,
    )

    # ---- Step 6: Persist both turns to the database ---------------- #
    user_msg = ChatMessage(
        session_id=body.session_id,
        role="user",
        content=body.message,
    )
    assistant_msg = ChatMessage(
        session_id=body.session_id,
        role="assistant",
        content=answer_text,
    )
    db.add(user_msg)
    db.add(assistant_msg)
    # get_db() commits on clean exit — no explicit commit needed here

    # ---- Step 7: Build sources list for the frontend --------------- #
    # Each result is a note_chunk (~1 200 chars max) — we show the first 300
    # chars as a preview snippet in the collapsible source card.
    # chunk_index tells the user which part of a long note was retrieved.
    sources = [
        {
            "id":              chunk["chunk_id"],
            "note_id":         chunk["note_id"],
            "chunk_index":     chunk["chunk_index"],
            "created_at":      chunk["created_at"].isoformat(),
            "note_type":       chunk.get("note_type"),
            "caseworker_name": chunk.get("caseworker_name"),
            "snippet":         chunk["chunk_text"][:300] + ("…" if len(chunk["chunk_text"]) > 300 else ""),
            "similarity":      round(chunk["similarity"], 4),
        }
        for chunk in similar_notes
    ]

    return {"answer": answer_text, "sources": sources}
