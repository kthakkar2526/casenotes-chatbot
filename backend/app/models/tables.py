"""
tables.py — SQLAlchemy ORM models that map to the Neon (Postgres) tables.

TABLE RELATIONSHIPS:
  cases ──< case_notes          (one case has many notes)
  case_notes ──< note_chunks    (one note is split into many searchable chunks)
  cases ──< chat_sessions       (one case can have many chat sessions)
  chat_sessions ──< chat_messages (one session has many messages)

WHY note_chunks INSTEAD OF embedding ON case_notes?
  A note can be up to 8 000 characters (~2 000 tokens), far exceeding
  bge-large-en-v1.5's 512-token context window.  Storing one embedding per
  note would silently truncate long notes.  Instead we split each note into
  ~1 200-character chunks (with smart sentence-level overlap) and store one
  embedding per chunk in note_chunks.  Vector search then finds the most
  relevant *chunk*, not the most relevant *note*.

DENORMALISATION IN note_chunks:
  case_id, created_at, caseworker_name, and note_type are copied from the
  parent CaseNote row into every NoteChunk row.  This lets the vector search
  query filter by case_id and date window WITHOUT a JOIN, which is important
  because that query runs on every chat message.

WHY UUID PKs?
  UUIDs are generated in the database (gen_random_uuid()), which avoids
  id collisions if we ever insert from multiple processes and makes URLs
  non-guessable.
"""

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    UUID,
    DATE,
    INTEGER,
    TEXT,
    VARCHAR,
    DateTime,
    ForeignKey,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Case(Base):
    """
    Represents a child welfare case.

    case_number  – human-readable identifier (e.g. "CW-2024-001")
    client_name  – name of the child / family the case belongs to
    """
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    case_number: Mapped[str] = mapped_column(VARCHAR(50), unique=True, nullable=False)
    client_name: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    notes: Mapped[list["CaseNote"]] = relationship(
        "CaseNote", back_populates="case", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession", back_populates="case", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Case {self.case_number} — {self.client_name}>"


class CaseNote(Base):
    """
    A single observation written by a caseworker.

    Stores the full original note text.  The text is NOT embedded directly
    here — instead embed_notes.py chunks it and stores each chunk with its
    embedding in the note_chunks table.

    created_at      – when the observation was recorded; used to filter by
                      the user's 6-month date window (stored on chunks too)
    """
    __tablename__ = "case_notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    note_text: Mapped[str] = mapped_column(TEXT, nullable=False)
    caseworker_name: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)
    note_type: Mapped[str | None] = mapped_column(VARCHAR(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    case: Mapped["Case"] = relationship("Case", back_populates="notes")
    chunks: Mapped[list["NoteChunk"]] = relationship(
        "NoteChunk", back_populates="note", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        snippet = self.note_text[:60].replace("\n", " ")
        return f"<CaseNote {self.id} [{self.created_at.date()}] \"{snippet}…\">"


class NoteChunk(Base):
    """
    One searchable chunk of a CaseNote.

    chunk_index     – 0-based position of this chunk within its parent note
                      (used to reconstruct note order when displaying sources)
    chunk_text      – the actual text of this chunk (~1 200 chars, sentence-
                      aligned, with overlap from the previous chunk prepended)
    embedding       – 1024-dim vector from bge-large-en-v1.5; NULL until
                      embed_notes.py has been run

    DENORMALISED FIELDS (copied from the parent CaseNote for JOIN-free search):
    case_id         – enables filtering to a specific case
    created_at      – enables the 6-month date-window filter
    caseworker_name – surfaced in the UI alongside the source snippet
    note_type       – surfaced in the UI alongside the source snippet
    """
    __tablename__ = "note_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_notes.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised — allows WHERE case_id = ? without joining case_notes
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(INTEGER, nullable=False)
    chunk_text: Mapped[str] = mapped_column(TEXT, nullable=False)

    # NULL until embed_notes.py fills it in
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024), nullable=True
    )

    # Denormalised from parent note — avoids JOIN in the hot search path
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    caseworker_name: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)
    note_type: Mapped[str | None] = mapped_column(VARCHAR(50), nullable=True)

    note: Mapped["CaseNote"] = relationship("CaseNote", back_populates="chunks")

    def __repr__(self) -> str:
        snippet = self.chunk_text[:60].replace("\n", " ")
        return f"<NoteChunk {self.note_id}[{self.chunk_index}] \"{snippet}…\">"


class ChatSession(Base):
    """
    One "conversation" tied to a specific case and date window.
    """
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(DATE, nullable=False)
    end_date: Mapped[date] = mapped_column(DATE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    case: Mapped["Case"] = relationship("Case", back_populates="sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan",
        order_by="ChatMessage.created_at"
    )

    def __repr__(self) -> str:
        return f"<ChatSession {self.id} case={self.case_id} {self.start_date}→{self.end_date}>"


class ChatMessage(Base):
    """
    A single turn in the conversation (either user or assistant).
    """
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(VARCHAR(10), nullable=False)  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(TEXT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:
        snippet = self.content[:60].replace("\n", " ")
        return f"<ChatMessage [{self.role}] \"{snippet}…\">"
