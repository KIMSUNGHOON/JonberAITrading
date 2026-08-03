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
import asyncio
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


class _SimulatedHangSignal(Exception):
    """`_HangingBackend`가 즉시 내는 표시용 예외 — 실제로 기다리지 않는다.
    `_fake_wait_for`가 이 신호를 가로채 `timeout` 인자만큼 공유 가짜 시계를
    전진시킨 뒤 `asyncio.TimeoutError`로 바꿔치기한다. 이렇게 하면 "백엔드가
    타임아웃까지 행(hang)했다"를 실제 wall-clock 대기 없이, 라우터가 clamp한
    `timeout` 값까지 정확히 반영해 재현할 수 있다."""


class _HangingBackend(LLMBackend):
    """항상 `_SimulatedHangSignal`을 즉시 던진다 — `_fake_wait_for`와 짝을 이뤄
    "행(hang)하다가 라우터의 clamp된 타임아웃에 걸려 잘린 백엔드"를 흉내낸다."""

    def __init__(self, name):
        self.name = name
        self.supports_stream = False
        self.supports_schema = True
        self.calls = 0

    async def generate(self, messages, *, temperature=None, max_tokens=None, response_schema=None):
        self.calls += 1
        raise _SimulatedHangSignal()

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


@pytest.mark.asyncio
async def test_gives_up_with_usage_limit_reason_when_clamp_cuts_pass_short(monkeypatch):
    """2026-08-03 리뷰 라운드 2 Finding 재현: 체인의 앞쪽 백엔드가 행(hang)하다가
    클램프된 타임아웃에 걸리면, 남은 예산이 0이 돼 뒤쪽(진짜 usage-limited) 백엔드는
    시도조차 못 하고 패스가 잘린다. 이때도 give-up이 "빈 사유"가 아니라 애초에
    대기를 시작하게 만든 usage-limit 사유로, `llm_usage_limit_gave_up`이 찍히는
    경로로 나가야 한다(라운드 1 수정 직후엔 `all backends failed ...: `처럼 빈
    사유로 퇴화하는 회귀가 있었다 — 리뷰어가 read-only 프로브로 실측).

    실제 wall-clock 대기 없이 재현하려고 `asyncio.wait_for` 자체를 가짜로 바꾼다:
    `_HangingBackend`가 `_SimulatedHangSignal`을 즉시 내면, 가짜 wait_for가 그걸
    보고 라우터가 넘긴 `timeout`(=클램프된 값)만큼 공유 시계를 전진시킨 뒤
    `asyncio.TimeoutError`를 낸다 — 실제 타임아웃이 "그만큼 걸렸다"는 관측 가능한
    효과만 재현하고, 실제로는 기다리지 않는다.
    """
    # 타임아웃을 이 테스트 안에서 고정한다(코드 기본값과 동일한 값) — `.env`가
    # LLM_TIMEOUT을 건드려도 재현 시나리오(2패스째에 정확히 클램프가 걸리는 것)가
    # 깨지지 않게 한다. 클램프가 실제로 걸리려면 OPENROUTER의 무클램프 타임아웃이
    # `CAP - RETRY_INTERVAL`(=280) 이상이어야 한다 — 300은 이를 만족한다.
    monkeypatch.setattr(settings, "LLM_TIMEOUT", 300, raising=False)
    monkeypatch.setattr(settings, "LLM_CLI_TIMEOUT", 180, raising=False)

    elapsed = {"t": 0.0}

    async def _fake_sleep(sec):
        elapsed["t"] += sec

    async def _fake_wait_for(coro, timeout):
        try:
            return await coro
        except _SimulatedHangSignal:
            elapsed["t"] += timeout
            raise asyncio.TimeoutError("simulated hang")

    hang = _HangingBackend(BackendName.OPENROUTER)
    limited = _Backend(
        BackendName.CLAUDE_CLI,
        error=BackendUsageLimitError("claude exited 1: usage limit reached"),
    )

    # SENTIMENT_ANALYSIS 체인은 [OPENROUTER, CLAUDE_CLI] — 리뷰어의 원 프로브와
    # 동일한 순서/구성. `resolve()`를 고정 패치해 매 패스 같은 체인을 낸다.
    r = router_mod.Router(now=lambda: elapsed["t"])
    with patch.object(r, "resolve", return_value=[hang, limited]), \
         patch.object(router_mod.asyncio, "sleep", _fake_sleep), \
         patch.object(router_mod.asyncio, "wait_for", _fake_wait_for):
        with pytest.raises(LLMAllBackendsFailed) as exc_info:
            await r.generate(_msgs(), task=TaskType.SENTIMENT_ANALYSIS)

    # 회귀 지점: 메시지가 "all backends failed ...: "(last가 TimeoutError라 빈
    # 사유)로 퇴화하지 않고, usage-limit 사유를 담은 give-up 메시지여야 한다.
    msg = str(exc_info.value)
    assert "usage limit outlasted" in msg
    assert "usage limit reached" in msg

    # 패스가 클램프로 잘려 CLAUDE_CLI가 마지막 패스에서는 시도되지 못했다는 증거:
    # OPENROUTER(행)는 매 패스 시도되지만 CLAUDE_CLI는 그보다 적게 호출된다.
    assert hang.calls > limited.calls
    assert limited.calls >= 1   # 첫 패스에서는 usage limit이 실제로 확인됐다

    # 대기 "지속시간" 자체(300초)는 라운드 2에서도 정상이지만, 이 시나리오의 총
    # 경과는 300초가 아니다 — 데드라인이 "1패스가 끝난 뒤"에야 잡히는데, 그 1패스
    # 자체가 행 때문에 무클램프 LLM_TIMEOUT(=300)만큼 걸렸다. 이건 이번 라운드에서
    # 손대지 않기로 한 잔여 사항(코디네이터 residual 1)의 산술적 귀결이지 새 결함이
    # 아니다 — 정확한 값으로 못박아 둔다: 1패스(무클램프 행) + CAP(300).
    expected_total = settings.LLM_TIMEOUT + router_mod._USAGE_LIMIT_WAIT_SECONDS
    assert elapsed["t"] == pytest.approx(expected_total)
