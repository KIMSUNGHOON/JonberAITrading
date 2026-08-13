"""헬스 프로브가 실제 사용 모델을 쓰는지 — 2026-08-03 라이브 장애 회귀 방지.

haiku로 프로브하고 sonnet으로 호출하면, 모델·플랜 단위 한도가 프로브를 통과해
`/api/llm/stats`가 healthy: true를 보고하는 동안 전 호출이 실패한다.

실제 CLI는 호출하지 않는다 — run_cli를 mock한다.
"""
from unittest.mock import AsyncMock, patch

import pytest

from agents.llm.backends.claude_cli import ClaudeCLIBackend

_OK = '{"subtype":"success","is_error":false,"result":"ok"}'


@pytest.mark.asyncio
async def test_health_probes_the_configured_model():
    backend = ClaudeCLIBackend(model="sonnet")
    runner = AsyncMock(return_value=(0, _OK, ""))
    with patch("agents.llm.backends.claude_cli.run_cli", runner):
        assert await backend.health() is True

    argv = runner.await_args.args[0]
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert "haiku" not in argv


@pytest.mark.asyncio
async def test_health_follows_a_different_configured_model():
    """모델을 바꿔 넣으면 프로브도 따라가야 한다 — 하드코딩이 남아 있으면 여기서 걸린다."""
    backend = ClaudeCLIBackend(model="opus")
    runner = AsyncMock(return_value=(0, _OK, ""))
    with patch("agents.llm.backends.claude_cli.run_cli", runner):
        await backend.health()

    argv = runner.await_args.args[0]
    assert argv[argv.index("--model") + 1] == "opus"


@pytest.mark.asyncio
async def test_health_false_on_nonzero_exit():
    backend = ClaudeCLIBackend(model="sonnet")
    with patch(
        "agents.llm.backends.claude_cli.run_cli",
        AsyncMock(return_value=(1, "", "boom")),
    ):
        assert await backend.health() is False
