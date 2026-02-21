"""
sessions.py — POST /api/sessions  and  GET /api/sessions/{id}/messages

POST /api/sessions
  Creates a new chat session tied to a case and a 6-month date window.
  Returns the new session's UUID, which the frontend stores and passes
  with every subsequent chat message.

GET /api/sessions/{session_id}/messages
  Returns the full message history for a session (user + assistant turns),
  ordered by creation time.  Used to restore the chat view on page reload.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.tables import Case, ChatMessage, ChatSession

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ------------------------------------------------------------------ #
# Request / response schemas
# ------------------------------------------------------------------ #
class CreateSessionRequest(BaseModel):
    """
    Body for POST /api/sessions.

    case_id    – UUID of the case the user selected in the dropdown.
    start_date – Start of the 6-month window (YYYY-MM-DD string or date).
    end_date   – End of the 6-month window (YYYY-MM-DD string or date).
    """
    case_id:    uuid.UUID
    start_date: date
    end_date:   date

    @field_validator("end_date")
    @classmethod
    def end_must_be_after_start(cls, end_date, info):
        """Reject sessions where the end date is before or equal to the start."""
        start = info.data.get("start_date")
        if start and end_date <= start:
            raise ValueError("end_date must be after start_date")
        return end_date


# ------------------------------------------------------------------ #
# Routes
# ------------------------------------------------------------------ #
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new chat session.

    FLOW:
      1. Verify the referenced case exists (raises 404 if not).
      2. Insert a new ChatSession row.
      3. Return the session id plus the case details the frontend needs
         to display in the chat header.
    """
    # Confirm the case exists
    result = await db.execute(select(Case).where(Case.id == body.case_id))
    case = result.scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    session = ChatSession(
        case_id=body.case_id,
        start_date=body.start_date,
        end_date=body.end_date,
    )
    db.add(session)
    await db.flush()   # flush to get the server-generated UUID before commit

    return {
        "session_id":  str(session.id),
        "case_number": case.case_number,
        "client_name": case.client_name,
        "start_date":  str(body.start_date),
        "end_date":    str(body.end_date),
    }


@router.get("/{session_id}/messages")
async def get_messages(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Return all messages for a session, ordered chronologically.

    FLOW:
      1. Load the session (raises 404 if not found).
      2. Eagerly load its messages via selectinload to avoid N+1 queries.
      3. Return them as a list of {role, content, created_at} dicts.
    """
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.messages))
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return [
        {
            "id":         str(m.id),
            "role":       m.role,
            "content":    m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in session.messages
    ]
