"""Text chunking for ingestion.

Paragraph-aware recursive splitter: tries to break on paragraph, then
sentence, then word boundaries so chunks keep semantic coherence.
No heavy NLP dependencies - pure Python.
"""

from dataclasses import dataclass


@dataclass
class Chunk:
    index: int
    content: str
    token_count: int


def estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars/token). Replace with tiktoken for billing-grade counts."""
    return max(1, len(text) // 4)


def chunk_text(text: str, chunk_size: int = 800, chunk_overlap: int = 120) -> list[Chunk]:
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    text = " ".join(text.split())  # normalize whitespace
    if not text:
        return []

    separators = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "]
    chunks: list[str] = []
    current = ""

    def flush():
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    # Greedy fill: accumulate words, splitting oversized pieces on separators.
    words = text.split(" ")
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        if estimate_tokens(candidate) <= chunk_size:
            current = candidate
            continue
        # current is full - split the long word if a single word exceeds the size
        flush()
        piece = word
        while estimate_tokens(piece) > chunk_size:
            cut = _split_at_separator(piece, chunk_size, separators)
            chunks.append(cut.strip())
            piece = piece[len(cut):].lstrip()
        current = piece

    flush()

    # Apply overlap by prepending the tail of the previous chunk.
    overlapped: list[Chunk] = []
    for i, content in enumerate(chunks):
        if i > 0 and chunk_overlap > 0:
            prev_tail = chunks[i - 1][-chunk_overlap * 4 :]  # ~chars for overlap tokens
            content = (prev_tail + " " + content).strip()
        overlapped.append(Chunk(index=i, content=content, token_count=estimate_tokens(content)))
    return overlapped


def _split_at_separator(text: str, max_tokens: int, separators: list[str]) -> str:
    """Cut `text` near max_tokens at the best available separator."""
    budget = max_tokens * 4  # chars
    for sep in separators:
        idx = text.rfind(sep, 0, budget)
        if idx > budget // 4:  # don't cut comically early
            return text[: idx + len(sep)]
    return text[:budget]
