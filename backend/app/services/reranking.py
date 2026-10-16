"""Rerankers: real second-stage scoring over retrieved candidates.

Default: LateInteractionReranker - ColBERT-style MaxSim late interaction.
Each query/chunk token is embedded with a hashed token vector; the score is
the length-normalized sum over query tokens of the max cosine similarity to
any chunk token. This is a genuine token-level interaction signal - strictly
more expressive than the pooled dense cosine - and needs no model downloads.

Production path: plug a cross-encoder (Cohere Rerank, bge-reranker) behind the
`rerank()` signature via RERANKER=cross-encoder. The signature is unchanged.
"""

import hashlib
import math
import re

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.vectorstore import ScoredChunk

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DIMENSIONS = 128


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _token_vector(token: str) -> list[float]:
    """Deterministic hashed token embedding (matches FakeEmbeddingProvider's scheme)."""
    vec = [0.0] * _DIMENSIONS
    # Character-trigram hashing gives soft partial-match behaviour.
    padded = f"^{token}$"
    for i in range(len(padded) - 2):
        trigram = padded[i : i + 3]
        h = int(hashlib.md5(trigram.encode()).hexdigest(), 16)
        vec[h % _DIMENSIONS] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # inputs are unit-norm


def maxsim_score(query: str, chunk_text: str) -> float:
    """ColBERT-style MaxSim: mean over query tokens of max token similarity."""
    q_tokens = _tokenize(query)
    c_tokens = _tokenize(chunk_text)
    if not q_tokens or not c_tokens:
        return 0.0
    q_vecs = [_token_vector(t) for t in q_tokens]
    c_vecs = [_token_vector(t) for t in c_tokens]
    total = 0.0
    for qv in q_vecs:
        total += max(_cosine(qv, cv) for cv in c_vecs)
    return total / len(q_vecs)


class LateInteractionReranker:
    """Rerank candidates with MaxSim late interaction. Blends 50/50 with the
    first-stage score so dense/hybrid signal is preserved."""

    def __init__(self, blend: float = 0.5) -> None:
        self.blend = blend

    def rerank(self, query: str, chunks: list[ScoredChunk], top_k: int) -> list[ScoredChunk]:
        scored: list[tuple[float, ScoredChunk]] = []
        for c in chunks:
            s = maxsim_score(query, c.content)
            fused = self.blend * s + (1 - self.blend) * c.score
            scored.append((fused, c))
        scored.sort(key=lambda t: t[0], reverse=True)
        out: list[ScoredChunk] = []
        for fused, c in scored[:top_k]:
            out.append(
                ScoredChunk(
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    filename=c.filename,
                    content=c.content,
                    score=round(fused, 6),
                    modality=c.modality,
                    page_number=c.page_number,
                )
            )
        return out


def rerank(query: str, chunks: list[ScoredChunk], top_k: int) -> list[ScoredChunk]:
    """Second-stage rerank. RERANKER=none restores pass-through."""
    settings = get_settings()
    mode = settings.reranker.lower()
    if mode == "none":
        return chunks[:top_k]
    if mode == "cross-encoder":
        # Seam: instantiate a cross-encoder (Cohere/bge) here.
        raise NotImplementedError(
            "RERANKER=cross-encoder is a seam - wire your cross-encoder client here."
        )
    # default: late-interaction
    return LateInteractionReranker().rerank(query, chunks, top_k)
