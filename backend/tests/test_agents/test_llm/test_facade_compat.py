"""Phase 1: llm_provider facade stays backward compatible + delegates to router."""
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from agents.llm_provider import get_llm_provider, reset_llm_provider


@pytest.mark.asyncio
async def test_generate_backcompat_positional_and_str():
    reset_llm_provider()
    fake_router = AsyncMock()
    fake_router.generate = AsyncMock(return_value="RESULT")
    with patch("agents.llm_provider.get_router", return_value=fake_router):
        p = get_llm_provider()
        # positional signature unchanged -> str
        out = await p.generate([HumanMessage(content="x")], temperature=0.3)
        assert out == "RESULT"
        # unknown task does not raise (router coerces to GENERAL)
        assert await p.generate([HumanMessage(content="x")], task="bogus") == "RESULT"
        # router received the task kwarg
        assert fake_router.generate.await_args.kwargs["task"] == "bogus"


@pytest.mark.asyncio
async def test_generate_structured_validates():
    reset_llm_provider()
    fake_router = AsyncMock()
    fake_router.generate = AsyncMock(return_value='{"action":"BUY","confidence":0.7,"rationale":"r"}')
    with patch("agents.llm_provider.get_router", return_value=fake_router):
        d = await get_llm_provider().generate_structured(
            [HumanMessage(content="x")], schema={"type": "object", "required": ["action"]}
        )
        assert d["action"] == "BUY"


@pytest.mark.asyncio
async def test_generate_structured_raises_on_missing_key():
    reset_llm_provider()
    fake_router = AsyncMock()
    fake_router.generate = AsyncMock(return_value='{"confidence":0.7}')  # no action
    with patch("agents.llm_provider.get_router", return_value=fake_router):
        with pytest.raises(ValueError):
            await get_llm_provider().generate_structured(
                [HumanMessage(content="x")], schema={"type": "object", "required": ["action"]}
            )
