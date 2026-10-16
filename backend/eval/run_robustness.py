"""Robustness evaluation.

- Negative rejection: unanswerable queries should retrieve nothing relevant AND
  the answer path should abstain (stream_answer with no chunks).
- Noise robustness: retrieval quality with distractor docs present vs removed.
- Multi-hop reasoning: both hop-docs retrievable in top-k (retrieval half of
  multi-hop; the composition half needs an LLM judge -> run_generation).
- Conflicting info: both conflicting sources surface (system has no
  adjudication logic - verified here).
"""

import asyncio

from app.services.rag import build_citations, retrieve, stream_answer
from eval.corpus import DOCS, QUERIES
from eval.harness import EvalEnv
from eval.run_retrieval import evaluate as evaluate_retrieval


class _NeverCalledLLM:
    async def stream_chat(self, system: str, user: str):
        raise AssertionError("LLM must not be called on the abstention path")
        yield  # make it an async generator


async def _collect(stream):
    return "".join([t async for t in stream])


def negative_rejection(env: EvalEnv) -> dict:
    rows = {}
    for qid, q in QUERIES.items():
        if q["kind"] != "unanswerable":
            continue
        chunks = retrieve(env.session, env.user_id, q["question"], env.embedder, env.store)
        retrieved_keys = [env.chunk_id_to_doc_key(c) for c in chunks]
        # Real-path check: with rag_min_score=0.0 the gate never filters, so the
        # abstention branch in stream_answer is unreachable in practice.
        gate_filters = len(chunks) == 0
        # Branch check: real stream_answer with zero chunks and an LLM that
        # explodes if touched - proves the branch abstains without generation.
        answer = asyncio.run(_collect(stream_answer(q["question"], [], _NeverCalledLLM())))
        abstains = "don't have" in answer
        rows[qid] = {
            "n_retrieved": len(chunks),
            "retrieved": retrieved_keys,
            "relevant_retrieved": 0,
            "retrieval_gate_filters_irrelevant": gate_filters,
            "abstention_branch_works": abstains,
            "abstention_text": answer[:120],
        }
    branch_ok = sum(1 for r in rows.values() if r["abstention_branch_works"])
    gated = sum(1 for r in rows.values() if r["retrieval_gate_filters_irrelevant"])
    return {
        "n_unanswerable": len(rows),
        "abstention_branch_rate": round(branch_ok / len(rows), 4) if rows else 0.0,
        "effective_rejection_rate_real_path": round(gated / len(rows), 4) if rows else 0.0,
        "finding": (
            "The abstention branch works in isolation, but with the default "
            "rag_min_score=0.0 the retrieval gate never filters, so irrelevant chunks "
            "are always passed to the LLM. In production, rejection depends on the LLM "
            "following the 'say you don't know' system instruction. Raise rag_min_score "
            "to make rejection deterministic."
        ),
        "per_query": rows,
    }


def noise_robustness() -> dict:
    """Same queries, corpus with vs without the N* distractor docs."""
    noisy = EvalEnv()
    noisy.ingest()
    clean_keys = [k for k in DOCS if not k.startswith("N")]
    clean = EvalEnv()
    clean.ingest(clean_keys)
    noisy_res = evaluate_retrieval(noisy)
    clean_res = evaluate_retrieval(clean)
    noisy.close()
    clean.close()
    delta = {
        m: round(noisy_res[m] - clean_res[m], 4)
        for m in ("hit_rate@k", "recall@k (context recall)", "mrr", "ndcg@k")
    }
    return {
        "with_noise_docs": {m: noisy_res[m] for m in delta},
        "without_noise_docs": {m: clean_res[m] for m in delta},
        "delta_noisy_minus_clean": delta,
    }


def multi_hop(env: EvalEnv) -> dict:
    q = QUERIES["Q5"]
    chunks = retrieve(env.session, env.user_id, q["question"], env.embedder, env.store)
    keys = [env.chunk_id_to_doc_key(c) for c in chunks]
    return {
        "question": q["question"],
        "retrieved": keys,
        "hop_D5_retrieved": "D5" in keys,
        "hop_D6_retrieved": "D6" in keys,
        "both_hops_in_top_k": "D5" in keys and "D6" in keys,
        "note": "retrieval half of multi-hop; answer composition needs LLM judge",
    }


def conflicting_info(env: EvalEnv) -> dict:
    q = QUERIES["Q8"]
    chunks = retrieve(env.session, env.user_id, q["question"], env.embedder, env.store)
    keys = [env.chunk_id_to_doc_key(c) for c in chunks]
    citations = build_citations(chunks)
    return {
        "question": q["question"],
        "retrieved": keys,
        "both_sources_surfaced": "D7" in keys and "D8" in keys,
        "citation_count": len(citations),
        "finding": (
            "System surfaces both conflicting sources with citations but has no "
            "adjudication logic - the LLM is instructed to answer only from context, "
            "so conflicts are passed to the model/user unresolved."
        ),
    }


def evaluate(env: EvalEnv) -> dict:
    return {
        "negative_rejection": negative_rejection(env),
        "noise_robustness": noise_robustness(),
        "multi_hop": multi_hop(env),
        "conflicting_info": conflicting_info(env),
    }


if __name__ == "__main__":
    import json

    env = EvalEnv()
    env.ingest()
    print(json.dumps(evaluate(env), indent=2))
    env.close()
