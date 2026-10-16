"""Pluggable embedding providers.

The RAG pipeline only depends on `EmbeddingProvider`. Swap implementations
via the EMBEDDING_PROVIDER env var - OpenAI by default, `fake` for tests and
offline local dev. A Cohere / Vertex / Bedrock provider slots in here.
"""

from typing import Protocol

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class EmbeddingProvider(Protocol):
    dimensions: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class OpenAIEmbeddingProvider:
    """Embeddings via any OpenAI-compatible /embeddings endpoint."""

    def __init__(self) -> None:
        s = get_settings()
        if not s.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set (EMBEDDING_PROVIDER=openai)")
        self.dimensions = s.embedding_dimensions
        self._model = s.embedding_model
        self._client = httpx.Client(
            base_url=s.openai_base_url,
            headers={"Authorization": f"Bearer {s.openai_api_key}"},
            timeout=60.0,
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        # Batch to stay under API limits.
        for i in range(0, len(texts), 128):
            batch = texts[i : i + 128]
            resp = self._client.post("/embeddings", json={"model": self._model, "input": batch})
            resp.raise_for_status()
            data = resp.json()["data"]
            # API may return out of order - sort by index.
            data.sort(key=lambda d: d["index"])
            vectors.extend(d["embedding"] for d in data)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class FakeEmbeddingProvider:
    """Deterministic, dependency-free embeddings for tests/offline dev.

    NOT for production - only preserves rough lexical overlap so the
    retrieval path can be exercised without an API key.
    """

    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        import hashlib

        vec = [0.0] * self.dimensions
        for word in text.lower().split():
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            vec[h % self.dimensions] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def get_embedding_provider() -> EmbeddingProvider:
    provider = get_settings().embedding_provider.lower()
    if provider == "openai":
        return OpenAIEmbeddingProvider()
    if provider == "fake":
        log.warning("using_fake_embeddings_not_for_production")
        return FakeEmbeddingProvider()
    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {provider}")
