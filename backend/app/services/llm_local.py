"""Free local LLM via llama-cpp-python (GGUF models, CPU-friendly, no API key).

Default model: Qwen2.5-0.5B-Instruct (Q4_K_M, ~400MB) - downloaded once from
HuggingFace into ./models on first use. Swap any GGUF via LOCAL_LLM_MODEL_PATH.

Same `stream_chat(system, user)` / `aclose()` shape as LLMClient, so the chat
pipeline is provider-agnostic. Select with LLM_PROVIDER=local.
"""

import os
import threading
from collections.abc import AsyncIterator

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf"
)
DEFAULT_MODEL_PATH = "models/Qwen3-4B-Q4_K_M.gguf"
# Fallback: smaller 0.5B model (faster, weaker).
FALLBACK_MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/"
    "qwen2.5-0.5b-instruct-q4_k_m.gguf"
)


def ensure_model(path: str) -> str:
    """Download the default GGUF on first use. Returns the local path."""
    if os.path.exists(path):
        return path
    import urllib.request

    url = os.environ.get("LOCAL_LLM_MODEL_URL", DEFAULT_MODEL_URL)
    log.info("llm_model_download_start", extra={"url": url})
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".downloading"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, path)
    log.info("llm_model_download_done", extra={"path": path})
    return path


class LocalLlamaCppClient:
    """llama-cpp-python client. Model loads lazily on first stream_chat."""

    _llm = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        s = get_settings()
        self._model_path = s.local_llm_model_path
        self._n_ctx = s.local_llm_n_ctx
        self._max_tokens = s.local_llm_max_tokens

    def _get_llm(self):
        with LocalLlamaCppClient._lock:
            if LocalLlamaCppClient._llm is None:
                from llama_cpp import Llama

                path = ensure_model(self._model_path)
                log.info("llm_local_load", extra={"path": path})
                LocalLlamaCppClient._llm = Llama(
                    model_path=path,
                    n_ctx=self._n_ctx,
                    n_threads=os.cpu_count() or 4,
                    verbose=False,
                )
            return LocalLlamaCppClient._llm

    async def stream_chat(self, system: str, user: str) -> AsyncIterator[str]:
        """Yield response text deltas (runs blocking inference in a thread).

        Qwen3 emits <think> blocks by default; they are filtered from the
        stream so users only see the final answer ('/no_think' also nudges the
        template, belt and suspenders).
        """
        async for token in self._stream(system, user, filter_think=True):
            yield token

    async def raw_stream_chat(self, system: str, user: str) -> AsyncIterator[str]:
        """Unfiltered stream (think blocks intact) - for machine consumers
        like the eval judge that parse structured output."""
        async for token in self._stream(system, user, filter_think=False):
            yield token

    async def _stream(
        self, system: str, user: str, filter_think: bool
    ) -> AsyncIterator[str]:
        import asyncio
        import re

        llm = self._get_llm()

        def _run():
            return llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user + " /no_think"},
                ],
                max_tokens=self._max_tokens,
                temperature=0.3,
                stream=True,
            )

        stream = await asyncio.to_thread(_run)
        if not filter_think:
            async for chunk in self._raw_chunks(stream):
                yield chunk
            return
        in_think = False
        buf = ""
        for text in self._sync_chunks(stream):
            buf += text
            # Strip <think>...</think> spans, which may straddle chunks.
            while True:
                if in_think:
                    end = buf.find("</think>")
                    if end == -1:
                        # Keep a tail in case the tag is split across chunks.
                        keep = max(0, len(buf) - 8)
                        buf = buf[keep:]
                        break
                    buf = buf[end + len("</think>") :]
                    in_think = False
                    continue
                start = buf.find("<think>")
                if start == -1:
                    break
                # Emit text before the think block, then enter it.
                yield buf[:start]
                buf = buf[start + len("<think>") :]
                in_think = True
            # Emit all but a small tail (a tag may be split across chunks).
            if not in_think and len(buf) > 16:
                yield buf[:-8]
                buf = buf[-8:]
        if buf:
            if in_think:
                # Unclosed think block (model cut off mid-reasoning): strip the
                # tags and emit the remainder rather than returning nothing.
                buf = re.sub(r"</?think>", "", buf)
            else:
                buf = re.sub(r"<think>.*", "", buf, flags=re.S)
            if buf:
                yield buf

    async def _raw_chunks(self, stream):
        for chunk in stream:
            try:
                delta = chunk["choices"][0]["delta"]
                text = delta.get("content") or ""
            except (KeyError, IndexError, TypeError):
                continue
            if text:
                yield text

    def _sync_chunks(self, stream):
        # stream is a sync iterator from llama-cpp; wrap for uniform handling.
        for chunk in stream:
            try:
                delta = chunk["choices"][0]["delta"]
                text = delta.get("content") or ""
            except (KeyError, IndexError, TypeError):
                continue
            if text:
                yield text

    async def aclose(self) -> None:
        pass  # process-lifetime singleton; nothing to close per request
