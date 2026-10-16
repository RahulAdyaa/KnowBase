"""RAG orchestration: ingestion pipeline + retrieval + grounded answering.

Ingestion:  extract text -> chunk -> embed -> store (background task).
Query:      embed question -> vector search -> rerank (stub) -> LLM with citations.

The reranker is intentionally a stub: in production plug in Cohere Rerank,
a cross-encoder, or RankGPT behind the `rerank()` function signature.
"""

from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.document import Document, DocumentStatus
from app.schemas.chat import Citation
from app.services.chunking import chunk_text
from app.services.embeddings import EmbeddingProvider
from app.services.hybrid import hybrid_retrieve
from app.services.llm import LLMClient
from app.services.reranking import rerank
from app.services.vectorstore import ScoredChunk, VectorStore

log = get_logger(__name__)

SYSTEM_PROMPT = """You answer questions using ONLY the provided context excerpts.
Rules:
- If the answer is not in the context, say you don't know - do not invent facts.
- Cite sources inline like [1], [2] matching the excerpt numbers.
- Be concise and directly answer the question."""


def extract_text(filename: str, content_type: str, raw: bytes) -> str:
    """Legacy single-text extractor. Prefer extract_segments() for new code."""
    from app.services.extractors import extract_segments

    segments = extract_segments(filename, content_type, raw)
    return "\n\n".join(s.text for s in segments)


def ingest_document(
    db: Session,
    document_id: int,
    raw: bytes,
    embedder: EmbeddingProvider,
    store: VectorStore,
) -> None:
    """Run the ingestion pipeline. Designed to run in a FastAPI BackgroundTask."""
    settings = get_settings()
    doc = db.get(Document, document_id)
    if doc is None:
        log.error("ingest_document_missing", extra={"document_id": document_id})
        return
    try:
        doc.status = DocumentStatus.PROCESSING
        db.commit()

        from app.services.extractors import extract_segments

        segments = extract_segments(doc.filename, doc.content_type, raw)
        payload: list[tuple] = []
        chunk_idx = 0
        for seg in segments:
            seg_chunks = chunk_text(seg.text, settings.rag_chunk_size, settings.rag_chunk_overlap)
            if not seg_chunks:
                continue
            vectors = embedder.embed_texts([c.content for c in seg_chunks])
            for c, v in zip(seg_chunks, vectors):
                payload.append(
                    (chunk_idx, c.content, c.token_count, v, seg.modality, seg.page_number, seg.timestamp_ms)
                )
                chunk_idx += 1
        if not payload:
            raise ValueError("No text could be extracted from the file")
        store.upsert_chunks(db, doc.owner_id, doc.id, payload)

        doc.chunk_count = len(payload)
        doc.status = DocumentStatus.READY
        db.commit()
        log.info("document_ingested", extra={"document_id": doc.id, "chunks": len(payload)})
    except Exception as exc:
        db.rollback()
        doc = db.get(Document, document_id)
        if doc:
            doc.status = DocumentStatus.FAILED
            doc.error = str(exc)[:1000]
            db.commit()
        log.error("document_ingest_failed", extra={"document_id": document_id, "err": str(exc)})


def build_citations(chunks: list[ScoredChunk]) -> list[Citation]:
    return [
        Citation(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            filename=c.filename,
            score=round(c.score, 4),
            snippet=c.content[:300],
            modality=c.modality,
            page_number=c.page_number,
        )
        for c in chunks
    ]


def retrieve(
    db: Session,
    owner_id: int,
    query: str,
    embedder: EmbeddingProvider,
    store: VectorStore,
    top_k: int | None = None,
) -> list[ScoredChunk]:
    settings = get_settings()
    k = top_k or settings.rag_top_k
    if settings.hybrid_retrieval:
        # Hybrid: dense + BM25 fused with RRF, over-fetch for the reranker.
        candidates = hybrid_retrieve(db, owner_id, query, embedder, store, top_k=k)
    else:
        query_vector = embedder.embed_query(query)
        # Over-fetch, then rerank down to k.
        candidates = store.search(db, owner_id, query_vector, top_k=k * 3)
    candidates = [c for c in candidates if c.score >= settings.rag_min_score]
    return rerank(query, candidates, k)


def build_prompt(question: str, chunks: list[ScoredChunk]) -> str:
    context = "\n\n".join(
        f"[{i + 1}] (from {c.filename})\n{c.content}" for i, c in enumerate(chunks)
    )
    return f"Context excerpts:\n{context}\n\nQuestion: {question}\nAnswer:"


async def stream_answer(
    question: str, chunks: list[ScoredChunk], llm: LLMClient
) -> AsyncIterator[str]:
    """Yield answer tokens. Citations are sent by the route before/after."""
    if not chunks:
        yield "I don't have any documents that cover this yet. Upload a document first and I'll answer from it."
        return
    prompt = build_prompt(question, chunks)
    async for token in llm.stream_chat(SYSTEM_PROMPT, prompt):
        yield token
