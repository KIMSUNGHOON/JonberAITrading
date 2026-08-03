"""LLM 장애를 운영자에게 알리는지 — 2026-08-03에는 아무 통지도 가지 않았다.

감시 주기가 1분이라 래치가 없으면 장애 지속 동안 매분 발송된다. 원인별 1회만
보내고, 해소되면 래치를 풀어 재발 시 다시 알린다.
"""
from unittest.mock import AsyncMock, patch

import pytest

from agents.llm.backends.base import LLMAllBackendsFailed
from services.agent_chat import coordinator as coord_mod


def _notifier():
    n = AsyncMock()
    n.is_ready = True
    n.send_system_status = AsyncMock(return_value=True)
    return n


@pytest.mark.asyncio
async def test_alerts_once_per_cause():
    notifier = _notifier()
    coord_mod._LLM_FAILURE_NOTIFIED.clear()
    with patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
        await coord_mod._alert_llm_failure("005930", LLMAllBackendsFailed("usage limit reached"))
        await coord_mod._alert_llm_failure("000660", LLMAllBackendsFailed("usage limit reached"))

    assert notifier.send_system_status.await_count == 1


@pytest.mark.asyncio
async def test_latch_clears_and_realerts_after_recovery():
    notifier = _notifier()
    coord_mod._LLM_FAILURE_NOTIFIED.clear()
    with patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
        await coord_mod._alert_llm_failure("005930", LLMAllBackendsFailed("usage limit reached"))
        coord_mod.clear_llm_failure_latch()
        await coord_mod._alert_llm_failure("005930", LLMAllBackendsFailed("usage limit reached"))

    assert notifier.send_system_status.await_count == 2


@pytest.mark.asyncio
async def test_message_names_the_cause():
    notifier = _notifier()
    coord_mod._LLM_FAILURE_NOTIFIED.clear()
    with patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
        await coord_mod._alert_llm_failure("005930", LLMAllBackendsFailed("usage limit reached"))

    text = " ".join(str(a) for a in notifier.send_system_status.await_args.args)
    text += " " + " ".join(str(v) for v in notifier.send_system_status.await_args.kwargs.values())
    assert "usage limit" in text.lower()


@pytest.mark.asyncio
async def test_never_raises_when_notifier_explodes():
    coord_mod._LLM_FAILURE_NOTIFIED.clear()
    with patch("services.telegram.get_telegram_notifier", AsyncMock(side_effect=RuntimeError("boom"))):
        await coord_mod._alert_llm_failure("005930", LLMAllBackendsFailed("usage limit"))
