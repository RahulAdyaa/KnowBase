"""Document + chunk models.

Embeddings live in `document_chunks.embedding` as a pgvector column.
The pgvector import is lazy so unit tests (sqlite) can import this module
without the pgvector package installed - DDL for chunks is only created
against Postgres.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), default=DocumentStatus.PENDING, nullable=False, index=True
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    owner: Mapped["User"] = relationship("User", back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )


def _embedding_type():
    """pgvector Vector on Postgres; harmless fallback when pgvector isn't installed.

    Unit tests (sqlite) never create this table - the fallback only needs to
    exist so the module imports cleanly.
    """
    try:
        from pgvector.sqlalchemy import Vector

        return Vector(1536)  # DDL dimension is set properly in the Alembic migration
    except ImportError:  # pragma: no cover - test/dev fallback
        from sqlalchemy import LargeBinary

        return LargeBinary()


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Populated at runtime from settings.embedding_dimensions (see migration).
    embedding = mapped_column("embedding", _embedding_type())
    # Multimodal metadata: 'text' | 'image' | 'audio' | 'video'.
    modality: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    # Source location inside the original file (PDF page, slide #, ...).
    page_number: Mapped[int] = mapped_column(Integer, nullable=True)
    # Milliseconds into audio/video for transcribed segments.
    timestamp_ms: Mapped[int] = mapped_column(Integer, nullable=True)

    document: Mapped[Document] = relationship("Document", back_populates="chunks")
