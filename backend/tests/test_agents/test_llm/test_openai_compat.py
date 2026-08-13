"""Phase 1: OpenAICompatBackend (OpenRouter / local Ollama-vLLM)."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from agents.llm.backends.openai_compat import OpenAICompatBackend
from agents.llm.backends.base import BackendError, BackendTransientError
from agents.llm.tasks import BackendName


def _backend():
    return OpenAICompatBackend(
        name=BackendName.OPENROUTER, base_url="http://x/v1",
        model="m", api_key="k", timeout=30,
    )


def test_capabilities():
    b = _backend()
    assert b.supports_stream and b.supports_schema
    assert b.name == BackendName.OPENROUTER


@pytest.mark.asyncio
async def test_generate_returns_content(monkeypatch):
    b = _backend()
    fake_client = MagicMock()
    fake_client.ainvoke = AsyncMock(return_value=MagicMock(content="hi"))
    monkeypatch.setattr(b, "_make_client", lambda *a, **k: fake_client)
    out = await b.generate([HumanMessage(content="x")], temperature=0.6, max_tokens=100)
    assert out == "hi"


@pytest.mark.asyncio
async def test_generate_maps_rate_limit_to_transient(monkeypatch):
    b = _backend()
    fake_client = MagicMock()
    fake_client.ainvoke = AsyncMock(side_effect=RuntimeError("HTTP 429 rate limit exceeded"))
    monkeypatch.setattr(b, "_make_client", lambda *a, **k: fake_client)
    with pytest.raises(BackendTransientError):
        await b.generate([HumanMessage(content="x")])
    # retried once before giving up
    assert fake_client.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_generate_maps_generic_to_backend_error(monkeypatch):
    b = _backend()
    fake_client = MagicMock()
    fake_client.ainvoke = AsyncMock(side_effect=ValueError("bad request 400"))
    monkeypatch.setattr(b, "_make_client", lambda *a, **k: fake_client)
    with pytest.raises(BackendError):
        await b.generate([HumanMessage(content="x")])
