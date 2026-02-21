"""
embed_notes.py — Chunk all case notes and embed each chunk into note_chunks.

WHAT THIS SCRIPT DOES:
  1. Fetches every case_notes row that has NO corresponding rows in note_chunks
     yet (so the script is safe to re-run — it skips already-chunked notes).
  2. For each note, calls chunk_text() to split the text into overlapping
     ~1 200-character chunks with smart sentence-level overlap.
  3. Inserts each chunk as a row in note_chunks (with denormalised metadata).
  4. Collects chunks into batches of 16 and embeds them with bge-large-en-v1.5.
  5. UPDATEs each note_chunks row with its embedding vector.

WHY CHUNK FIRST, EMBED SECOND (two passes)?
  We insert all chunks for a note before embedding any of them.  This way, if
  the embedding step crashes halfway through a batch, we can resume by looking
  for note_chunks rows where embedding IS NULL — we don't lose which notes have
  already been chunked.

HOW TO RUN (after seed_data.py):
  cd backend
  source .venv/bin/activate
  python scripts/embed_notes.py

RE-RUNNING:
  Safe to re-run at any time:
  - Notes already in note_chunks are skipped (idempotent chunk insertion).
  - Chunks with embedding IS NULL are (re-)embedded.
  To fully redo everything:
    DELETE FROM note_chunks;
  then re-run this script.
"""

import os
import sys
import uuid

# ------------------------------------------------------------------ #
# Path setup — must happen before any local imports
# ------------------------------------------------------------------ #
_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _BACKEND_DIR)

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

_raw_url = os.environ["DATABASE_URL"]
SYNC_DATABASE_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://")

# Local imports after sys.path is configured
from app.services.chunking import chunk_text          # sentence-aware chunker
from app.services.embedding import embed_documents    # bge-large-en-v1.5

# ------------------------------------------------------------------ #
# Tuning
# ------------------------------------------------------------------ #
EMBED_BATCH_SIZE = 16   # bge-large is memory-heavy; keep batches small


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #
def main():
    print("Connecting to database…")
    conn = psycopg2.connect(SYNC_DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    # ---- 1. Find notes that have not been chunked yet -------------- #
    # We identify "unchunked" notes by LEFT JOIN — if no note_chunks row
    # exists for a note_id, that note still needs to be processed.
    cur.execute("""
        SELECT
            cn.id,
            cn.case_id,
            cn.note_text,
            cn.caseworker_name,
            cn.note_type,
            cn.created_at
        FROM case_notes cn
        LEFT JOIN note_chunks nc ON nc.note_id = cn.id
        WHERE nc.id IS NULL
        ORDER BY cn.created_at;
    """)
    pending_notes = cur.fetchall()  # list of (id, case_id, text, cw, type, ts)

    if not pending_notes:
        print("All notes already chunked. Checking for un-embedded chunks…")
    else:
        print(f"Notes to chunk: {len(pending_notes)}")

    # ---- 2. Chunk each pending note and insert rows ---------------- #
    total_chunks_inserted = 0

    for note_row in pending_notes:
        note_id, case_id, note_text, caseworker_name, note_type, created_at = note_row

        # chunk_text() returns a list of strings.
        # For a short note this will be a single-element list.
        chunks = chunk_text(note_text)

        for idx, chunk in enumerate(chunks):
            chunk_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO note_chunks
                    (id, note_id, case_id, chunk_index, chunk_text,
                     created_at, caseworker_name, note_type)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    chunk_id,
                    str(note_id),
                    str(case_id),
                    idx,
                    chunk,
                    created_at,    # denormalised timestamp from parent note
                    caseworker_name,
                    note_type,
                ),
            )
            total_chunks_inserted += 1

        conn.commit()

    print(f"Chunks inserted this run: {total_chunks_inserted}")

    # ---- 3. Embed all chunks that still have embedding IS NULL ----- #
    cur.execute("""
        SELECT id, chunk_text
        FROM note_chunks
        WHERE embedding IS NULL
        ORDER BY created_at, chunk_index;
    """)
    pending_chunks = cur.fetchall()  # list of (chunk_id, chunk_text)

    if not pending_chunks:
        print("All chunks already embedded. Nothing more to do.")
        cur.close()
        conn.close()
        return

    print(f"Chunks to embed: {len(pending_chunks)}")

    # ---- 4. Embed in batches of EMBED_BATCH_SIZE ------------------- #
    # embed_documents() accepts raw text — no BGE query prefix needed here
    # because we are indexing documents, not querying.
    embedded = 0
    for batch_start in range(0, len(pending_chunks), EMBED_BATCH_SIZE):
        batch       = pending_chunks[batch_start : batch_start + EMBED_BATCH_SIZE]
        chunk_ids   = [str(r[0]) for r in batch]
        chunk_texts = [r[1]      for r in batch]

        batch_num = batch_start // EMBED_BATCH_SIZE + 1
        total_batches = (len(pending_chunks) + EMBED_BATCH_SIZE - 1) // EMBED_BATCH_SIZE
        print(
            f"  Embedding batch {batch_num}/{total_batches} "
            f"({len(batch)} chunks) …",
            end=" ",
            flush=True,
        )

        # Returns list of list[float], one vector per chunk text
        vectors = embed_documents(chunk_texts)

        # Write each vector into the corresponding note_chunks row.
        # We cast the Python list to a Postgres VECTOR literal using ::vector.
        for chunk_id, vector in zip(chunk_ids, vectors):
            cur.execute(
                "UPDATE note_chunks SET embedding = %s::vector WHERE id = %s::uuid;",
                (str(vector), chunk_id),
            )

        conn.commit()
        embedded += len(batch)
        print(f"done. ({embedded}/{len(pending_chunks)})")

    cur.close()
    conn.close()
    print(f"\nAll done. {embedded} chunk(s) embedded across the note_chunks table.")


if __name__ == "__main__":
    main()
