"""OpenAI-compatible HTTP backend (OpenRouter, or local Ollama/vLLM).

Lifts the existing ChatOpenAI usage out of llm_provider.py. Used for both the
`openrouter` and (optional) `local` backends — same code, different config.
"""
from typing import AsyncIterator, Optional

import httpx
import structlog
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from agents.llm.backends.base import (
    BackendAuthError, BackendError, BackendTransientError, LLMBackend,
)
from agents.llm.tasks import BackendName

logger = structlog.get_logger()

_TRANSIENT_MARKERS = (
    "rate limit", "429", "overloaded", "timeout", "timed out",
    "connection", "temporarily", "503", "502", "500", "econnreset",
)
_AUTH_MARKERS = ("401", "403", "unauthorized", "invalid api key", "no api key")


def _classify(exc: Exception) -> BackendError:
    msg = str(exc).lower()
    if any(mk in msg for mk in _AUTH_MARKERS):
        return BackendAuthError(str(exc))
    if any(mk in msg for mk in _TRANSIENT_MARKERS):
        return BackendTransientError(str(exc))
    return BackendError(str(exc))


class OpenAICompatBackend(LLMBackend):
    supports_stream = True
    supports_schema = True

    def __init__(
        self,
        name: BackendName,
        base_url: str,
        model: str,
        api_key: str,
        timeout: int,
        default_temperature: float = 0.6,
        default_max_tokens: int = 4096,
    ):
        self.name = name
        self.base_url = base_url
        self.model = model
        self._api_key = api_key
        self.timeout = timeout
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens

    def _make_client(
        self, temperature: float, max_tokens: int, response_schema: Optional[dict]
    ) -> ChatOpenAI:
        kwargs = dict(
            base_url=self.base_url,
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self.timeout,
            api_key=self._api_key,
        )
        if response_schema is not None:
            kwargs["model_kwargs"] = {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "decision", "schema": response_schema},
                }
            }
        return ChatOpenAI(**kwargs)

    async def generate(
        self,
        messages: list[BaseMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_schema: Optional[dict] = None,
    ) -> str:
        temp = self.default_temperature if temperature is None else temperature
        mx = self.default_max_tokens if max_tokens is None else max_tokens
        last: Optional[BackendError] = None
        # Narrow in-backend retry: one extra attempt on a transient error only.
        for attempt in range(2):
            client = self._make_client(temp, mx, response_schema)
            try:
                resp = await client.ainvoke(messages)
                return resp.content if isinstance(resp.content, str) else str(resp.content)
            except Exception as e:  # noqa: BLE001 — classify then re-raise typed
                last = _classify(e)
                if isinstance(last, BackendTransientError) and attempt == 0:
                    logger.warning("openai_compat_transient_retry", backend=self.name.value)
                    continue
                raise last
        raise last  # pragma: no cover

    async def stream(
        self,
        messages: list[BaseMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        temp = self.default_temperature if temperature is None else temperature
        mx = self.default_max_tokens if max_tokens is None else max_tokens
        client = self._make_client(temp, mx, None)
        try:
            async for chunk in client.astream(messages):
                if chunk.content:
                    yield chunk.content if isinstance(chunk.content, str) else str(chunk.content)
        except Exception as e:  # noqa: BLE001
            raise _classify(e)

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                return r.status_code == 200
        except Exception:
            return False
