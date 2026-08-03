"""라우터가 사용량 한도에만, 신선도 상한까지만 기다리는지.

상한 300초는 감시 주기(1분)의 5배이며 신선도에서 유도된 값이다 — 멈췄던 토론은
멈춘 시점의 가격을 들고 있어, 그보다 오래 기다려 재개하면 낡은 값으로 매매를
결정하게 된다.

실제로 5분을 자지 않도록 asyncio.sleep을 mock하고 시계를 주입한다.
"""
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from agents.llm import router as router_mod
from agents.llm.backends.base import (
    BackendAuthError,
    BackendError,
    BackendUsageLimitError,
    LLMAllBackendsFailed,
    LLMBackend,
)
from agents.llm.tasks import BackendName, TaskType


class _Backend(LLMBackend):
    """정해진 횟수만큼 실패한 뒤 성공하는 백엔드."""

    def __init__(self, name, *, error, fail_times=10**9, result="ok"):
        self.name = name
        self._error = error
        self._fail_times = fail_times
        self._result = result
        self.supports_stream = False
        self.supports_schema = True
        self.calls = 0

    async def generate(self, messages, *, temperature=None, max_tokens=None, response_schema=None):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error
        return self._result

    async def health(self):
        return True


def _msgs():
    return [HumanMessage(content="hi")]


def _router_with(backend):
    r = router_mod.Router()
    with patch.object(r, "resolve", return_value=[backend]):
        yield r


@pytest.mark.asyncio
async def test_waits_and_succeeds_when_limit_clears_within_cap():
    backend = _Backend(
        BackendName.CLAUDE_CLI,
        error=BackendUsageLimitError("claude exited 1: usage limit reached"),
        fail_times=2,
    )
    slept = []

    async def _fake_sleep(sec):
        slept.append(sec)

    r = router_mod.Router()
    with patch.object(r, "resolve", return_value=[backend]), \
         patch.object(router_mod.asyncio, "sleep", _fake_sleep):
        result = await r.generate(_msgs(), task=TaskType.GENERAL)

    assert result == "ok"
    assert backend.calls == 3          # 2회 실패 후 3번째 성공
    assert len(slept) == 2             # 실패마다 한 번씩 대기


@pytest.mark.asyncio
async def test_gives_up_at_the_freshness_cap():
    backend = _Backend(
        BackendName.CLAUDE_CLI,
        error=BackendUsageLimitError("claude exited 1: usage limit reached"),
    )
    elapsed = {"t": 0.0}

    async def _fake_sleep(sec):
        elapsed["t"] += sec

    class _FakeTime:
        """`router_mod.time` 참조만 갈아끼운다. `time.monotonic`을 전역 패치하면
        asyncio 내부까지 영향을 받아 테스트가 예측 불가능해진다."""

        @staticmethod
        def monotonic():
            return elapsed["t"]

    r = router_mod.Router()
    with patch.object(r, "resolve", return_value=[backend]), \
         patch.object(router_mod.asyncio, "sleep", _fake_sleep), \
         patch.object(router_mod, "time", _FakeTime):
        with pytest.raises(LLMAllBackendsFailed):
            await r.generate(_msgs(), task=TaskType.GENERAL)

    assert elapsed["t"] >= router_mod._USAGE_LIMIT_WAIT_SECONDS
    # 상한을 크게 넘겨 계속 돌지 않는다
    assert elapsed["t"] < router_mod._USAGE_LIMIT_WAIT_SECONDS + 2 * router_mod._USAGE_LIMIT_RETRY_INTERVAL


@pytest.mark.asyncio
async def test_does_not_wait_for_non_limit_failures():
    """인증 오류는 기다린다고 풀리지 않는다 — 즉시 던져야 한다."""
    backend = _Backend(BackendName.CLAUDE_CLI, error=BackendAuthError("logged out"))
    slept = []

    async def _fake_sleep(sec):
        slept.append(sec)

    r = router_mod.Router()
    with patch.object(r, "resolve", return_value=[backend]), \
         patch.object(router_mod.asyncio, "sleep", _fake_sleep):
        with pytest.raises(LLMAllBackendsFailed):
            await r.generate(_msgs(), task=TaskType.GENERAL)

    assert slept == []
    assert backend.calls == 1


@pytest.mark.asyncio
async def test_does_not_wait_when_no_backend_is_available():
    """체인이 비었다 = 서킷이 열려 있다. 긴 장애에 5분씩 낭비하지 않는다."""
    slept = []

    async def _fake_sleep(sec):
        slept.append(sec)

    r = router_mod.Router()
    with patch.object(r, "resolve", return_value=[]), \
         patch.object(router_mod.asyncio, "sleep", _fake_sleep):
        with pytest.raises(LLMAllBackendsFailed):
            await r.generate(_msgs(), task=TaskType.GENERAL)

    assert slept == []


@pytest.mark.asyncio
async def test_generic_error_still_falls_through_without_waiting():
    backend = _Backend(BackendName.CLAUDE_CLI, error=BackendError("boom"))
    slept = []

    async def _fake_sleep(sec):
        slept.append(sec)

    r = router_mod.Router()
    with patch.object(r, "resolve", return_value=[backend]), \
         patch.object(router_mod.asyncio, "sleep", _fake_sleep):
        with pytest.raises(LLMAllBackendsFailed):
            await r.generate(_msgs(), task=TaskType.GENERAL)

    assert slept == []
