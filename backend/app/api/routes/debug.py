"""
debug.py — Debug endpoints for inspecting the chunking output.

These endpoints are NOT part of the production API — they exist purely to
let you see what the chunking + embedding pipeline produced so you can
verify the output is correct before demoing.

ENDPOINTS:
  GET /api/debug/cases/{case_number}/chunks
    Returns every chunk created for a given case, grouped by note.
    Shows chunk_index, character count, first 200 chars, and whether
    the overlap from the previous chunk is visible at the start.

  GET /api/debug/cases/{case_number}/chunks/{note_id}
    Returns ALL chunks for a single note with full text, so you can
    read the overlap sentences directly.
"""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db
from app.models.tables import Case

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/cases/{case_number}/chunks")
async def list_chunks_for_case(
    case_number: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Show all chunks for a case, grouped by note.

    Response shows:
      - How many notes the case has
      - How many chunks each note produced
      - The first 200 chars of each chunk (so you can see overlap at chunk start)
      - Char count of each chunk
      - Whether it is embedded yet

    FLOW:
      1. Look up the case by case_number.
      2. Query note_chunks joined to case_notes ordered by created_at, chunk_index.
      3. Group into a nested structure: note → [chunks].
    """
    # 1. Find the case
    result = await db.execute(
        select(Case).where(Case.case_number == case_number)
    )
    case = result.scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case '{case_number}' not found")

    # 2. Fetch all chunks for this case, with parent note metadata
    rows = await db.execute(
        text("""
            SELECT
                cn.id::text          AS note_id,
                cn.created_at        AS note_date,
                cn.note_type,
                cn.caseworker_name,
                length(cn.note_text) AS note_total_chars,
                nc.id::text          AS chunk_id,
                nc.chunk_index,
                length(nc.chunk_text) AS chunk_chars,
                left(nc.chunk_text, 200) AS chunk_preview,
                (nc.embedding IS NOT NULL) AS is_embedded
            FROM case_notes cn
            JOIN note_chunks nc ON nc.note_id = cn.id
            WHERE cn.case_id = (:case_id)::uuid
            ORDER BY cn.created_at, nc.chunk_index;
        """),
        {"case_id": str(case.id)},
    )
    all_rows = rows.fetchall()

    if not all_rows:
        return {
            "case_number": case_number,
            "client_name": case.client_name,
            "message": "No chunks found. Run embed_notes.py first.",
        }

    # 3. Group by note_id to build a nested response
    notes: dict = {}
    for row in all_rows:
        nid = row.note_id
        if nid not in notes:
            notes[nid] = {
                "note_id":         nid,
                "note_date":       row.note_date.strftime("%Y-%m-%d"),
                "note_type":       row.note_type,
                "caseworker_name": row.caseworker_name,
                "note_total_chars": row.note_total_chars,
                "chunk_count":     0,
                "chunks":          [],
            }
        notes[nid]["chunk_count"] += 1
        notes[nid]["chunks"].append({
            "chunk_id":     row.chunk_id,
            "chunk_index":  row.chunk_index,
            "chunk_chars":  row.chunk_chars,
            # Preview shows the first 200 chars so you can see overlap at the start
            "preview":      row.chunk_preview + ("…" if row.chunk_chars > 200 else ""),
            "is_embedded":  row.is_embedded,
        })

    return {
        "case_number": case_number,
        "client_name": case.client_name,
        "total_notes": len(notes),
        "total_chunks": len(all_rows),
        "notes": list(notes.values()),
    }


@router.get("/cases/{case_number}/chunks/{note_id}")
async def get_full_chunks_for_note(
    case_number: str,
    note_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Show the FULL text of every chunk for a single note.

    This is the most useful endpoint for verifying overlap correctness:
    you can read chunk N and chunk N+1 side by side and confirm that the
    last sentences of chunk N appear at the start of chunk N+1.

    FLOW:
      1. Verify the case exists.
      2. Fetch all chunks for the note, ordered by chunk_index.
      3. Return full chunk_text for each so you can read the overlap directly.
    """
    # Verify case exists
    result = await db.execute(
        select(Case).where(Case.case_number == case_number)
    )
    case = result.scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case '{case_number}' not found")

    # Fetch full chunk text for this note
    rows = await db.execute(
        text("""
            SELECT
                nc.id::text       AS chunk_id,
                nc.chunk_index,
                nc.chunk_text,
                length(nc.chunk_text) AS chunk_chars,
                (nc.embedding IS NOT NULL) AS is_embedded
            FROM note_chunks nc
            JOIN case_notes cn ON cn.id = nc.note_id
            WHERE
                nc.note_id = (:note_id)::uuid
                AND cn.case_id = (:case_id)::uuid
            ORDER BY nc.chunk_index;
        """),
        {"note_id": note_id, "case_id": str(case.id)},
    )
    all_chunks = rows.fetchall()

    if not all_chunks:
        raise HTTPException(
            status_code=404,
            detail=f"No chunks found for note {note_id}. Run embed_notes.py first.",
        )

    return {
        "note_id":     note_id,
        "case_number": case_number,
        "chunk_count": len(all_chunks),
        "chunks": [
            {
                "chunk_id":    r.chunk_id,
                "chunk_index": r.chunk_index,
                "chunk_chars": r.chunk_chars,
                "is_embedded": r.is_embedded,
                # Full text — compare the END of chunk N with START of chunk N+1
                # to visually confirm the overlap is working correctly
                "chunk_text":  r.chunk_text,
            }
            for r in all_chunks
        ],
    }
