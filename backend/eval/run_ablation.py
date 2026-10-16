"""Retrieval ablation: dense-only vs hybrid vs hybrid+reranker.

Switches modes via env vars (get_settings() re-reads env per call).
"""

import os

from app.core.config import get_settings
from eval.harness import EvalEnv
from eval.run_retrieval import evaluate as evaluate_retrieval

MODES = [
    ("dense_only", {"HYBRID_RETRIEVAL": "false", "RERANKER": "none"}),
    ("hybrid_only", {"HYBRID_RETRIEVAL": "true", "RERANKER": "none"}),
    ("hybrid_reranked", {"HYBRID_RETRIEVAL": "true", "RERANKER": "late-interaction"}),
]


def ablate() -> dict:
    results = {}
    for name, env_vars in MODES:
        for k, v in env_vars.items():
            os.environ[k] = v
        get_settings.cache_clear()  # settings are lru_cached per process
        env = EvalEnv()
        env.ingest()
        try:
            res = evaluate_retrieval(env)
            results[name] = {
                m: res[m]
                for m in (
                    "hit_rate@k",
                    "recall@k (context recall)",
                    "mrr",
                    "ndcg@k",
                    "context_precision@k",
                )
            }
        finally:
            env.close()
    return results


if __name__ == "__main__":
    import json

    print(json.dumps(ablate(), indent=2))
