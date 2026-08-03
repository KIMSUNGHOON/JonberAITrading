"""`/api/llm/stats`의 healthy가 실제 호출 결과를 반영하는지 — 2026-08-03 회귀 방지.

부팅 1회 프로브만으로는 장애 중에도 healthy: true가 유지된다. 실제 관측된 증상이
그것이었다. 합성 프로브를 늘리는 대신(할당량을 더 쓰게 된다) 라우터가 이미 아는
실제 호출 성패로 표시를 만든다.

실제 CLI는 호출하지 않는다. 이 디렉터리를 통째로 돌릴 때는 반드시 `-m "not slow"`.
"""
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from agents.llm import router as router_mod
from agents.llm.backends.base import BackendError, LLMAllBackendsFailed, LLMBackend
from agents.llm.tasks import BackendName, TaskType


class _Backend(LLMBackend):
    def __init__(self, name, *, error=None, result="ok"):
        self.name = name
        self._error = error
        self._result = result
        self.supports_stream = False
        self.supports_schema = True
        self.calls = 0

    async def generate(self, messages, *, temperature=None, max_tokens=None, response_schema=None):
        self.calls += 1
        if self._error:
            raise self._error
        return self._result

    async def health(self):
        return True


def _msgs():
    return [HumanMessage(content="hi")]


@pytest.mark.asyncio
async def test_success_marks_backend_healthy():
    backend = _Backend(BackendName.CLAUDE_CLI)
    r = router_mod.Router()
    with patch.object(r, "resolve", return_value=[backend]):
        await r.generate(_msgs(), task=TaskType.GENERAL)

    assert r.snapshot()["backends"][BackendName.CLAUDE_CLI.value]["healthy"] is True


@pytest.mark.asyncio
async def test_failure_marks_backend_unhealthy():
    """부팅 때 healthy였어도 실제 호출이 실패하면 표시가 따라가야 한다."""
    backend = _Backend(BackendName.CLAUDE_CLI, error=BackendError("boom"))
    r = router_mod.Router()
    r._health_cache[BackendName.CLAUDE_CLI] = True  # 부팅 프로브가 남긴 값
    with patch.object(r, "resolve", return_value=[backend]):
        with pytest.raises(LLMAllBackendsFailed):
            await r.generate(_msgs(), task=TaskType.GENERAL)

    assert r.snapshot()["backends"][BackendName.CLAUDE_CLI.value]["healthy"] is False


@pytest.mark.asyncio
async def test_recovery_flips_back_to_healthy():
    """실패로 False가 된 뒤에도 다시 호출돼 성공하면 True로 돌아와야 한다.
    resolve()가 healthy False를 게이트로 쓰면 여기서 데드락이 난다."""
    ok = _Backend(BackendName.CLAUDE_CLI)
    r = router_mod.Router()
    r._health_cache[BackendName.CLAUDE_CLI] = False  # 직전 실패가 남긴 값
    with patch.object(r, "resolve", return_value=[ok]):
        await r.generate(_msgs(), task=TaskType.GENERAL)

    assert ok.calls == 1
    assert r.snapshot()["backends"][BackendName.CLAUDE_CLI.value]["healthy"] is True


def test_resolve_does_not_gate_on_health_cache():
    """게이트는 서킷 브레이커 하나뿐이다. health는 순수 관측용 표시다."""
    import inspect

    src = inspect.getsource(router_mod.Router.resolve)
    assert "_health_cache" not in src


def test_resolve_still_gates_on_the_circuit_breaker():
    """게이트를 지웠다가 브레이커까지 같이 지우면 백오프가 사라진다."""
    import inspect

    src = inspect.getsource(router_mod.Router.resolve)
    assert "_breakers" in src and "allow()" in src


@pytest.mark.asyncio
async def test_startup_probes_both_claude_instances():
    """전략용 opus에 걸린 한도가 관측 대상 밖이면 안 된다.

    router.py는 ClaudeCLIBackend/CodexCLIBackend를 모듈 전역이 아니라
    `_build_from_settings()` 안에서 지역 임포트하므로 `router_mod.ClaudeCLIBackend`는
    존재하지 않는다 — 실제 정의 모듈에서 클래스를 가져와 패치해야 한다.
    CodexCLIBackend는 OPENROUTER_API_KEY 유무와 무관하게 항상 구성되고 그
    `health()`는 실제 `codex` CLI를 서브프로세스로 띄운다(이 환경의 PATH에
    `codex`가 실재한다) — 패치하지 않으면 이 순수 유닛 테스트가 실 사용량을
    태운다. OpenAICompatBackend(OPENROUTER/LOCAL)도 방어적으로 막아, 셸에
    OPENROUTER_API_KEY가 남아 있는 환경에서 돌려도 실 HTTP를 타지 않게 한다.
    """
    from agents.llm.backends.claude_cli import ClaudeCLIBackend
    from agents.llm.backends.codex_cli import CodexCLIBackend
    from agents.llm.backends.openai_compat import OpenAICompatBackend

    r = router_mod.Router()
    probed = []

    async def _probe(self):
        probed.append(self.model)
        return True

    with patch.object(ClaudeCLIBackend, "health", _probe), \
            patch.object(CodexCLIBackend, "health", AsyncMock(return_value=True)), \
            patch.object(OpenAICompatBackend, "health", AsyncMock(return_value=True)):
        await r.startup()

    assert len(set(probed)) >= 2, f"claude 인스턴스가 하나만 프로브됐다: {probed}"
