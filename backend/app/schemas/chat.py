"""Chat schemas. The chat endpoint streams Server-Sent Events:

    event: citation   data: {"chunk_id": 12, "document_id": 3, "filename": "a.pdf", "score": 0.87, "snippet": "..."}
    event: token      data: {"text": "partial answer..."}
    event: done       data: {"credits_charged": 1, "balance_after": 49}

A non-streaming JSON fallback (POST /chat/ask) is provided for simple clients.
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None  # reserved for multi-turn memory
    top_k: int | None = Field(default=None, ge=1, le=20)


class Citation(BaseModel):
    chunk_id: int
    document_id: int
    filename: str
    score: float
    snippet: str
    modality: str = "text"
    page_number: int | None = None


class ChatAnswerResponse(BaseModel):
    answer: str
    citations: list[Citation]
    credits_charged: int
    balance_after: int
