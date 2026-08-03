"""CLI 백엔드가 실패 사유를 잃지 않는지 — 2026-08-03 라이브 장애 회귀 방지.

`claude`/`codex` CLI는 `--output-format json`에서 실패해도 stdout에 사유를 쓰고
stderr는 비운다. 백엔드가 stderr만 읽으면 `claude exited 1: `처럼 사유가 비어
나가고, `_RATE_MARKERS`의 "usage limit"이 매칭될 기회조차 없어진다.

실제 CLI는 절대 호출하지 않는다 — 사용자의 실제 사용량을 소비한다. run_cli를 mock한다.
"""
from unittest.mock import AsyncMock, patch

import pytest

from agents.llm.backends.base import (
    BackendError,
    BackendTransientError,
    BackendUsageLimitError,
)
from agents.llm.backends.claude_cli import ClaudeCLIBackend
from agents.llm.backends.codex_cli import CodexCLIBackend

_LIMIT_JSON = (
    '{"is_error":true,"result":"Claude usage limit reached. '
    'Your limit will reset at 3pm."}'
)


def _messages():
    from langchain_core.messages import HumanMessage

    return [HumanMessage(content="hi")]


class TestUsageLimitExceptionShape:
    def test_usage_limit_is_a_transient_error(self):
        """라우터의 기존 transient 처리(2배 쿨다운)를 그대로 받으려면 하위 타입이어야 한다."""
        assert issubclass(BackendUsageLimitError, BackendTransientError)
        assert issubclass(BackendUsageLimitError, BackendError)


class TestClaudeStdoutCapture:
    @pytest.mark.asyncio
    async def test_reason_from_stdout_survives_when_stderr_empty(self):
        backend = ClaudeCLIBackend()
        with patch(
            "agents.llm.backends.claude_cli.run_cli",
            AsyncMock(return_value=(1, _LIMIT_JSON, "")),
        ):
            with pytest.raises(BackendError) as ei:
                await backend.generate(_messages())

        assert "usage limit" in str(ei.value).lower()

    @pytest.mark.asyncio
    async def test_usage_limit_classified_as_usage_limit_error(self):
        backend = ClaudeCLIBackend()
        with patch(
            "agents.llm.backends.claude_cli.run_cli",
            AsyncMock(return_value=(1, _LIMIT_JSON, "")),
        ):
            with pytest.raises(BackendUsageLimitError):
                await backend.generate(_messages())

    @pytest.mark.asyncio
    async def test_non_limit_failure_is_not_usage_limit(self):
        """모델 부재 같은 영구 오류가 한도로 오분류되면 라우터가 헛되이 기다린다."""
        payload = '{"is_error":true,"result":"There is an issue with the selected model."}'
        backend = ClaudeCLIBackend()
        with patch(
            "agents.llm.backends.claude_cli.run_cli",
            AsyncMock(return_value=(1, payload, "")),
        ):
            with pytest.raises(BackendError) as ei:
                await backend.generate(_messages())

        assert not isinstance(ei.value, BackendUsageLimitError)
        assert "selected model" in str(ei.value)


class TestCodexStdoutCapture:
    @pytest.mark.asyncio
    async def test_usage_limit_classified_as_usage_limit_error(self):
        backend = CodexCLIBackend()
        with patch(
            "agents.llm.backends.codex_cli.run_cli",
            AsyncMock(return_value=(1, "usage limit reached", "")),
        ):
            with pytest.raises(BackendUsageLimitError):
                await backend.generate(_messages())
