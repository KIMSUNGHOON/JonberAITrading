"""통지 광역화 Task 7: 집행 실패 통지.

손절 집행이 실패하면 포지션이 무방비로 남는다 — 체결 통지보다 급하다.
지금은 _execute_close_position의 예외가 auto_execute_failed 로그만 남기고
끝난다. 아무도 모른다.

실패 통지는 '무엇을 하라'를 담아야 한다. 상태만 알려주고 조치를 안 알려주면
운영자가 잘못된 복구를 한다(재시작 안전 아크에서 실제로 겪었다).

리뷰 수정(2026-07-30, Critical): 최초 구현은 `_execute_close_position`
자체를 통째로 모킹해 테스트했는데, 그 메서드는 자기 자신의 try/except로
모든 예외를 삼키고 절대 re-raise하지 않는다 — 그래서 `_auto_execute_event`의
except에 달았던 통지 호출은 실제로는 도달 불가능했다. 모킹이 바로 그
차단막(catch)을 우회해버려 테스트가 "핸들러가 동작한다"는 것만 증명하고
"핸들러에 도달 가능하다"는 것은 증명하지 못했다. 아래 재현성 테스트는
`_execute_close_position` 자신은 모킹하지 않고, 그 안에서 실제로 부르는
`check_autonomy`/`trading_coord._close_position`만 모킹해 진짜 catch 경로를
통과시킨다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _position():
    position = MagicMock()
    position.ticker = "094840"
    position.stock_name = "슈프리마에이치큐"
    position.quantity = 1315
    position.current_price = 13060
    position.close_gate_denied_notified = False
    position.liquidity_cap_blocked_notified = False
    return position


async def test_close_position_broker_failure_sends_alert():
    """진짜 실패 경로: 오토노미 게이트 통과 → 코디네이터 브로커 호출에서
    예외 → `_execute_close_position` 자신의 except가 그걸 잡고 통지한다.

    `_execute_close_position` 자체는 모킹하지 않는다 — 그걸 모킹하면 이
    메서드 자신의 catch를 우회해버려 통지 핸들러가 실제로 도달 가능한지
    증명하지 못한다(리뷰 Critical이 잡은 최초 구현의 결함).
    """
    from services.agent_chat.position_manager import PositionManager
    from services.autonomy.gate import GateDecision

    pm = PositionManager()
    position = _position()

    gate = GateDecision(allowed=True, reason="ok", check="all")
    trading_coord = MagicMock()
    trading_coord._close_position = AsyncMock(side_effect=RuntimeError("broker down"))

    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_message = AsyncMock(return_value=True)

    with patch("services.autonomy.check_autonomy", new=AsyncMock(return_value=gate)), \
         patch("app.dependencies.get_trading_coordinator", new=AsyncMock(return_value=trading_coord)), \
         patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        await pm._execute_close_position(position, "stop_loss")

    trading_coord._close_position.assert_awaited_once()
    notifier.send_message.assert_awaited_once()
    body = notifier.send_message.await_args.args[0]
    assert "094840" in body
    assert "손절" in body
    assert "확인" in body or "수동" in body, "조치 지시가 있어야 한다"


async def test_close_position_alert_failure_does_not_propagate():
    """통지까지 실패해도 집행 경로(진짜 catch 경로)가 죽으면 안 된다."""
    from services.agent_chat.position_manager import PositionManager
    from services.autonomy.gate import GateDecision

    pm = PositionManager()
    position = _position()

    gate = GateDecision(allowed=True, reason="ok", check="all")
    trading_coord = MagicMock()
    trading_coord._close_position = AsyncMock(side_effect=RuntimeError("broker down"))

    with patch("services.autonomy.check_autonomy", new=AsyncMock(return_value=gate)), \
         patch("app.dependencies.get_trading_coordinator", new=AsyncMock(return_value=trading_coord)), \
         patch("services.telegram.get_telegram_notifier",
               new=AsyncMock(side_effect=RuntimeError("telegram down"))):
        await pm._execute_close_position(position, "stop_loss")  # raise하지 않아야 한다


async def test_take_profit_failure_labels_as_take_profit_not_stop_loss():
    """리뷰 Minor: reason 문자열 직접 비교로 판별하므로 손절/익절이 절대
    섞이지 않는다."""
    from services.agent_chat.position_manager import PositionManager
    from services.autonomy.gate import GateDecision

    pm = PositionManager()
    position = _position()

    gate = GateDecision(allowed=True, reason="ok", check="all")
    trading_coord = MagicMock()
    trading_coord._close_position = AsyncMock(side_effect=RuntimeError("broker down"))

    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_message = AsyncMock(return_value=True)

    with patch("services.autonomy.check_autonomy", new=AsyncMock(return_value=gate)), \
         patch("app.dependencies.get_trading_coordinator", new=AsyncMock(return_value=trading_coord)), \
         patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        await pm._execute_close_position(position, "take_profit")

    body = notifier.send_message.await_args.args[0]
    assert "익절" in body
    assert "손절" not in body


# ---------------------------------------------------------------------------
# 유동성 캡 차단 통지 (Step 4) — 리뷰 Important 3: 최초 구현엔 테스트가
# 전혀 없었다.
# ---------------------------------------------------------------------------


def _add_position_mocks():
    """`_execute_add_position`이 유동성 캡 분기까지 도달하도록 gate/coordinator를
    구성한다."""
    from services.autonomy.gate import GateDecision
    from services.trading.coordinator import ORDER_STATUS_REJECTED_LIQUIDITY_CAP

    gate = GateDecision(allowed=True, reason="ok", check="all")
    result = MagicMock()
    result.status = ORDER_STATUS_REJECTED_LIQUIDITY_CAP
    trading_coord = MagicMock()
    trading_coord._add_to_position = AsyncMock(return_value=result)
    return gate, trading_coord


async def test_liquidity_cap_block_sends_alert_with_instruction():
    from services.agent_chat.position_manager import PositionManager

    pm = PositionManager()
    position = _position()
    gate, trading_coord = _add_position_mocks()

    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_message = AsyncMock(return_value=True)

    with patch("services.autonomy.check_autonomy", new=AsyncMock(return_value=gate)), \
         patch("app.dependencies.get_trading_coordinator", new=AsyncMock(return_value=trading_coord)), \
         patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        await pm._execute_add_position(position, 100, "test_add")

    notifier.send_message.assert_awaited_once()
    body = notifier.send_message.await_args.args[0]
    assert "094840" in body
    assert "유동성" in body
    # 리뷰 Important 1: 상태만 알리지 말고 조치 여부를 명시해야 한다.
    assert "조치" in body


async def test_liquidity_cap_block_is_throttled_once_per_episode():
    """리뷰 Important 2: close_gate_denied_notified와 동일하게 래치가 있어야
    한다 — 없으면 캡 초과 보유 종목이 토론 주기마다 재통지로 도배된다."""
    from services.agent_chat.position_manager import PositionManager

    pm = PositionManager()
    position = _position()
    gate, trading_coord = _add_position_mocks()

    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_message = AsyncMock(return_value=True)

    with patch("services.autonomy.check_autonomy", new=AsyncMock(return_value=gate)), \
         patch("app.dependencies.get_trading_coordinator", new=AsyncMock(return_value=trading_coord)), \
         patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        await pm._execute_add_position(position, 100, "test_add")
        await pm._execute_add_position(position, 100, "test_add")  # 같은 에피소드, 재통지 없어야

    notifier.send_message.assert_awaited_once()


async def test_liquidity_cap_block_alert_never_raises():
    from services.agent_chat.position_manager import PositionManager

    pm = PositionManager()
    position = _position()
    gate, trading_coord = _add_position_mocks()

    with patch("services.autonomy.check_autonomy", new=AsyncMock(return_value=gate)), \
         patch("app.dependencies.get_trading_coordinator", new=AsyncMock(return_value=trading_coord)), \
         patch("services.telegram.get_telegram_notifier",
               new=AsyncMock(side_effect=RuntimeError("telegram down"))):
        await pm._execute_add_position(position, 100, "test_add")  # raise하지 않아야 한다
