"""LLM 실패가 '의견'으로 세탁되지 않는지 — 2026-08-03 라이브 장애 회귀 방지.

실패를 문자열로 반환하면 그 문자열이 토론에 정상 의견처럼 흘러들어, 합의 불성립이
가짜 NO_ACTION이 되어 원장에 쌓인다. 실패는 전파돼야 하고, chat_room.start()가
그것을 잡아 세션을 CANCELLED로 표시한다.
"""
from unittest.mock import AsyncMock

import pytest

from agents.llm.backends.base import LLMAllBackendsFailed
from services.agent_chat.agents.base_agent import BaseDiscussionAgent


class _Agent:
    """base_agent의 _call_llm만 빌려 쓰기 위한 최소 구성.

    실제 클래스명은 브리프의 `BaseAgent`가 아니라 `BaseDiscussionAgent`다.
    그 생성자는 `get_llm_provider()`를 호출해 실 LLM 라우터를 구성하므로,
    단위 테스트에서 생성자를 거치지 않고 `_call_llm`만 바인딩해 쓴다.
    """

    def __init__(self, llm):
        self.llm = llm
        self.agent_name = "테스트요원"

    _call_llm = BaseDiscussionAgent._call_llm


@pytest.mark.asyncio
async def test_llm_failure_propagates_instead_of_becoming_text():
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=LLMAllBackendsFailed("no available backend"))
    agent = _Agent(llm)

    with pytest.raises(LLMAllBackendsFailed):
        await agent._call_llm("sys", "user")


@pytest.mark.asyncio
async def test_error_text_is_never_returned_as_analysis():
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("boom"))
    agent = _Agent(llm)

    with pytest.raises(RuntimeError):
        result = await agent._call_llm("sys", "user")
        assert "분석 중 오류 발생" not in result  # 도달하면 안 된다


@pytest.mark.asyncio
async def test_success_path_unchanged():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="정상 분석 결과")
    agent = _Agent(llm)

    assert await agent._call_llm("sys", "user") == "정상 분석 결과"
