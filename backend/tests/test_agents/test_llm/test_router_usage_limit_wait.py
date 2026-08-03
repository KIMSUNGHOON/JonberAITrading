"""라우터가 사용량 한도에만, 신선도 상한까지만 기다리는지.

상한 300초는 감시 주기(1분)의 5배이며 신선도에서 유도된 값이다 — 멈췄던 토론은
멈춘 시점의 가격을 들고 있어, 그보다 오래 기다려 재개하면 낡은 값으로 매매를
결정하게 된다.

실제로 5분을 자지 않도록 asyncio.sleep을 mock하고 시계를 주입한다.

대부분의 테스트는 `r.resolve`를 패치해 대기 루프만 순수하게 검증한다. 다만 이렇게
패치하면 실제 서킷 차단기 상호작용(2026-08-03 리뷰 Finding 1의 원인)이 전부
가려진다 — 그래서 `test_real_resolve_...`는 일부러 `resolve()`를 패치하지 않고,
라우터·서킷·대기가 같은 가짜 시계를 공유하는 상태로 실제 라우팅 경로를 태운다.
"""
from unittest.mock import patch

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
from app.config import settings


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


class _SwitchingBackend(LLMBackend):
    """호출 순서대로 다른 오류를 낸다 — 한도 대기가 다른 종류의 실패로 넘어가지
    않는지 검증하는 용도(오류 목록을 넘어서면 마지막 오류를 반복)."""

    def __init__(self, name, *, errors):
        self.name = name
        self._errors = list(errors)
        self.supports_stream = False
        self.supports_schema = True
        self.calls = 0

    async def generate(self, messages, *, temperature=None, max_tokens=None, response_schema=None):
        self.calls += 1
        idx = min(self.calls, len(self._errors)) - 1
        raise self._errors[idx]

    async def health(self):
        return True


def _msgs():
    return [HumanMessage(content="hi")]


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
    # 개수뿐 아니라 값 자체를 고정한다 — _USAGE_LIMIT_RETRY_INTERVAL이 바뀌면
    # 이 테스트가 그 사실을 드러내야 한다(관측된 동작에 상수를 고정).
    assert slept == [20, 20]


@pytest.mark.asyncio
async def test_gives_up_at_the_freshness_cap():
    """가짜 시계를 `Router(now=...)`로 주입한다. router.py가 이제 `self._now()`만
    쓰므로(모듈 전역 `time.monotonic`이 아님), 라우터와 서킷 차단기가 항상 같은
    시계를 본다 — 예전처럼 `router_mod.time`을 패치해도 `self._now`는 생성 시점에
    이미 real `time.monotonic`에 바인딩돼 있어 아무 효과가 없다."""
    backend = _Backend(
        BackendName.CLAUDE_CLI,
        error=BackendUsageLimitError("claude exited 1: usage limit reached"),
    )
    elapsed = {"t": 0.0}

    async def _fake_sleep(sec):
        elapsed["t"] += sec

    r = router_mod.Router(now=lambda: elapsed["t"])
    with patch.object(r, "resolve", return_value=[backend]), \
         patch.object(router_mod.asyncio, "sleep", _fake_sleep):
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


@pytest.mark.asyncio
async def test_wait_does_not_persist_across_different_failure_kinds():
    """1패스는 usage limit(대기 시작), 2패스는 다른 종류의 오류 — 대기 상태를
    물려받지 않고 그 자리에서 즉시 포기해야 한다."""
    backend = _SwitchingBackend(
        BackendName.CLAUDE_CLI,
        errors=[
            BackendUsageLimitError("claude exited 1: usage limit reached"),
            BackendError("boom-different"),
        ],
    )
    slept = []

    async def _fake_sleep(sec):
        slept.append(sec)

    r = router_mod.Router()
    with patch.object(r, "resolve", return_value=[backend]), \
         patch.object(router_mod.asyncio, "sleep", _fake_sleep):
        with pytest.raises(LLMAllBackendsFailed) as exc_info:
            await r.generate(_msgs(), task=TaskType.GENERAL)

    assert "boom-different" in str(exc_info.value)
    assert slept == [20]        # 1패스 뒤에만 대기했다 — 2패스에서는 대기 없이 포기
    assert backend.calls == 2


@pytest.mark.asyncio
async def test_real_resolve_waits_to_cap_and_charges_breaker_once(monkeypatch):
    """`resolve()`를 패치하지 않고 실제 라우팅+서킷+대기 경로를 공유 가짜 시계로
    검증한다.

    2026-08-03 리뷰 Finding 1: 재시도 패스마다 `record_failure()`를 부르면
    LLM_CIRCUIT_FAIL_THRESHOLD(기본 3)회 만에 서킷이 열려 `resolve()`가 빈 체인을
    반환하고, "체인이 비면 즉시 던진다" 규칙과 충돌해 300초 대기가 사실상 도달
    불가능해진다 — 실측 시 ~60초에 "no available backend"로 끊겼다. 위의 테스트들은
    전부 `r.resolve`를 패치하므로 이 결함이 green 스위트에서 보이지 않았다. 이
    테스트는 그 결함이 고쳐졌는지(서킷이 호출당 1회만 charge되어 계속 closed
    상태를 유지하고, 대기가 실제로 300초 상한까지 도달하는지) 검증한다.
    """
    # 서킷 임계값을 이 테스트 안에서 고정한다 — 운영자가 .env에서 바꾸면 이
    # 테스트가 조용히 무의미해지거나(threshold를 올리면) 항상 실패한다(특히
    # threshold=1이면 "1회만 charge"해도 즉시 열린다).
    monkeypatch.setattr(settings, "LLM_CIRCUIT_FAIL_THRESHOLD", 3, raising=False)
    monkeypatch.setattr(settings, "LLM_CIRCUIT_COOLDOWN", 60, raising=False)

    backend = _Backend(
        BackendName.CLAUDE_CLI,
        error=BackendUsageLimitError("claude exited 1: usage limit reached"),
    )
    elapsed = {"t": 0.0}

    async def _fake_sleep(sec):
        elapsed["t"] += sec

    # GROUP_CHAT 체인은 [CLAUDE_CLI, OPENROUTER]다. OPENROUTER는 등록하지 않으면
    # resolve()가 자연히 걸러낸다(백엔드가 None이면 스킵) — 최소 구성으로 실제
    # 라우팅 경로를 태운다.
    r = router_mod.Router(backends={BackendName.CLAUDE_CLI: backend}, now=lambda: elapsed["t"])

    with patch.object(router_mod.asyncio, "sleep", _fake_sleep):
        with pytest.raises(LLMAllBackendsFailed) as exc_info:
            await r.generate(_msgs(), task=TaskType.GROUP_CHAT)

    # 신선도 상한까지 실제로 대기했다 — 서킷 개방으로 조기에 "체인 없음"으로 끊기지
    # 않았다는 뜻이다.
    assert "usage limit outlasted" in str(exc_info.value)
    assert elapsed["t"] >= router_mod._USAGE_LIMIT_WAIT_SECONDS
    assert elapsed["t"] < router_mod._USAGE_LIMIT_WAIT_SECONDS + 2 * router_mod._USAGE_LIMIT_RETRY_INTERVAL

    # 서킷은 이 한 번의 generate() 호출 동안 딱 1회만 charge됐다 — 재시도 패스가
    # 여러 번(계산상 15회) 있었는데도 threshold=3 미만이라 계속 closed였다.
    breaker = r._breakers[BackendName.CLAUDE_CLI]
    assert breaker._fails == 1
    assert breaker.allow() is True

    # 실제로 여러 패스가 돌았다(재시도가 일어났다는 증거) — charge는 1회여도 시도
    # 자체는 반복됐다.
    assert backend.calls > 1
