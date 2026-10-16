"""Hybrid retrieval: dense (vector) + sparse (BM25) fused with RRF.

Pure-Python, dependency-free sparse side so hybrid works on every backend.
Production at scale should move the sparse index to tantivy/OpenSearch; the
fusion contract (rank lists -> RRF) stays the same.
"""

import math
import re
from collections import Counter

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.embeddings import EmbeddingProvider
from app.services.vectorstore import ScoredChunk, VectorStore

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class BM25Index:
    """Minimal BM25 (k1=1.5, b=0.75) over an in-memory corpus."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: dict[tuple[int, int], Counter] = {}  # (doc_id, chunk_id) -> tf
        self._lengths: dict[tuple[int, int], int] = {}
        self._df: Counter = Counter()

    def add(self, document_id: int, chunk_id: int, text: str) -> None:
        tokens = tokenize(text)
        key = (document_id, chunk_id)
        tf = Counter(tokens)
        self._docs[key] = tf
        self._lengths[key] = len(tokens)
        for tok in tf:
            self._df[tok] += 1

    def __len__(self) -> int:
        return len(self._docs)

    def search(self, query: str, top_k: int) -> list[tuple[tuple[int, int], float]]:
        """Return [((document_id, chunk_id), bm25_score)] sorted desc."""
        if not self._docs:
            return []
        qtf = Counter(tokenize(query))
        n = len(self._docs)
        avg_len = sum(self._lengths.values()) / n
        scored: list[tuple[tuple[int, int], float]] = []
        for key, tf in self._docs.items():
            score = 0.0
            doc_len = self._lengths[key]
            for tok, qf in qtf.items():
                df = self._df.get(tok, 0)
                if df == 0:
                    continue
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                f = tf.get(tok, 0)
                denom = f + self.k1 * (1 - self.b + self.b * doc_len / avg_len)
                score += idf * (f * (self.k1 + 1) / denom) * qf
            if score > 0:
                scored.append((key, score))
        scored.sort(key=lambda s: s[1], reverse=True)
        return scored[:top_k]


def rrf_fuse(
    rank_lists: list[list[tuple[int, int]]], k: int = 60
) -> list[tuple[tuple[int, int], float]]:
    """Reciprocal Rank Fusion over ranked key lists. Returns (key, rrf_score) desc."""
    fused: dict[tuple[int, int], float] = {}
    for ranked in rank_lists:
        for rank, key in enumerate(ranked, start=1):
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda kv: kv[1], reverse=True)


def build_bm25_index(
    db: Session, owner_id: int, store: VectorStore
) -> tuple[BM25Index, dict[tuple[int, int], ScoredChunk]]:
    """Build a BM25 index over all of an owner's chunks.

    Returns (index, key -> ScoredChunk shell with content for result building).
    NOTE: rebuilt per query in this scaffold; move to a persistent sparse index
    (tantivy/OpenSearch) at production scale.
    """
    index = BM25Index()
    shells: dict[tuple[int, int], ScoredChunk] = {}
    for chunk_id, document_id, filename, content in store.iter_chunks(db, owner_id):
        key = (document_id, chunk_id)
        index.add(document_id, chunk_id, content)
        shells[key] = ScoredChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            filename=filename,
            content=content,
            score=0.0,
        )
    return index, shells


def hybrid_retrieve(
    db: Session,
    owner_id: int,
    query: str,
    embedder: EmbeddingProvider,
    store: VectorStore,
    top_k: int | None = None,
) -> list[ScoredChunk]:
    """Dense + BM25 fused with RRF. Returns top_k ScoredChunks (fused score)."""
    settings = get_settings()
    k = top_k or settings.rag_top_k
    overfetch = k * 3

    # Dense branch (existing vector path).
    query_vector = embedder.embed_query(query)
    dense = store.search(db, owner_id, query_vector, top_k=overfetch)
    dense_ranked = [(c.document_id, c.chunk_id) for c in dense]
    dense_by_key = {(c.document_id, c.chunk_id): c for c in dense}

    # Sparse branch.
    index, shells = build_bm25_index(db, owner_id, store)
    sparse_ranked = [key for key, _ in index.search(query, overfetch)]

    # Fuse.
    fused = rrf_fuse([dense_ranked, sparse_ranked], k=settings.hybrid_rrf_k)
    max_rrf = max((s for _, s in fused), default=1.0) or 1.0

    out: list[ScoredChunk] = []
    for (document_id, chunk_id), rrf_score in fused:
        base = dense_by_key.get((document_id, chunk_id)) or shells.get(
            (document_id, chunk_id)
        )
        if base is None:
            continue
        out.append(
            ScoredChunk(
                chunk_id=base.chunk_id,
                document_id=base.document_id,
                filename=base.filename,
                content=base.content,
                # Normalize RRF to 0..1 so rag_min_score keeps its meaning.
                score=round(rrf_score / max_rrf, 6),
                modality=base.modality,
                page_number=base.page_number,
            )
        )
        if len(out) >= k * 3:  # over-fetch for the reranker, then cut to k
            break
    # Keep pre-rerank ordering stable; rag.retrieve() applies min_score + rerank.
    return out
