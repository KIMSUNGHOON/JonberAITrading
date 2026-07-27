"""자율 ADD 경로의 유동성 캡 (2026-07-27 유동성 인지 아크 후속).

배경: 진입 BUY는 C1 사이징 캡(ADTV의 0.5%)을 받지만, 자율 추가매수
(`PositionManager._execute_add_position` -> `coordinator._add_to_position`)는
`add_quantity = round(보유수량 * add_position_pct)`로 ADTV와 무관하게 산정돼
캡을 완전히 우회했다. 진입이 0.5%를 지켜도 ADD가 천장을 넘는 유일한
exposure-increasing 경로였다.

캡 기준은 **추가분이 아니라 총 포지션**이다:
    allowed_add_notional = max(0, ADTV * 0.005 - 현재_보유_평가액)
추가분에만 캡을 걸면 매번 캡만큼 더 살 수 있어 천장을 영원히 넘는다
(라이브 094840 실측: ADTV 5.3억 -> 캡 265만원인데 이미 1,729만원 보유 = 6.5배).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.trading.models import (
    ManagedPosition,
    OrderResult,
    OrderSide,
    PositionStatus,
)

억 = 100_000_000.0


def _position(ticker="094840", qty=1315, price=13_150.0):
    return ManagedPosition(
        ticker=ticker,
        stock_name=ticker,
        quantity=qty,
        avg_price=price,
        current_price=price,
        stop_loss=price * 0.95,
        take_profit=price * 1.10,
        status=PositionStatus.FILLED,
        risk_score=3,
    )


def _fill(qty, price=13_150.0):
    return OrderResult(
        order_id="test-order",
        ticker="094840",
        side=OrderSide.BUY,
        requested_quantity=qty,
        filled_quantity=qty,
        avg_price=price,
        status="filled",
    )


@pytest.fixture
def coord():
    """_add_to_position만 실행 가능한 최소 coordinator."""
    from services.trading.coordinator import ExecutionCoordinator

    c = ExecutionCoordinator.__new__(ExecutionCoordinator)
    c._state = MagicMock()
    c._state.positions = [_position()]
    c._execute_order = AsyncMock(return_value=_fill(0))
    c._add_position = MagicMock()
    c.portfolio_agent = MagicMock()
    return c


# ---------------------------------------------------------------------------
# 캡이 총 포지션 기준으로 적용되는가
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_blocked_when_holding_already_exceeds_cap(coord):
    """라이브 094840 시나리오 — ADTV 5.3억(캡 265만원)인데 1,729만원 보유.

    이미 캡의 6.5배라 허용 ADD는 0이어야 하고, 주문이 아예 나가면 안 된다.
    """
    coord.portfolio_agent._resolve_adtv = AsyncMock(return_value=5.3 * 억)

    result = await coord._add_to_position("094840", quantity=100)

    assert result is None
    coord._execute_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_clamped_to_remaining_headroom(coord):
    """여유가 있으면 그 여유만큼만 산다.

    ADTV 200억 -> 캡 1억원. 보유 1,729만원이므로 여유 8,271만원.
    현재가 13,150원이면 6,290주까지 가능한데 1,000주 요청은 그대로 통과.
    """
    coord.portfolio_agent._resolve_adtv = AsyncMock(return_value=200 * 억)
    coord._execute_order = AsyncMock(return_value=_fill(1000))

    await coord._add_to_position("094840", quantity=1000)

    coord._execute_order.assert_awaited_once()
    assert coord._execute_order.await_args.args[0].quantity == 1000


@pytest.mark.asyncio
async def test_add_partially_clamped(coord):
    """요청이 여유를 넘으면 여유만큼으로 깎인다.

    ADTV 40억 -> 캡 2,000만원(20,000,000).
    보유 1315주 x 13,150 = 17,292,250 -> 여유 2,707,750.
    2,707,750 / 13,150 = 205.91 -> int() = 205주.
    1,000주 요청은 205주로 클램프된다(내림이라 캡을 절대 넘지 않는다).
    """
    coord.portfolio_agent._resolve_adtv = AsyncMock(return_value=40 * 억)
    coord._execute_order = AsyncMock(return_value=_fill(205))

    await coord._add_to_position("094840", quantity=1000)

    coord._execute_order.assert_awaited_once()
    assert coord._execute_order.await_args.args[0].quantity == 205
    # 클램프 후 총 포지션이 캡을 넘지 않는지 직접 확인
    assert (1315 + 205) * 13_150 <= 40 * 억 * 0.005


# ---------------------------------------------------------------------------
# fail-open과 킬스위치
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_proceeds_when_adtv_unknown(coord):
    """ADTV를 모르면 캡을 적용하지 않는다(fail-open) — C1과 동일 규약.

    ADD는 이미 check_autonomy(BUY) 게이트를 통과한 요청이고, 여기서 막으면
    조회 실패가 곧 포지션 관리 정지가 된다.
    """
    coord.portfolio_agent._resolve_adtv = AsyncMock(return_value=None)
    coord._execute_order = AsyncMock(return_value=_fill(100))

    await coord._add_to_position("094840", quantity=100)

    coord._execute_order.assert_awaited_once()
    assert coord._execute_order.await_args.args[0].quantity == 100


@pytest.mark.asyncio
async def test_add_never_raises_when_resolve_adtv_explodes(coord):
    """ADTV 조회가 예외를 던져도 ADD 경로가 죽지 않는다."""
    coord.portfolio_agent._resolve_adtv = AsyncMock(side_effect=RuntimeError("boom"))
    coord._execute_order = AsyncMock(return_value=_fill(100))

    await coord._add_to_position("094840", quantity=100)

    coord._execute_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_killswitch_off_skips_cap(coord):
    """LIQUIDITY_SIZING_CAP_ENABLED=False면 캡을 건너뛴다(부분 롤백)."""
    coord.portfolio_agent._resolve_adtv = AsyncMock(return_value=5.3 * 억)
    coord._execute_order = AsyncMock(return_value=_fill(100))

    with patch("services.trading.coordinator.get_settings") as gs:
        gs.return_value.LIQUIDITY_SIZING_CAP_ENABLED = False
        await coord._add_to_position("094840", quantity=100)

    coord._execute_order.assert_awaited_once()
    coord.portfolio_agent._resolve_adtv.assert_not_awaited()


# ---------------------------------------------------------------------------
# 기존 동작 무회귀
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_position_still_returns_none(coord):
    """추적하지 않는 종목은 캡 이전에 기존 가드가 먼저 잡는다."""
    coord.portfolio_agent._resolve_adtv = AsyncMock(return_value=200 * 억)

    result = await coord._add_to_position("999999", quantity=100)

    assert result is None
    coord.portfolio_agent._resolve_adtv.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_positive_quantity_still_returns_none(coord):
    """비양수 수량도 캡 이전에 기존 가드가 먼저 잡는다."""
    coord.portfolio_agent._resolve_adtv = AsyncMock(return_value=200 * 억)

    result = await coord._add_to_position("094840", quantity=0)

    assert result is None
    coord.portfolio_agent._resolve_adtv.assert_not_awaited()
