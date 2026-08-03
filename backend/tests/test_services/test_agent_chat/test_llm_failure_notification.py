"""LLM 장애를 운영자에게 알리는지 — 2026-08-03에는 아무 통지도 가지 않았다.

감시 주기가 1분이라 래치가 없으면 장애 지속 동안 매분 발송된다. 원인별 1회만
보내고, 해소되면 래치를 풀어 재발 시 다시 알린다.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.llm.backends.base import LLMAllBackendsFailed
from services.agent_chat import coordinator as coord_mod
from services.agent_chat.coordinator import ChatCoordinator


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


@pytest.mark.asyncio
async def test_latch_not_set_when_send_returns_false():
    """send_system_status can return False without raising (config off,
    uninitialized bot, TimedOut/NetworkError/Forbidden — see service.py's
    _send_message). If the latch were set before delivery is confirmed, a
    transient send failure would permanently eat that cause's only alert.
    """
    notifier = _notifier()
    notifier.send_system_status = AsyncMock(return_value=False)
    coord_mod._LLM_FAILURE_NOTIFIED.clear()
    with patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
        await coord_mod._alert_llm_failure("005930", LLMAllBackendsFailed("usage limit reached"))

    assert "usage limit reached" not in coord_mod._LLM_FAILURE_NOTIFIED


# -------------------------------------------------------------------------
# Wiring tests — drive the real coordinator call sites (A: the auto
# watch-list path that actually failed on 2026-08-03, C: the manual
# background path), not `_alert_llm_failure` in isolation. Without these,
# deleting the `isinstance(e, LLMAllBackendsFailed)` guard at either site,
# or a `clear_llm_failure_latch()` call, leaves the whole suite green.
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_site_a_run_discussion_alerts_and_does_not_propagate():
    """_run_discussion (coordinator.py, the auto watch-list path) must
    alert and swallow — it's a background task; re-raising would surface
    as an unhandled task exception and kill unattended operation."""
    coordinator = ChatCoordinator()
    exc = LLMAllBackendsFailed("usage limit reached")
    room = AsyncMock()
    room.start = AsyncMock(side_effect=exc)

    with patch("services.agent_chat.coordinator._alert_llm_failure", AsyncMock()) as mock_alert:
        await coordinator._run_discussion("005930", room)  # must not raise

    mock_alert.assert_awaited_once_with("005930", exc)


@pytest.mark.asyncio
async def test_site_c_run_manual_discussion_alerts_persists_and_does_not_propagate():
    """_run_manual_discussion (coordinator.py, manual background path) must
    alert, swallow, AND still call persist_session(room.session) — that call
    is the recovery that keeps the session id /discuss already handed out
    from dangling as a permanent 404. Re-raising to alert would skip it."""
    coordinator = ChatCoordinator()
    exc = LLMAllBackendsFailed("usage limit reached")
    room = AsyncMock()
    room.start = AsyncMock(side_effect=exc)
    room.session = MagicMock(name="cancelled_session")

    with patch("services.agent_chat.coordinator._alert_llm_failure", AsyncMock()) as mock_alert, \
            patch("services.agent_chat.coordinator.persist_session", AsyncMock()) as mock_persist:
        await coordinator._run_manual_discussion("005930", room)  # must not raise

    mock_alert.assert_awaited_once_with("005930", exc)
    mock_persist.assert_awaited_once_with(room.session)


@pytest.mark.asyncio
async def test_site_a_success_path_clears_latch():
    """A completed discussion is the observable proof the LLM recovered —
    every call site must clear the latch on success, not just alert on
    failure."""
    coordinator = ChatCoordinator()
    session = MagicMock()
    session.decision = None  # skip _handle_decision — irrelevant here
    room = AsyncMock()
    room.start = AsyncMock(return_value=session)

    with patch("services.agent_chat.coordinator.persist_session", AsyncMock()), \
            patch("services.agent_chat.coordinator.clear_llm_failure_latch") as mock_clear:
        await coordinator._run_discussion("005930", room)

    mock_clear.assert_called_once()
