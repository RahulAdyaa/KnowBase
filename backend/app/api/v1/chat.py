"""RAG chat: billed, rate-limited, streaming with citations.

Billing model: the credit gate deducts BEFORE generation (fail-closed).
If generation fails after charging, the charge stands and is visible in the
ledger - production systems may add a compensation refund; see README.
"""

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession, credit_gate, rate_limit
from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.chat import ChatAnswerResponse, ChatRequest
from app.services.embeddings import get_embedding_provider
from app.services.llm import get_llm
from app.services.rag import build_citations, retrieve, stream_answer
from app.services.vectorstore import get_vector_store

router = APIRouter()
log = get_logger(__name__)
settings = get_settings()

COST_PER_QUERY = settings.credits_per_chat_query


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post(
    "",
    dependencies=[
        Depends(rate_limit("chat", settings.rate_limit_chat_per_minute)),
        Depends(credit_gate(COST_PER_QUERY, reason="chat_query")),
    ],
)
async def chat_stream(request: Request, body: ChatRequest, db: DbSession, user: CurrentUser):
    """Stream the answer as Server-Sent Events (see schemas/chat.py)."""
    embedder = get_embedding_provider()
    store = get_vector_store()
    chunks = retrieve(db, user.id, body.message, embedder, store, top_k=body.top_k)
    citations = build_citations(chunks)
    deduction = request.state.deduction

    async def event_gen():
        yield _sse("citation", {"citations": [c.model_dump() for c in citations]})
        llm = get_llm()
        try:
            async for token in stream_answer(body.message, chunks, llm):
                yield _sse("token", {"text": token})
        finally:
            await llm.aclose()
        yield _sse(
            "done",
            {"credits_charged": deduction.charged, "balance_after": deduction.balance_after},
        )
        log.info(
            "chat_query",
            extra={"user_id": user.id, "chunks": len(chunks),
                   "request_id": getattr(request.state, "request_id", None)},
        )

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/ask", response_model=ChatAnswerResponse)
async def chat_ask(
    request: Request,
    body: ChatRequest,
    db: DbSession,
    user: CurrentUser,
    _gate=Depends(credit_gate(COST_PER_QUERY, reason="chat_query")),
    _rl=Depends(rate_limit("chat", settings.rate_limit_chat_per_minute)),
):
    """Non-streaming JSON fallback for simple clients."""
    embedder = get_embedding_provider()
    store = get_vector_store()
    chunks = retrieve(db, user.id, body.message, embedder, store, top_k=body.top_k)
    citations = build_citations(chunks)
    llm = get_llm()
    try:
        parts = [t async for t in stream_answer(body.message, chunks, llm)]
    finally:
        await llm.aclose()
    deduction = request.state.deduction
    return ChatAnswerResponse(
        answer="".join(parts),
        citations=citations,
        credits_charged=deduction.charged,
        balance_after=deduction.balance_after,
    )
