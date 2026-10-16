"""Full RAG evaluation orchestrator.

Runs retrieval, robustness, generation and operational suites against the
real platform pipeline and writes eval/results.json.

    cd backend && .venv/bin/python -m eval.run_eval

Environment: uses FakeEmbeddingProvider + InMemoryVectorStore (lexical
baseline). Retrieval numbers measure the retrieval *path*, not production
semantic-embedding quality. LLM-judged generation metrics need OPENAI_API_KEY;
they are skipped otherwise.
"""

import json
import os
from datetime import datetime, timezone

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.harness import EvalEnv  # noqa: E402
from eval.run_ablation import ablate  # noqa: E402
from eval.run_generation import evaluate as eval_generation  # noqa: E402
from eval.run_operational import evaluate as eval_operational  # noqa: E402
from eval.run_retrieval import evaluate as eval_retrieval  # noqa: E402
from eval.run_robustness import evaluate as eval_robustness  # noqa: E402
from eval.test_multimodal import test_multimodal  # noqa: E402


def main() -> dict:
    llm_provider = os.environ.get("LLM_PROVIDER", "openai")
    env = EvalEnv()
    env.ingest()
    try:
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": {
                "embedding_provider": "FakeEmbeddingProvider (deterministic lexical baseline)",
                "vector_store": "InMemoryVectorStore",
                "llm_provider": llm_provider
                + (" (free local GGUF, qwen2.5-0.5b)" if llm_provider == "local" else " (needs API key)"),
                "llm_key_present": bool(os.environ.get("OPENAI_API_KEY")),
                "corpus_docs": 14,
                "eval_queries": 10,
            },
            "retrieval": eval_retrieval(env),
            "retrieval_ablation": ablate(),
            "robustness": eval_robustness(env),
            "generation": eval_generation(env),
            "multimodal": test_multimodal(),
            "operational": eval_operational(env),
        }
    finally:
        env.close()
    with open("eval/results.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    return report


if __name__ == "__main__":
    report = main()
    print(json.dumps(report, indent=2, default=str)[:3000])
    print("\n... full report written to eval/results.json")
