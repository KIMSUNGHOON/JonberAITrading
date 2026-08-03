"""LLM 장애를 운영자에게 알리는지 — 2026-08-03에는 아무 통지도 가지 않았다.

감시 주기가 1분이라 래치가 없으면 장애 지속 동안 매분 발송된다. 원인별 1회만
보내고, 해소되면 래치를 풀어 재발 시 다시 알린다.
"""
import asyncio
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

    # 키 형식이 바뀌어도(안정화 축약) 의미가 유지되도록 집합 자체가 비었는지를 본다 —
    # 원문 부분문자열 `not in`은 키가 무엇이든 항상 참이라 회귀를 못 잡는다.
    assert coord_mod._LLM_FAILURE_NOTIFIED == set()


@pytest.mark.asyncio
async def test_concurrent_calls_with_same_cause_send_once():
    """TOCTOU regression: LLMAllBackendsFailed is keyed on task + last error
    (agents/llm/router.py), so multiple tickers failing because every LLM
    backend died share an identical cause string, and the coordinator runs
    discussions concurrently per ticker (asyncio.create_task). Two coroutines
    racing on the same cause must not both pass the dedup check before
    either confirms delivery — that would fan one outage out into one
    Telegram message per concurrently-failing ticker.

    The send mock does a real `await asyncio.sleep(0)` to force a yield
    between the dedup-check/claim and the confirmed send, deterministically
    reproducing the interleaving without relying on wall-clock timing.
    """
    notifier = _notifier()

    async def _yielding_send(*args, **kwargs):
        await asyncio.sleep(0)
        return True

    notifier.send_system_status = AsyncMock(side_effect=_yielding_send)
    coord_mod._LLM_FAILURE_NOTIFIED.clear()
    with patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
        await asyncio.gather(
            coord_mod._alert_llm_failure("005930", LLMAllBackendsFailed("usage limit reached")),
            coord_mod._alert_llm_failure("000660", LLMAllBackendsFailed("usage limit reached")),
        )

    assert notifier.send_system_status.await_count == 1


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


# -------------------------------------------------------------------------
# 사이트 B — `start_manual_discussion(wait=True)`. 실 포지션에 가장 가까운
# 경로인데 여기만 알림 배선이 없었다.
#
# 원래 판단은 "예외가 HTTP 호출자에게 그대로 가니 알림이 필요 없다"였는데,
# 실제 호출자를 세어 보면 전제가 틀렸다:
#   - `app/api/routes/agent_chat.py:320` — `wait`를 넘기지 않는다 → 사이트 C
#     (백그라운드) 경로로 간다.
#   - `services/agent_chat/position_manager.py:1232` — 프로덕션의 유일한
#     wait=True 호출자. 그 except는 `position_discussion_failed` 로그 한 줄뿐이다.
# 즉 익절·손절임박·큰손실·전략재평가 토론이 LLM 장애로 죽으면 운영자에게 아무
# 통지도 가지 않았다.
# -------------------------------------------------------------------------


class _FailingRoom:
    """`room.start()`가 정해진 예외를 내는 가짜 룸 — 사이트 A/C 배선 테스트와
    같은 방식으로 **실제 호출부**를 태운다."""

    def __init__(self, exc, **kwargs):
        self._exc = exc
        self.ticker = kwargs.get("ticker", "005930")
        self.stock_name = kwargs.get("stock_name", "삼성전자")
        self.session = MagicMock(name="cancelled_session")

    def on_status_change(self, callback):  # 코디네이터가 부를 수 있다
        pass

    async def start(self):
        raise self._exc


def _wait_true_harness(exc):
    """`start_manual_discussion(wait=True)`를 실제로 태우기 위한 최소 배선."""
    context = MagicMock()
    context.is_stale = False
    context.consensus_threshold = 0.75

    coordinator = ChatCoordinator()
    patches = [
        patch("services.agent_chat.coordinator.ChatRoom", lambda **kw: _FailingRoom(exc, **kw)),
        patch("services.agent_chat.coordinator._fire_room_created", MagicMock()),
        patch("services.agent_chat.coordinator._register_sm_discussion", AsyncMock()),
        patch("services.agent_chat.coordinator.persist_session", AsyncMock()),
        patch.object(coordinator, "_fetch_market_context", AsyncMock(return_value=context)),
        patch.object(coordinator, "_compute_agent_weights", AsyncMock(return_value=None)),
    ]
    return coordinator, patches


@pytest.mark.asyncio
async def test_site_b_wait_true_alerts_and_reraises():
    """사이트 A/C와 달리 이 경로의 계약은 **전파**다(호출자가 session.decision을
    읽는다). 알리고 다시 던져야 한다 — 삼키면 PositionManager가 "결정 없음"을
    정상 결과로 오해할 수 있다."""
    exc = LLMAllBackendsFailed("usage limit reached")
    coordinator, patches = _wait_true_harness(exc)

    with patch("services.agent_chat.coordinator._alert_llm_failure", AsyncMock()) as mock_alert:
        for p in patches:
            p.start()
        try:
            with pytest.raises(LLMAllBackendsFailed):
                await coordinator.start_manual_discussion(
                    ticker="005930", stock_name="삼성전자", wait=True
                )
        finally:
            for p in reversed(patches):
                p.stop()

    mock_alert.assert_awaited_once_with("005930", exc)
    # finally가 raise 경로에서도 계속 동작해야 한다 — 남아 있으면 그 종목은
    # "이미 토론 중"으로 영구히 막힌다.
    assert "005930" not in coordinator._active_rooms


@pytest.mark.asyncio
async def test_site_b_pops_active_room_on_cancellation_without_alerting():
    """취소는 LLM 장애가 아니다 — 알리지 않고 전파하되, `_active_rooms`는
    반드시 비워져야 한다(락업 방지)."""
    coordinator, patches = _wait_true_harness(asyncio.CancelledError())

    with patch("services.agent_chat.coordinator._alert_llm_failure", AsyncMock()) as mock_alert:
        for p in patches:
            p.start()
        try:
            with pytest.raises(asyncio.CancelledError):
                await coordinator.start_manual_discussion(
                    ticker="005930", stock_name="삼성전자", wait=True
                )
        finally:
            for p in reversed(patches):
                p.stop()

    mock_alert.assert_not_awaited()
    assert "005930" not in coordinator._active_rooms


@pytest.mark.asyncio
async def test_site_b_success_path_clears_latch_and_returns_session():
    """성공 경로가 회귀하지 않는지 — 예외 처리를 끼워 넣으면서 정상 반환·래치
    해제가 깨지지 않았음을 같이 못박는다."""
    session = MagicMock(name="decided_session")

    class _OkRoom(_FailingRoom):
        async def start(self):
            return session

    context = MagicMock()
    context.is_stale = False
    context.consensus_threshold = 0.75
    coordinator = ChatCoordinator()

    with patch("services.agent_chat.coordinator.ChatRoom", lambda **kw: _OkRoom(None, **kw)), \
            patch("services.agent_chat.coordinator._fire_room_created", MagicMock()), \
            patch("services.agent_chat.coordinator._register_sm_discussion", AsyncMock()), \
            patch("services.agent_chat.coordinator.persist_session", AsyncMock()) as mock_persist, \
            patch("services.agent_chat.coordinator.clear_llm_failure_latch") as mock_clear, \
            patch.object(coordinator, "_fetch_market_context", AsyncMock(return_value=context)), \
            patch.object(coordinator, "_compute_agent_weights", AsyncMock(return_value=None)):
        returned = await coordinator.start_manual_discussion(
            ticker="005930", stock_name="삼성전자", wait=True
        )

    assert returned is session
    mock_clear.assert_called_once()
    mock_persist.assert_awaited_once_with(session)
    assert "005930" not in coordinator._active_rooms


# -------------------------------------------------------------------------
# 래치의 두 결함 — (a) 취소로 wedge, (b) 키 불안정
# -------------------------------------------------------------------------


class TestLatchSurvivesCancellation:
    """(a) back-out이 `except Exception` 안에 있으면 `asyncio.CancelledError`
    (3.8부터 BaseException)를 못 잡는다. 토론 태스크가 통지 중에 취소되면 claim만
    남고 메시지는 안 나간 채 그 사유가 **영구히** 래치돼, 같은 원인의 이후 장애가
    다음 성공 토론까지 통째로 침묵한다."""

    @pytest.mark.asyncio
    async def test_cancel_while_sending_backs_out_and_still_propagates(self):
        notifier = _notifier()
        started = asyncio.Event()

        async def _hanging_send(*args, **kwargs):
            started.set()
            await asyncio.sleep(3600)
            return True

        notifier.send_system_status = AsyncMock(side_effect=_hanging_send)
        coord_mod._LLM_FAILURE_NOTIFIED.clear()

        with patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
            task = asyncio.create_task(
                coord_mod._alert_llm_failure("005930", LLMAllBackendsFailed("usage limit reached"))
            )
            await started.wait()
            # 발송 도중이므로 claim은 이미 잡혀 있다 — 바로 이 상태에서 취소한다.
            assert coord_mod._LLM_FAILURE_NOTIFIED
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task   # 취소는 삼키지 않고 전파돼야 한다

        assert coord_mod._LLM_FAILURE_NOTIFIED == set(), (
            "취소로 발송이 무산됐는데 claim이 남았다 — 같은 사유의 장애가 영구히 침묵한다"
        )

    @pytest.mark.asyncio
    async def test_cancel_while_resolving_notifier_backs_out_too(self):
        """`get_telegram_notifier()` 안에서 취소되는 경우도 같다."""
        started = asyncio.Event()

        async def _hanging_notifier():
            started.set()
            await asyncio.sleep(3600)

        coord_mod._LLM_FAILURE_NOTIFIED.clear()
        with patch("services.telegram.get_telegram_notifier", _hanging_notifier):
            task = asyncio.create_task(
                coord_mod._alert_llm_failure("005930", LLMAllBackendsFailed("usage limit reached"))
            )
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert coord_mod._LLM_FAILURE_NOTIFIED == set()

    @pytest.mark.asyncio
    async def test_notifier_not_ready_backs_out(self):
        """조용한 실패 경로(`is_ready` False)도 `finally`로 옮긴 뒤 그대로인지."""
        notifier = _notifier()
        notifier.is_ready = False
        coord_mod._LLM_FAILURE_NOTIFIED.clear()
        with patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
            await coord_mod._alert_llm_failure("005930", LLMAllBackendsFailed("usage limit"))

        assert coord_mod._LLM_FAILURE_NOTIFIED == set()


class TestLatchKeyIsStable:
    """(b) 키가 `str(exc)[:160]`이면 호출마다 달라지는 값 하나로 dedup이 통째로
    무너져 "실패한 토론마다 매분 Telegram"이 된다 — 메모리 증가보다 나쁘다.

    실제로 그 160자 안에 들어오는 변동 요소가 셋이다: 대기 상한 숫자(토론 예산이
    붙으면서 300 고정이 아니게 됐다), task 이름(토론 1건이 단계마다 다른 task로
    LLM을 약 15회 부른다), CLI 원문 blob(한도 리셋 시각 등).
    """

    @staticmethod
    def _give_up(cap: int, task: str, reset_epoch: int) -> LLMAllBackendsFailed:
        """라우터가 실제로 만드는 give-up 메시지 모양 그대로."""
        return LLMAllBackendsFailed(
            f"usage limit outlasted the {cap}s freshness cap for task '{task}': "
            f"claude exited 1: Claude AI usage limit reached|{reset_epoch}"
        )

    @pytest.mark.asyncio
    async def test_same_outage_with_varying_numbers_and_task_alerts_once(self):
        notifier = _notifier()
        coord_mod._LLM_FAILURE_NOTIFIED.clear()
        with patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
            await coord_mod._alert_llm_failure("005930", self._give_up(300, "group_chat", 1754236800))
            await coord_mod._alert_llm_failure("000660", self._give_up(60, "technical_analysis", 1754240400))
            await coord_mod._alert_llm_failure("089860", self._give_up(0, "risk_assessment", 1754244000))

        assert notifier.send_system_status.await_count == 1
        assert len(coord_mod._LLM_FAILURE_NOTIFIED) == 1

    @pytest.mark.asyncio
    async def test_genuinely_different_causes_still_get_their_own_alert(self):
        """합쳐도 되는 것만 합쳐야 한다 — 성격이 다른 장애는 각자 알림을 받는다."""
        notifier = _notifier()
        coord_mod._LLM_FAILURE_NOTIFIED.clear()
        with patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
            await coord_mod._alert_llm_failure("005930", self._give_up(300, "group_chat", 1754236800))
            await coord_mod._alert_llm_failure("005930", LLMAllBackendsFailed("no available backend for task 'group_chat'"))
            await coord_mod._alert_llm_failure("005930", LLMAllBackendsFailed("all backends failed for task 'group_chat': logged out"))

        assert notifier.send_system_status.await_count == 3

    @pytest.mark.asyncio
    async def test_message_body_keeps_the_full_reason_not_the_shortened_key(self):
        """키는 축약하되 **본문**은 사유 전문(160자)을 유지해야 한다 — 축약이
        운영자에게 보이는 정보까지 깎으면 안 된다."""
        notifier = _notifier()
        coord_mod._LLM_FAILURE_NOTIFIED.clear()
        with patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
            await coord_mod._alert_llm_failure("005930", self._give_up(300, "group_chat", 1754236800))

        body = " ".join(str(a) for a in notifier.send_system_status.await_args.args)
        assert "Claude AI usage limit reached|1754236800" in body
        assert "group_chat" in body

    @pytest.mark.asyncio
    async def test_latch_size_is_hard_bounded(self):
        """키를 안정화해도 메모리 상한은 무조건적으로 건다."""
        notifier = _notifier()
        coord_mod._LLM_FAILURE_NOTIFIED.clear()
        with patch("services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)):
            for i in range(coord_mod._LLM_FAILURE_NOTIFIED_MAX * 2):
                await coord_mod._alert_llm_failure(
                    "005930", LLMAllBackendsFailed(f"distinct-shape-{chr(97 + i % 26)}{'x' * (i % 30)} failure")
                )

        assert len(coord_mod._LLM_FAILURE_NOTIFIED) <= coord_mod._LLM_FAILURE_NOTIFIED_MAX
