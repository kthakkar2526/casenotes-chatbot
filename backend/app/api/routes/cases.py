"""
cases.py — GET /api/cases

Returns the list of all cases with their note date ranges, so the frontend
can render a timeline and constrain the date-window picker.

WHY JOIN TO case_notes?
  The frontend needs to know the earliest and latest note date for each case
  so it can:
    - Render a visual timeline bar
    - Constrain the start-date picker so the 6-month window always fits
    - Default the window to the last 6 months of the case
"""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from app.core.database import get_db
from app.models.tables import Case, CaseNote

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.get("/")
async def list_cases(db: AsyncSession = Depends(get_db)):
    """
    Return all cases sorted by case_number, each including the date span
    of its notes.

    Response shape:
      [
        {
          "id":             "<uuid>",
          "case_number":    "CW-2023-001",
          "client_name":    "Aaliyah Johnson",
          "min_note_date":  "2023-01-15",   # earliest note date
          "max_note_date":  "2024-07-20"    # latest note date
        },
        ...
      ]

    FLOW:
      1. LEFT JOIN cases → case_notes so cases with no notes still appear.
      2. GROUP BY case.id, aggregate MIN/MAX on created_at.
      3. Return as plain dicts — FastAPI auto-serialises to JSON.
    """
    result = await db.execute(
        select(
            Case.id,
            Case.case_number,
            Case.client_name,
            func.min(CaseNote.created_at).label("min_note_date"),
            func.max(CaseNote.created_at).label("max_note_date"),
        )
        .outerjoin(CaseNote, CaseNote.case_id == Case.id)
        .group_by(Case.id)
        .order_by(Case.case_number)
    )
    rows = result.all()

    return [
        {
            "id":            str(row.id),
            "case_number":   row.case_number,
            "client_name":   row.client_name,
            # .date() strips the time component; isoformat() → "YYYY-MM-DD"
            "min_note_date": row.min_note_date.date().isoformat() if row.min_note_date else None,
            "max_note_date": row.max_note_date.date().isoformat() if row.max_note_date else None,
        }
        for row in rows
    ]
