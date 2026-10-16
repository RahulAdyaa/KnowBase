"""Chat-completion client over any OpenAI-compatible API.

Streams tokens as an async iterator so the API layer can relay Server-Sent
Events without buffering the whole answer. Swap for Anthropic/Bedrock by
implementing the same `stream_chat` shape.
"""

from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings

import json as _json


class LLMClient:
    def __init__(self) -> None:
        s = get_settings()
        if not s.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self._model = s.chat_model
        self._client = httpx.AsyncClient(
            base_url=s.openai_base_url,
            headers={"Authorization": f"Bearer {s.openai_api_key}"},
            timeout=120.0,
        )

    async def stream_chat(self, system: str, user: str) -> AsyncIterator[str]:
        """Yield response text deltas."""
        async with self._client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": self._model,
                "stream": True,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    delta = _json.loads(data)["choices"][0]["delta"]
                    if "content" in delta:
                        yield delta["content"]
                except (KeyError, IndexError, ValueError):
                    continue

    async def aclose(self) -> None:
        await self._client.aclose()


def get_llm():
    """Provider factory. LLM_PROVIDER=local uses the free GGUF model (no key);
    default is the OpenAI-compatible API client."""
    from app.services.llm_local import LocalLlamaCppClient

    if get_settings().llm_provider.lower() == "local":
        return LocalLlamaCppClient()
    return LLMClient()
