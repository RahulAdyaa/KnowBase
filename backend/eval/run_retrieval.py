"""Retrieval evaluation: runs every query through the real `retrieve()`
and scores Context Recall, Context Precision, Hit Rate@k, MRR and NDCG@k.

Unanswerable queries (empty ground truth) are excluded here - they are
covered by the negative-rejection test in run_robustness.py.
"""

from app.core.config import get_settings
from app.services.rag import retrieve
from eval import metrics
from eval.corpus import QUERIES
from eval.harness import EvalEnv


def evaluate(env: EvalEnv, k: int | None = None) -> dict:
    settings = get_settings()
    k = k or settings.rag_top_k
    per_query: dict[str, dict] = {}
    agg: dict[str, list[float]] = {
        "hit_rate": [],
        "recall": [],
        "mrr": [],
        "ndcg": [],
        "ctx_precision": [],
        "ctx_recall": [],
    }
    for qid, q in QUERIES.items():
        relevant = set(q["relevant"])
        if not relevant:
            continue  # unanswerable -> robustness suite
        chunks = retrieve(env.session, env.user_id, q["question"], env.embedder, env.store)
        retrieved = [env.chunk_id_to_doc_key(c) for c in chunks]
        retrieved = [d for d in retrieved if d is not None]
        row = {
            "kind": q["kind"],
            "n_relevant": len(relevant),
            "n_retrieved": len(retrieved),
            "retrieved": retrieved,
            "hit_rate@k": metrics.hit_rate_at_k(retrieved, relevant, k),
            "recall@k": metrics.recall_at_k(retrieved, relevant, k),
            "mrr": metrics.mrr(retrieved, relevant),
            "ndcg@k": metrics.ndcg_at_k(retrieved, relevant, k),
            "ctx_precision@k": metrics.context_precision(retrieved, relevant, k),
            "ctx_recall@k": metrics.context_recall(retrieved, relevant, k),
            "top_score": round(chunks[0].score, 4) if chunks else 0.0,
        }
        per_query[qid] = row
        agg["hit_rate"].append(row["hit_rate@k"])
        agg["recall"].append(row["recall@k"])
        agg["mrr"].append(row["mrr"])
        agg["ndcg"].append(row["ndcg@k"])
        agg["ctx_precision"].append(row["ctx_precision@k"])
        agg["ctx_recall"].append(row["ctx_recall@k"])

    def avg(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    return {
        "k": k,
        "n_queries": len(per_query),
        "hit_rate@k": avg(agg["hit_rate"]),
        "recall@k (context recall)": avg(agg["recall"]),
        "mrr": avg(agg["mrr"]),
        "ndcg@k": avg(agg["ndcg"]),
        "context_precision@k": avg(agg["ctx_precision"]),
        "per_query": per_query,
    }


if __name__ == "__main__":
    import json

    env = EvalEnv()
    env.ingest()
    print(json.dumps(evaluate(env), indent=2))
    env.close()
