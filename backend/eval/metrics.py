"""Pure retrieval metric functions (no I/O, no app imports).

Conventions:
- `retrieved`: ordered list of doc-id strings returned by the system (rank 1 first).
- `relevant`: set of ground-truth relevant doc-id strings.
- `k`: cutoff rank.
"""

import math


def hit_rate_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """1.0 if any relevant doc appears in the top-k, else 0.0."""
    return 1.0 if any(d in relevant for d in retrieved[:k]) else 0.0


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Fraction of relevant docs appearing in the top-k."""
    if not relevant:
        return 1.0  # nothing to recall; handled separately in eval
    return len(set(retrieved[:k]) & relevant) / len(relevant)


def mrr(retrieved: list[str], relevant: set[str]) -> float:
    """Mean reciprocal rank: 1/rank of the first relevant doc (0 if none)."""
    for rank, doc_id in enumerate(retrieved, start=1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """NDCG@k with binary relevance."""
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, doc_id in enumerate(retrieved[:k], start=1)
        if doc_id in relevant
    )
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 1.0


def context_precision(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Ragas-style context precision: relevant retrieved / retrieved (top-k)."""
    top = retrieved[:k]
    if not top:
        return 0.0
    return len(set(top) & relevant) / len(top)


def context_recall(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Ragas-style context recall: relevant retrieved / all relevant (top-k)."""
    return recall_at_k(retrieved, relevant, k)


def percentile(data: list[float], p: float) -> float:
    """Nearest-rank percentile (p in 0..100)."""
    if not data:
        return 0.0
    ordered = sorted(data)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]
