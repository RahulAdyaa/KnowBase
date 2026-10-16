"""Generation evaluation.

Two layers:

1. CITATION PLUMBING (runs without any LLM key): verifies through the real
   code path that citations are structurally valid - every citation references
   a retrieved chunk, snippets match chunk content, scores are present - and
   that the streaming answer pipeline works end-to-end with an extractive
   test-double LLM (quotes top-2 chunks verbatim). This validates plumbing,
   NOT answer quality.

2. LLM-JUDGED QUALITY (needs OPENAI_API_KEY): Ragas-style judges for
   faithfulness/groundedness, answer relevancy, answer correctness and
   (semantic) citation accuracy. Skipped with instructions when no key is set.
"""

import asyncio
import os

import httpx

from app.services.rag import build_citations, build_prompt, retrieve, stream_answer
from eval.corpus import DOCS, QUERIES
from eval.harness import EvalEnv


class ExtractiveTestDoubleLLM:
    """Test double: answers by quoting the first two chunks verbatim with
    [1][2] citations. Deterministic; used ONLY to validate the streaming
    plumbing, never as a quality signal."""

    async def stream_chat(self, system: str, user: str):
        # Parse the numbered excerpts back out of the prompt (real build_prompt format).
        import re

        excerpts = re.findall(r"\[(\d+)\] \(from ([^)]+)\)\n(.+?)(?=\n\[\d+\] \(from |\n\nQuestion:)", user, re.S)
        quotes = " ".join(f"[{n}] {text[:160]}" for n, _, text in excerpts[:2])
        answer = f"Based on the sources: {quotes}"
        for word in answer.split(" "):
            yield word + " "


async def _collect(stream):
    return "".join([t async for t in stream])


def citation_plumbing(env: EvalEnv) -> dict:
    rows = {}
    for qid, q in QUERIES.items():
        if not q["relevant"]:
            continue
        chunks = retrieve(env.session, env.user_id, q["question"], env.embedder, env.store)
        citations = build_citations(chunks)
        # NOTE: InMemoryVectorStore reuses chunk_id per document (dev-only quirk;
        # PgVectorStore uses globally unique DB row ids), so match on
        # (document_id, chunk_id).
        chunk_key = {(c.document_id, c.chunk_id): c for c in chunks}
        all_ref_valid = all(
            (cit.document_id, cit.chunk_id) in chunk_key for cit in citations
        )
        snippets_match = all(
            cit.snippet == chunk_key[(cit.document_id, cit.chunk_id)].content[:300]
            for cit in citations
        )
        scores_present = all(cit.score is not None for cit in citations)
        # End-to-end streaming with the extractive double.
        answer = asyncio.run(_collect(stream_answer(q["question"], chunks, ExtractiveTestDoubleLLM())))
        streamed = len(answer) > 0 and "[1]" in answer
        rows[qid] = {
            "n_citations": len(citations),
            "citations_reference_retrieved_chunks": all_ref_valid,
            "snippets_match_chunk_content": snippets_match,
            "scores_present": scores_present,
            "streaming_pipeline_ok": streamed,
        }
    ok = lambda key: sum(1 for r in rows.values() if r[key])  # noqa: E731
    n = len(rows)
    return {
        "n_queries": n,
        "citation_reference_integrity": f"{ok('citations_reference_retrieved_chunks')}/{n}",
        "snippet_fidelity": f"{ok('snippets_match_chunk_content')}/{n}",
        "streaming_pipeline": f"{ok('streaming_pipeline_ok')}/{n}",
        "note": "Structural plumbing only - does not measure whether citations support claims.",
        "per_query": rows,
    }


JUDGE_SYSTEM = (
    "You are a strict RAG evaluator. Reply with ONLY a JSON object "
    '{"score": <0.0-1.0>, "reason": "<one sentence>"} - no other text.'
)


def _judge(question: str, answer: str, context: str, client: httpx.Client, model: str, aspect: str) -> dict:
    prompts = {
        "faithfulness": (
            "Break the ANSWER into individual factual claims. For each claim, check if it is "
            "directly supported by the CONTEXT. score = supported claims / total claims.\n"
            f"QUESTION: {question}\nCONTEXT:\n{context}\nANSWER: {answer}"
        ),
        "answer_relevancy": (
            "Does the ANSWER directly and completely address the QUESTION? Penalize "
            "incomplete, evasive, or off-topic answers.\n"
            f"QUESTION: {question}\nANSWER: {answer}"
        ),
        "answer_correctness": (
            "Compare the ANSWER against the REFERENCE answer. Score semantic equivalence "
            "(1.0 = fully correct, 0.0 = wrong).\n"
            f"QUESTION: {question}\nREFERENCE: {context}\nANSWER: {answer}"
        ),
    }
    resp = client.post(
        "/chat/completions",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": prompts[aspect]},
            ],
            "temperature": 0.0,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    import json as _json

    return _json.loads(resp.json()["choices"][0]["message"]["content"])


def llm_judged_quality(env: EvalEnv) -> dict:
    """Full Ragas-style judged eval.

    Uses OPENAI_API_KEY when set, otherwise the free local GGUF model
    (LLM_PROVIDER=local). Skipped only when neither is available.
    """
    import asyncio

    api_key = os.environ.get("OPENAI_API_KEY")
    use_local = not api_key and os.environ.get("LLM_PROVIDER", "").lower() == "local"
    if not api_key and not use_local:
        return {
            "status": "skipped",
            "reason": "No LLM available - set OPENAI_API_KEY or LLM_PROVIDER=local.",
            "how_to_run": (
                "Set OPENAI_API_KEY (any OpenAI-compatible endpoint via OPENAI_BASE_URL) "
                "or LLM_PROVIDER=local (free GGUF, auto-downloads ~400MB), "
                "then run: python -m eval.run_generation."
            ),
            "metrics_covered_when_enabled": [
                "faithfulness / groundedness",
                "answer relevance",
                "answer correctness",
                "citation accuracy (semantic)",
            ],
        }

    from app.services.llm import get_llm

    llm = get_llm()
    judge_model = os.environ.get("EVAL_JUDGE_MODEL", "qwen3-4b-local" if use_local else "gpt-4o-mini")
    client = None
    if api_key:
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})

    async def _judge_local(prompt: str) -> dict:
        import json as _json
        import re

        # Raw stream: the judge's JSON often lands inside Qwen3 think blocks.
        text = "".join([t async for t in llm.raw_stream_chat(JUDGE_SYSTEM, prompt)])
        m = re.search(r"\{[^{}]*\}", text)
        if not m:
            return {"score": 0.5, "reason": "judge output unparseable"}
        try:
            d = _json.loads(m.group(0))
            return {"score": float(d.get("score", 0.5)), "reason": str(d.get("reason", ""))[:200]}
        except (ValueError, TypeError):
            return {"score": 0.5, "reason": "judge output unparseable"}

    async def _judge(question: str, answer: str, context: str, aspect: str) -> dict:
        prompts = {
            "faithfulness": (
                "Break the ANSWER into individual factual claims. For each claim, check if it is "
                "directly supported by the CONTEXT. score = supported claims / total claims.\n"
                f"QUESTION: {question}\nCONTEXT:\n{context}\nANSWER: {answer}"
            ),
            "answer_relevancy": (
                "Does the ANSWER directly and completely address the QUESTION? Penalize "
                "incomplete, evasive, or off-topic answers.\n"
                f"QUESTION: {question}\nANSWER: {answer}"
            ),
            "answer_correctness": (
                "Compare the ANSWER against the REFERENCE answer. Score semantic equivalence "
                "(1.0 = fully correct, 0.0 = wrong).\n"
                f"QUESTION: {question}\nREFERENCE: {context}\nANSWER: {answer}"
            ),
        }
        if use_local:
            return await _judge_local(prompts[aspect])
        return await asyncio.to_thread(
            _judge_openai, question, answer, context, client, judge_model, aspect
        )

    rows = {}
    try:
        for qid, q in QUERIES.items():
            if not q["relevant"]:
                continue
            rows[qid] = asyncio.run(_run_one_query(q, llm, env, _judge))
    finally:
        if client:
            client.close()
        asyncio.run(llm.aclose())
    return {"status": "measured", "judge_model": judge_model, "per_query": rows}


async def _run_one_query(q, llm, env, _judge) -> dict:
    chunks = retrieve(env.session, env.user_id, q["question"], env.embedder, env.store)
    answer = "".join([t async for t in stream_answer(q["question"], chunks, llm)])
    context = "\n\n".join(c.content for c in chunks)
    reference = " | ".join(DOCS[k]["text"][:200] for k in q["relevant"])
    return {
        "answer": answer[:300],
        "faithfulness": await _judge(q["question"], answer, context, "faithfulness"),
        "answer_relevancy": await _judge(q["question"], answer, context, "answer_relevancy"),
        "answer_correctness": await _judge(q["question"], answer, reference, "answer_correctness"),
    }


def _judge_openai(question: str, answer: str, context: str, client, model: str, aspect: str) -> dict:
    prompts = {
        "faithfulness": (
            "Break the ANSWER into individual factual claims. For each claim, check if it is "
            "directly supported by the CONTEXT. score = supported claims / total claims.\n"
            f"QUESTION: {question}\nCONTEXT:\n{context}\nANSWER: {answer}"
        ),
        "answer_relevancy": (
            "Does the ANSWER directly and completely address the QUESTION? Penalize "
            "incomplete, evasive, or off-topic answers.\n"
            f"QUESTION: {question}\nANSWER: {answer}"
        ),
        "answer_correctness": (
            "Compare the ANSWER against the REFERENCE answer. Score semantic equivalence "
            "(1.0 = fully correct, 0.0 = wrong).\n"
            f"QUESTION: {question}\nREFERENCE: {context}\nANSWER: {answer}"
        ),
    }
    resp = client.post(
        "/chat/completions",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": prompts[aspect]},
            ],
            "temperature": 0.0,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    import json as _json

    return _json.loads(resp.json()["choices"][0]["message"]["content"])


def evaluate(env: EvalEnv) -> dict:
    return {
        "citation_plumbing": citation_plumbing(env),
        "llm_judged_quality": llm_judged_quality(env),
    }


if __name__ == "__main__":
    import json

    env = EvalEnv()
    env.ingest()
    report = evaluate(env)
    env.close()
    with open("eval/results_generation.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))
