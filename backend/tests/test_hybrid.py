"""Tests for hybrid retrieval (BM25 + RRF) and the late-interaction reranker."""

import os

os.environ["VECTOR_BACKEND"] = "memory"
os.environ["EMBEDDING_PROVIDER"] = "fake"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-min-32-chars!!")

from app.services.hybrid import BM25Index, rrf_fuse  # noqa: E402
from app.services.reranking import maxsim_score, rerank  # noqa: E402
from app.services.vectorstore import ScoredChunk  # noqa: E402


def _chunk(cid: int, text: str, score: float = 0.5) -> ScoredChunk:
    return ScoredChunk(chunk_id=cid, document_id=1, filename="d.txt", content=text, score=score)


def test_bm25_ranks_exact_match_first():
    idx = BM25Index()
    idx.add(1, 0, "the rocket uses kerosene fuel")
    idx.add(1, 1, "a salad recipe with fresh greens")
    ranked = idx.search("rocket fuel", top_k=2)
    # zero-score docs are excluded - only the matching doc returns
    assert len(ranked) == 1
    assert ranked[0][0] == (1, 0)


def test_bm25_empty_index():
    assert BM25Index().search("anything", top_k=5) == []


def test_rrf_fusion_prefers_consensus():
    # (1,0) is rank-1 in the first list and rank-1 in the second -> wins
    fused = rrf_fuse([[(1, 0), (1, 1), (1, 2)], [(1, 0)]], k=60)
    assert fused[0][0] == (1, 0)
    # (1,1) at rank 2 beats (1,2) at rank 3
    assert fused[1][0] == (1, 1)
    assert fused[0][1] > fused[1][1] > fused[2][1]


def test_maxsim_rewards_token_overlap():
    s_good = maxsim_score("eiffel tower height", "the eiffel tower is 330 meters tall")
    s_bad = maxsim_score("eiffel tower height", "a salad recipe with fresh greens")
    assert s_good > s_bad
    assert 0.0 <= s_good <= 1.0


def test_rerank_reorders_by_late_interaction():
    chunks = [
        _chunk(0, "a salad recipe with fresh greens", score=0.6),
        _chunk(1, "the eiffel tower is 330 meters tall", score=0.4),
    ]
    out = rerank("how tall is the eiffel tower", chunks, top_k=2)
    assert out[0].chunk_id == 1  # reranker overrules the weaker dense score
    assert len(out) == 2


def test_rerank_none_is_passthrough():
    os.environ["RERANKER"] = "none"
    try:
        chunks = [_chunk(0, "aaa", score=0.9), _chunk(1, "bbb", score=0.1)]
        out = rerank("zzz", chunks, top_k=2)
        assert [c.chunk_id for c in out] == [0, 1]
    finally:
        del os.environ["RERANKER"]
