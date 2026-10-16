"""Operational metrics.

- Latency p50/p95: timed over the real `retrieve()` path (embed + vector
  search + rerank stub) with FakeEmbeddingProvider/InMemoryVectorStore.
  Labelled clearly: this measures pipeline overhead, NOT production LLM latency.
- Token usage: estimated with the platform's own `estimate_tokens` (chars/4)
  on the exact prompt sent to the LLM (`build_prompt` output).
- Cost per query: from platform config (credits_per_chat_query); dollar mapping
  only exists once Stripe is wired (currently a stub).
- User feedback rate: checks whether the platform instruments feedback.
"""

import os
import time

from app.core.config import get_settings
from app.services.chunking import estimate_tokens
from app.services.rag import build_prompt, retrieve
from eval import metrics
from eval.corpus import QUERIES
from eval.harness import EvalEnv


def latency(env: EvalEnv, reps: int = 5) -> dict:
    settings = get_settings()
    k = settings.rag_top_k
    questions = [q["question"] for q in QUERIES.values() if q["relevant"]]
    samples: list[float] = []
    # warmup
    retrieve(env.session, env.user_id, questions[0], env.embedder, env.store)
    for _ in range(reps):
        for question in questions:
            t0 = time.perf_counter()
            retrieve(env.session, env.user_id, question, env.embedder, env.store)
            samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return {
        "n_samples": len(samples),
        "p50_ms": round(metrics.percentile(samples, 50), 3),
        "p95_ms": round(metrics.percentile(samples, 95), 3),
        "max_ms": round(samples[-1], 3),
        "path": "embed_query + InMemoryVectorStore.search + rerank stub (no LLM call)",
        "top_k": k,
    }


def token_usage(env: EvalEnv) -> dict:
    rows = {}
    for qid, q in QUERIES.items():
        if not q["relevant"]:
            continue
        chunks = retrieve(env.session, env.user_id, q["question"], env.embedder, env.store)
        prompt = build_prompt(q["question"], chunks)
        rows[qid] = {
            "prompt_tokens_est": estimate_tokens(prompt),
            "n_context_chunks": len(chunks),
        }
    vals = [r["prompt_tokens_est"] for r in rows.values()]
    return {
        "estimator": "platform estimate_tokens (chars/4 heuristic, not tiktoken)",
        "scope": "LLM input prompt only (context + question); excludes system prompt and output",
        "avg_prompt_tokens": round(sum(vals) / len(vals), 1),
        "max_prompt_tokens": max(vals),
        "per_query": rows,
    }


def cost_per_query() -> dict:
    settings = get_settings()
    return {
        "credits_per_chat_query": settings.credits_per_chat_query,
        "credits_per_1k_embed_tokens": settings.credits_per_1k_embed_tokens,
        "dollar_cost_per_query": "not configured - Stripe top-up is a stub; no credit->USD mapping exists yet",
        "note": "Billing plumbing (deduction, ledger, 402 gate) is tested in test_credits.py; "
        "monetary cost needs Stripe wiring + a credit price.",
    }


def user_feedback() -> dict:
    import pathlib

    api_files = list(pathlib.Path("app/api/v1").glob("*.py"))
    mentions = [
        f for f in api_files if "feedback" in f.read_text().lower()
    ]
    return {
        "feedback_endpoint_exists": bool(mentions),
        "feedback_rate": "n/a - no feedback instrumentation and no production traffic",
        "recommendation": "Add POST /api/v1/chat/feedback {message_id, rating} and track "
        "thumbs-up/down rate per week as the quality KPI.",
    }


def evaluate(env: EvalEnv) -> dict:
    return {
        "latency": latency(env),
        "token_usage": token_usage(env),
        "cost_per_query": cost_per_query(),
        "user_feedback": user_feedback(),
    }


if __name__ == "__main__":
    import json

    # run from backend/ so the feedback scan hits app/api/v1
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = EvalEnv()
    env.ingest()
    print(json.dumps(evaluate(env), indent=2))
    env.close()
