"""통지 광역화 최종 전체 브랜치 리뷰 Important 2 + 보너스: 방어청산 경로의
"경로"(source) 라벨링과 _execute_reduce_position의 실패 통지 누락.

Important 2: `trading_coord._close_position`/`_reduce_position`이 호출자와
무관하게 `reason`을 각각 "User-initiated close"/"Autonomous partial reduce"로
하드코딩했다 — PositionManager의 자율 손절/익절 청산(`_execute_close_position`)이
이 두 메서드를 거치므로, 이 아크가 드러내려던 07-24 손절·07-27 익절 체결이
전부 폰에 "사람이 한 것"으로 표시됐다(스펙 A2: 자율/승인/방어청산 구분).

수정: `_close_position`/`_reduce_position`에 `reason` 파라미터를 추가하고
(미전달 시 기존 하드코딩 문자열로 폴백 — `handle_alert_action`의 진짜 사람
조작 CLOSE_POSITION은 그대로), PositionManager가 자신이 이미 갖고 있던
`reason` 상수("stop_loss"/"take_profit"/"agent_decision"/
"agent_decision_reduce"/"agent_decision_reduce_partial")를
`_EXIT_REASON_TO_SOURCE_LABEL`로 사람이 읽을 표시 문자열로 매핑해 넘긴다.

보너스(Important 4와 같은 결의 갭, 명시적 리뷰 대상은 아니었으나 형제
메서드라 값싸게 닫는다): `_execute_close_position`은 Task 7에서
`_alert_execution_failed`를 자기 except에 달았지만, 정확히 같은 모양인
`_execute_reduce_position`의 except는 여전히 로그만 남긴다 —
`trading_coord._reduce_position`이 예외를 던지면(브로커/게이트 예외) 손절의
부분청산 시도가 무방비로 실패하고도 통지가 없다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _position(quantity=1315):
    position = MagicMock()
    position.ticker = "094840"
    position.stock_name = "슈프리마에이치큐"
    position.quantity = quantity
    position.current_price = 13060
    position.close_gate_denied_notified = False
    position.liquidity_cap_blocked_notified = False
    return position


# -------------------------------------------
# Important 2 — _execute_close_position
# -------------------------------------------


@pytest.mark.parametrize(
    "reason,expected_label",
    [
        ("stop_loss", "방어청산(손절)"),
        ("take_profit", "방어청산(익절)"),
        ("agent_decision", "자율(에이전트 합의)"),
        ("agent_decision_reduce", "자율(에이전트 합의)"),
        ("some_future_reason_no_one_mapped_yet", "방어청산"),
    ],
)
async def test_close_position_threads_accurate_source_label(reason, expected_label):
    """RED(회귀 전): _close_position이 reason 인자를 안 받아 호출자와 무관하게
    "User-initiated close"만 나갔다 — 자율 손절/익절이 폰에 "사람이 한 것"으로
    표시된 근본 원인. GREEN: 트리거별 정확한 한국어 라벨이 코디네이터로
    넘어간다(알려지지 않은 reason은 "사람이 아니다"라는 사실만 보존해
    "방어청산"으로 안전 강등)."""
    from services.agent_chat.position_manager import PositionManager
    from services.autonomy.gate import GateDecision

    pm = PositionManager()
    position = _position()

    gate = GateDecision(allowed=True, reason="ok", check="all")
    captured = {}

    async def _close(ticker, decision_id=None, reason=None, **kwargs):
        captured["reason"] = reason
        return MagicMock(status="filled", filled_quantity=position.quantity)

    trading_coord = MagicMock()
    trading_coord._close_position = _close

    with patch("services.autonomy.check_autonomy", new=AsyncMock(return_value=gate)), \
         patch("app.dependencies.get_trading_coordinator", new=AsyncMock(return_value=trading_coord)):
        await pm._execute_close_position(position, reason)

    assert captured["reason"] == expected_label


# -------------------------------------------
# Important 2 — _execute_reduce_position
# -------------------------------------------


async def test_reduce_position_threads_accurate_source_label():
    from services.agent_chat.position_manager import PositionManager
    from services.autonomy.gate import GateDecision

    pm = PositionManager()
    position = _position(quantity=100)

    gate = GateDecision(allowed=True, reason="ok", check="all")
    captured = {}

    async def _reduce(ticker, quantity, decision_id=None, reason=None, **kwargs):
        captured["reason"] = reason
        return MagicMock(status="filled", filled_quantity=quantity)

    trading_coord = MagicMock()
    trading_coord._reduce_position = _reduce

    with patch("services.autonomy.check_autonomy", new=AsyncMock(return_value=gate)), \
         patch("app.dependencies.get_trading_coordinator", new=AsyncMock(return_value=trading_coord)):
        await pm._execute_reduce_position(position, 30, "agent_decision_reduce_partial")

    assert captured["reason"] == "자율(에이전트 합의)"


# -------------------------------------------
# 보너스 — _execute_reduce_position의 except에 실패 통지가 없던 갭
# (Task 7이 _execute_close_position에만 달았던 것과 같은 모양)
# -------------------------------------------


async def test_reduce_position_broker_exception_sends_alert():
    """RED(회귀 전): trading_coord._reduce_position이 예외를 던져도
    _execute_reduce_position의 except는 로그만 남기고 끝났다 — 부분청산
    시도가 무방비로 실패해도 아무도 몰랐다. GREEN: _execute_close_position과
    동일하게 _alert_execution_failed로 통지한다."""
    from services.agent_chat.position_manager import PositionManager
    from services.autonomy.gate import GateDecision

    pm = PositionManager()
    position = _position(quantity=100)

    gate = GateDecision(allowed=True, reason="ok", check="all")
    trading_coord = MagicMock()
    trading_coord._reduce_position = AsyncMock(side_effect=RuntimeError("broker down"))

    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_message = AsyncMock(return_value=True)

    with patch("services.autonomy.check_autonomy", new=AsyncMock(return_value=gate)), \
         patch("app.dependencies.get_trading_coordinator", new=AsyncMock(return_value=trading_coord)), \
         patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        await pm._execute_reduce_position(position, 30, "agent_decision_reduce_partial")

    notifier.send_message.assert_awaited_once()
    body = notifier.send_message.await_args.args[0]
    assert "094840" in body
    assert "확인" in body or "수동" in body


async def test_reduce_position_alert_failure_does_not_propagate():
    """통지까지 실패해도 집행 경로가 죽으면 안 된다(never-raise)."""
    from services.agent_chat.position_manager import PositionManager
    from services.autonomy.gate import GateDecision

    pm = PositionManager()
    position = _position(quantity=100)

    gate = GateDecision(allowed=True, reason="ok", check="all")
    trading_coord = MagicMock()
    trading_coord._reduce_position = AsyncMock(side_effect=RuntimeError("broker down"))

    with patch("services.autonomy.check_autonomy", new=AsyncMock(return_value=gate)), \
         patch("app.dependencies.get_trading_coordinator", new=AsyncMock(return_value=trading_coord)), \
         patch("services.telegram.get_telegram_notifier",
               new=AsyncMock(side_effect=RuntimeError("telegram down"))):
        await pm._execute_reduce_position(position, 30, "agent_decision_reduce_partial")
