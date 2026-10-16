"""Pluggable vector storage.

- `PgVectorStore`: production backend, cosine similarity via pgvector.
- `InMemoryVectorStore`: zero-dependency fallback for local dev / tests.

Select with the VECTOR_BACKEND env var. Both are scoped per-user: every
search is filtered by owner_id (tenant isolation at the storage layer).
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class ScoredChunk:
    chunk_id: int
    document_id: int
    filename: str
    content: str
    score: float  # cosine similarity, 0..1 (or fused score for hybrid)
    modality: str = "text"  # text | image | audio | video
    page_number: int | None = None


# Chunk payload for upsert: (chunk_index, content, token_count, embedding,
#                            modality, page_number, timestamp_ms).
# The last three default when a 4-tuple is passed (backward compatible).
ChunkPayload = tuple[int, str, int, list[float], str, int | None, int | None]


def _normalize_payload(
    chunks: list[tuple],
) -> list[tuple[int, str, int, list[float], str, int | None, int | None]]:
    out = []
    for c in chunks:
        if len(c) == 4:
            idx, content, tokens, vector = c
            out.append((idx, content, tokens, vector, "text", None, None))
        else:
            out.append(c)
    return out


class VectorStore(Protocol):
    def upsert_chunks(
        self,
        db: Session,
        owner_id: int,
        document_id: int,
        chunks: list[tuple[int, str, int, list[float]]],
    ) -> None:
        """Persist (chunk_index, content, token_count, embedding) tuples."""
        ...

    def search(
        self, db: Session, owner_id: int, query_vector: list[float], top_k: int
    ) -> list[ScoredChunk]: ...

    def delete_document(self, db: Session, owner_id: int, document_id: int) -> None: ...

    def iter_chunks(
        self, db: Session, owner_id: int
    ) -> list[tuple[int, int, str, str]]:
        """All chunks for an owner: (chunk_id, document_id, filename, content).

        Used by the hybrid BM25 sidecar. Keep it lazy/streaming at scale.
        """
        ...


class PgVectorStore:
    """Production store using the pgvector extension."""

    def upsert_chunks(self, db, owner_id, document_id, chunks) -> None:
        from app.models.document import DocumentChunk

        rows = [
            DocumentChunk(
                document_id=document_id,
                owner_id=owner_id,
                chunk_index=idx,
                content=content,
                token_count=tokens,
                embedding=vector,
                modality=modality,
                page_number=page_number,
                timestamp_ms=timestamp_ms,
            )
            for idx, content, tokens, vector, modality, page_number, timestamp_ms
            in _normalize_payload(chunks)
        ]
        db.add_all(rows)
        db.flush()

    def search(self, db: Session, owner_id: int, query_vector: list[float], top_k: int) -> list[ScoredChunk]:
        # <=> is pgvector's cosine-distance operator; 1 - distance = similarity.
        # IVFFlat index recommended at scale (see migration + README).
        rows = db.execute(
            text(
                """
                SELECT c.id, c.document_id, d.filename, c.content,
                       1 - (c.embedding <=> CAST(:qv AS vector)) AS score
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.owner_id = :owner_id
                ORDER BY c.embedding <=> CAST(:qv AS vector)
                LIMIT :top_k
                """
            ),
            {"qv": str(query_vector), "owner_id": owner_id, "top_k": top_k},
        ).all()
        return [
            ScoredChunk(
                chunk_id=r[0], document_id=r[1], filename=r[2],
                content=r[3], score=float(r[4]),
            )
            for r in rows
        ]

    def delete_document(self, db: Session, owner_id: int, document_id: int) -> None:
        from app.models.document import DocumentChunk

        db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document_id,
            DocumentChunk.owner_id == owner_id,
        ).delete()

    def iter_chunks(
        self, db: Session, owner_id: int
    ) -> list[tuple[int, int, str, str]]:
        from app.models.document import Document, DocumentChunk

        rows = (
            db.query(
                DocumentChunk.id,
                DocumentChunk.document_id,
                Document.filename,
                DocumentChunk.content,
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(DocumentChunk.owner_id == owner_id)
            .all()
        )
        return [(r[0], r[1], r[2], r[3]) for r in rows]


class InMemoryVectorStore:
    """Dev/test fallback. Pure Python cosine search; NOT for production."""

    def __init__(self) -> None:
        # (owner_id, document_id) -> list of dicts
        self._docs: dict[tuple[int, int], list[dict]] = {}
        self._filenames: dict[tuple[int, int], str] = {}
        self._next_id = 1  # globally unique chunk ids (matches pgvector row ids)

    def upsert_chunks(self, db, owner_id, document_id, chunks) -> None:
        from app.models.document import Document  # only for the filename lookup

        doc = db.get(Document, document_id)
        key = (owner_id, document_id)
        self._filenames[key] = doc.filename if doc else f"doc-{document_id}"
        items = []
        for idx, content, _tokens, vector, modality, page_number, _ts in _normalize_payload(
            chunks
        ):
            items.append(
                {
                    "chunk_id": self._next_id,
                    "chunk_index": idx,
                    "content": content,
                    "vector": vector,
                    "modality": modality,
                    "page_number": page_number,
                }
            )
            self._next_id += 1
        self._docs[key] = items

    def search(self, db, owner_id, query_vector, top_k) -> list[ScoredChunk]:
        scored: list[ScoredChunk] = []
        for (oid, did), chunks in self._docs.items():
            if oid != owner_id:
                continue
            for ch in chunks:
                scored.append(
                    ScoredChunk(
                        chunk_id=ch["chunk_id"],
                        document_id=did,
                        filename=self._filenames.get((oid, did), ""),
                        content=ch["content"],
                        score=_cosine(query_vector, ch["vector"]),
                        modality=ch.get("modality", "text"),
                        page_number=ch.get("page_number"),
                    )
                )
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]

    def iter_chunks(
        self, db, owner_id: int
    ) -> list[tuple[int, int, str, str]]:
        out: list[tuple[int, int, str, str]] = []
        for (oid, did), chunks in self._docs.items():
            if oid != owner_id:
                continue
            for ch in chunks:
                out.append(
                    (ch["chunk_id"], did, self._filenames.get((oid, did), ""), ch["content"])
                )
        return out

    def delete_document(self, db, owner_id, document_id) -> None:
        self._docs.pop((owner_id, document_id), None)
        self._filenames.pop((owner_id, document_id), None)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@lru_cache
def get_vector_store() -> VectorStore:
    """Singleton per backend. The memory backend MUST be shared between the
    ingestion background task and chat requests in the same process."""
    backend = get_settings().vector_backend.lower()
    if backend == "pgvector":
        return PgVectorStore()
    if backend == "memory":
        log.warning("using_inmemory_vector_store_not_for_production")
        return InMemoryVectorStore()
    raise ValueError(f"Unknown VECTOR_BACKEND: {backend}")
