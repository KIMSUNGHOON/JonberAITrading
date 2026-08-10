"""방어 매도(손절·익절) 재제출 가드 — G1/G2/G3.

2026-08-10 09:00 라이브 사고(089860). 로그 원문 순서:

    [RiskMonitor] Take-profit triggered: 6.6% (41600 >= 41462)
    [OrderAgent] Executing order: sell 361 @ 41600
    [Coordinator] Position 089860 reduced by 245; 116 remaining
    [ORDER] 미체결 잔량 추적 등록: 089860 (0005305:116주)
    [RiskMonitor] Take-profit triggered: 9.1% (42550)      ← 재발동
    [OrderAgent] Executing order: sell 116 @ 42550
    ❌ 800033 "모의투자 매도가능수량이 부족합니다"          ← 거부
    [Coordinator] Position removed: 089860
    [ORDER] 사후 매도 체결: 089860 116주 @ 41,743          ← 원래 주문 체결
    [RiskMonitor] Take-profit triggered: 10.0% (42900)     ← 또 재발동
    [OrderAgent] Executing order: sell 116 @ 42900
    ❌ 800033                                              ← 거부

기전: 부분체결 후 포지션이 축소된 수량으로 RiskMonitor에 재등록되는데,
가격이 여전히 익절선 위라 즉시 재발동한다. 그런데 그 수량은 미체결 주문이
브로커에서 이미 잡고 있어 매도가능수량이 0이다. 세 번째 발동은 포지션이
제거된 뒤(보유 0주)에 일어났다.

오늘은 익절이라 무해했다. 손절에서 같은 일이 나면 하락 국면에 거부가
반복되는 동안 실제 방어는 첫 주문 하나에만 의존하고, 거부가 Kiwoom
레이트리밋을 갉아먹는다.

세 관문(초크포인트 `ExecutionCoordinator._execute_order_from_monitor`,
그리고 두 번째 엔진 PositionManager가 지나는 `_close_position`/
`_reduce_position`):

  G1 no_position  — 보유하지 않은 것(포지션 없음/수량 0)을 팔지 않는다
  G2 pending_sell — 같은 종목의 미체결 SELL이 있으면 재제출하지 않는다
  G3 cooldown     — 같은 트리거가 틱마다 재발동하지 않는다(기본 30초)

🔴 안전 불변식: 어떤 관문도 진짜 손절을 **영구히** 막아선 안 된다.
아래 두 테스트가 그것을 고정한다 —
  * test_g2_releases_when_pending_order_fills
  * test_g3_releases_after_cooldown_elapses
그리고 회귀 가드(가장 중요) —
  * test_clean_stop_loss_still_submits
"""

from datetime import date

import pytest

import services.autonomy as autonomy_pkg
from services.autonomy import GateDecision
from services.kiwoom.models import FilledOrder
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import (
    ManagedPosition,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    StopLossMode,
)
from services.trading.pending_order_tracker import TrackedOrder

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.usefixtures("isolated_storage_service"),
]


TICKER = "089860"


# -------------------------------------------
# Helpers
# -------------------------------------------


async def _allow_gate(market, **kwargs):
    return GateDecision(allowed=True, reason="ok", check="all")


@pytest.fixture(autouse=True)
def _gate_allows(monkeypatch):
    """자율 게이트는 이 파일의 관심사가 아니다 — 항상 통과시킨다."""
    monkeypatch.setattr(autonomy_pkg, "check_autonomy", _allow_gate)


def _coordinator(quantity=361, current_price=41_600.0) -> ExecutionCoordinator:
    coord = ExecutionCoordinator(kiwoom_client=None)
    if quantity > 0:
        coord._add_position(
            ManagedPosition(
                ticker=TICKER,
                stock_name="비에이치아이",
                quantity=quantity,
                avg_price=39_000.0,
                current_price=current_price,
                stop_loss=37_000.0,
                take_profit=41_462.0,
                stop_loss_mode=StopLossMode.AGENT_AUTO,
            )
        )
    return coord


class _Recorder:
    """`_execute_order` 스텁 — 제출된 주문을 전부 기록한다."""

    def __init__(self, coord: ExecutionCoordinator, results=None):
        self.orders: list[OrderRequest] = []
        self._results = list(results or [])
        coord._execute_order = self  # type: ignore[assignment]

    async def __call__(self, order: OrderRequest) -> OrderResult:
        self.orders.append(order)
        if self._results:
            return self._results.pop(0)
        return _result(order, filled=order.quantity, status="filled")

    @property
    def count(self) -> int:
        return len(self.orders)


def _result(order, *, filled, status, order_id="0005305", avg_price=None):
    return OrderResult(
        order_id=order_id,
        ticker=order.ticker,
        side=order.side,
        requested_quantity=order.quantity,
        filled_quantity=filled,
        avg_price=avg_price if avg_price is not None else (order.price or 0),
        status=status,
    )


def _sell_order(quantity, price, reason="Take-profit auto-execution") -> OrderRequest:
    return OrderRequest(
        ticker=TICKER,
        stock_name="비에이치아이",
        side=OrderSide.SELL,
        quantity=quantity,
        price=price,
        order_type=OrderType.MARKET,
        reason=reason,
    )


def _pending_sell(remaining=116, total=361, ord_no="0005305") -> TrackedOrder:
    return TrackedOrder(
        ord_no=ord_no,
        ticker=TICKER,
        stock_name="비에이치아이",
        side="sell",
        total_quantity=total,
        filled_quantity=total - remaining,
        trade_date=date.today().strftime("%Y%m%d"),
    )


def _suppression_reasons(caplog) -> list[str]:
    out = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if "defensive_sell_suppressed" in msg:
            out.append(msg.split("reason=")[1].split()[0])
    return out


# -------------------------------------------
# 오늘의 실제 시퀀스 재현 (이것이 명세다)
# -------------------------------------------


async def test_live_089860_sequence_first_submits_second_and_third_suppressed(caplog):
    """2026-08-10 089860: 세 번의 익절 발동 중 1차만 제출되고 2·3차는 서로
    다른 사유로 억제된다."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=361)

    # 1차 발동: sell 361 @41600 → 245주만 부분체결, 116주는 미체결로 남는다.
    trigger1 = _sell_order(361, 41_600.0)
    rec = _Recorder(coord, results=[_result(trigger1, filled=245, status="partial")])

    assert await coord._execute_order_from_monitor(trigger1) is True
    assert rec.count == 1
    position = next(p for p in coord._state.positions if p.ticker == TICKER)
    assert position.quantity == 116  # "reduced by 245; 116 remaining"
    tracked = [o for o in coord.fill_tracker.tracking() if o.ticker == TICKER]
    assert len(tracked) == 1 and tracked[0].side == "sell"  # 미체결 잔량 추적 등록

    # 2차 발동: 가격이 여전히 익절선 위 → 즉시 재발동. 그 116주는 브로커가
    # 이미 잡고 있어 매도가능수량 0 (800033).
    assert await coord._execute_order_from_monitor(_sell_order(116, 42_550.0)) is False
    assert rec.count == 1  # 제출 안 됨

    # 원래 주문이 사후 체결되고(361 전량) 포지션이 사라진다.
    coord.fill_tracker.apply_fills([
        FilledOrder(
            ord_no="0005305", stk_cd=TICKER, stk_nm="비에이치아이",
            ccld_qty=361, ccld_uv=41_743, ccld_amt=361 * 41_743,
            ccld_dt="20260810", ccld_tm="090300", buy_sell_tp="1",
        )
    ])
    coord._apply_sell_position_delta(TICKER, 116, 41_743.0)
    assert not any(p.ticker == TICKER for p in coord._state.positions)

    # 3차 발동: 보유 0주인데 또 발동 → 억제.
    assert await coord._execute_order_from_monitor(_sell_order(116, 42_900.0)) is False
    assert rec.count == 1

    # 각각 다른 사유로 로그된다 — 침묵이 성공으로 오인되면 안 된다.
    assert _suppression_reasons(caplog) == ["pending_sell", "no_position"]


# -------------------------------------------
# G1 — 보유하지 않은 것을 팔지 않는다
# -------------------------------------------


async def test_g1_no_position_does_not_submit(caplog):
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=0)  # 포지션 없음
    rec = _Recorder(coord)

    assert await coord._execute_order_from_monitor(_sell_order(116, 42_900.0)) is False

    assert rec.count == 0
    assert _suppression_reasons(caplog) == ["no_position"]


async def test_g1_zero_quantity_position_does_not_submit(caplog):
    """수량 0으로 남은 유령 포지션도 팔 것이 없다."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=10)
    next(p for p in coord._state.positions if p.ticker == TICKER).quantity = 0
    rec = _Recorder(coord)

    assert await coord._execute_order_from_monitor(_sell_order(10, 42_900.0)) is False

    assert rec.count == 0
    assert _suppression_reasons(caplog) == ["no_position"]


# -------------------------------------------
# G2 — 이미 나가 있는 방어를 중복해서 내지 않는다
# -------------------------------------------


async def test_g2_pending_sell_does_not_submit(caplog):
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(_pending_sell())
    rec = _Recorder(coord)

    assert await coord._execute_order_from_monitor(_sell_order(116, 42_550.0)) is False

    assert rec.count == 0
    assert _suppression_reasons(caplog) == ["pending_sell"]


async def test_g2_pending_buy_does_not_suppress_a_sell():
    """같은 종목의 미체결 **BUY**는 매도가능수량을 잡지 않는다 — 억제 금지."""
    coord = _coordinator(quantity=116)
    pending_buy = _pending_sell()
    pending_buy.side = "buy"
    coord.fill_tracker.register(pending_buy)
    rec = _Recorder(coord)

    assert await coord._execute_order_from_monitor(_sell_order(116, 36_000.0)) is True
    assert rec.count == 1


async def test_g2_pending_sell_for_another_ticker_does_not_suppress():
    coord = _coordinator(quantity=116)
    other = _pending_sell(ord_no="OTHER")
    other.ticker = "005930"
    coord.fill_tracker.register(other)
    rec = _Recorder(coord)

    assert await coord._execute_order_from_monitor(_sell_order(116, 36_000.0)) is True
    assert rec.count == 1


async def test_g2_releases_when_pending_order_fills():
    """🔴 안전 불변식: 미체결이 체결되면 G2가 자동으로 풀린다. 영구 억제 금지."""
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(_pending_sell(remaining=116, total=361))
    rec = _Recorder(coord)

    # 억제 중
    assert await coord._execute_order_from_monitor(_sell_order(116, 42_550.0)) is False
    assert rec.count == 0

    # 미체결이 체결되면 tracking()에서 빠진다(status → FILLED).
    coord.fill_tracker.apply_fills([
        FilledOrder(
            ord_no="0005305", stk_cd=TICKER, stk_nm="비에이치아이",
            ccld_qty=361, ccld_uv=41_743, ccld_amt=361 * 41_743,
            ccld_dt="20260810", ccld_tm="090300", buy_sell_tp="1",
        )
    ])
    assert coord.fill_tracker.tracking() == []
    coord._last_defensive_sell_at.clear()  # G3와 독립적으로 G2만 본다

    # 다음 트리거는 제출된다.
    assert await coord._execute_order_from_monitor(_sell_order(116, 36_000.0)) is True
    assert rec.count == 1


async def test_g2_releases_when_pending_order_expires():
    """🔴 만료(expire_stale)로도 풀린다 — 체결되지 않은 주문이 영구 래치가
    되면 안 된다."""
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(_pending_sell())
    rec = _Recorder(coord)

    assert await coord._execute_order_from_monitor(_sell_order(116, 42_550.0)) is False

    coord.fill_tracker.expire_stale(None)  # 장 마감 관례: 전부 만료
    assert coord.fill_tracker.tracking() == []
    coord._last_defensive_sell_at.clear()

    assert await coord._execute_order_from_monitor(_sell_order(116, 36_000.0)) is True
    assert rec.count == 1


# -------------------------------------------
# G3 — 같은 트리거가 틱마다 재발동하지 않는다
# -------------------------------------------


async def test_g3_cooldown_blocks_immediate_resubmit(caplog):
    """G1/G2로 못 잡는 백스톱: 주문이 미체결 등록도 없이 즉시 거부되면
    포지션은 그대로 남아 트리거가 매 틱 재발동한다."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    first = _sell_order(116, 36_000.0, reason="Stop-loss auto-execution")
    # 거부 → 미체결 추적 등록도 없다(G2가 못 잡는 경우).
    rec = _Recorder(coord, results=[_result(first, filled=0, status="rejected")])

    assert await coord._execute_order_from_monitor(first) is True
    assert rec.count == 1
    assert coord.fill_tracker.tracking() == []  # G2는 여기서 무력하다

    # 다음 틱(쿨다운 이내) — 억제.
    assert await coord._execute_order_from_monitor(
        _sell_order(116, 35_900.0, reason="Stop-loss auto-execution")
    ) is False
    assert rec.count == 1
    assert _suppression_reasons(caplog) == ["cooldown"]


async def test_g3_releases_after_cooldown_elapses():
    """🔴 안전 불변식: 쿨다운은 반드시 시간으로 한정된다. 영구 래치 금지."""
    coord = _coordinator(quantity=116)
    first = _sell_order(116, 36_000.0, reason="Stop-loss auto-execution")
    rec = _Recorder(coord, results=[_result(first, filled=0, status="rejected")])

    await coord._execute_order_from_monitor(first)
    assert rec.count == 1
    assert await coord._execute_order_from_monitor(_sell_order(116, 35_900.0)) is False

    # 쿨다운이 지난 것으로 시계를 뒤로 민다.
    coord._last_defensive_sell_at[TICKER] -= coord._defensive_sell_cooldown_sec + 1.0

    assert await coord._execute_order_from_monitor(_sell_order(116, 35_800.0)) is True
    assert rec.count == 2


async def test_g3_is_per_ticker():
    """한 종목의 쿨다운이 다른 종목의 방어를 막으면 안 된다."""
    coord = _coordinator(quantity=116)
    coord._add_position(
        ManagedPosition(
            ticker="005930", stock_name="삼성전자", quantity=10,
            avg_price=70_000.0, current_price=65_000.0,
            stop_loss_mode=StopLossMode.AGENT_AUTO,
        )
    )
    first = _sell_order(116, 36_000.0)
    rec = _Recorder(coord, results=[_result(first, filled=0, status="rejected")])

    await coord._execute_order_from_monitor(first)

    other = OrderRequest(
        ticker="005930", stock_name="삼성전자", side=OrderSide.SELL,
        quantity=10, price=65_000.0, order_type=OrderType.MARKET,
        reason="Stop-loss auto-execution",
    )
    assert await coord._execute_order_from_monitor(other) is True
    assert rec.count == 2


# -------------------------------------------
# 손절도 동일하게 억제된다 (익절만 고친 게 아님)
# -------------------------------------------


@pytest.mark.parametrize("reason", ["Stop-loss auto-execution", "Take-profit auto-execution"])
async def test_stop_loss_and_take_profit_suppressed_identically(reason, caplog):
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(_pending_sell())
    rec = _Recorder(coord)

    submitted = await coord._execute_order_from_monitor(
        _sell_order(116, 36_000.0, reason=reason)
    )

    assert submitted is False
    assert rec.count == 0
    assert _suppression_reasons(caplog) == ["pending_sell"]


# -------------------------------------------
# 회귀 가드 (가장 중요) — 관문에 안 걸리는 정상 손절은 여전히 제출된다
# -------------------------------------------


async def test_clean_stop_loss_still_submits(caplog):
    """🔴 억제된 손절 = 무방비 포지션. 아무 관문에도 걸리지 않는 손절은
    반드시 그대로 제출돼야 한다."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=361)
    rec = _Recorder(coord)

    order = _sell_order(361, 36_000.0, reason="Stop-loss auto-execution")
    assert await coord._execute_order_from_monitor(order) is True

    assert rec.count == 1
    assert rec.orders[0].quantity == 361
    assert _suppression_reasons(caplog) == []
    # 전량 체결 → 포지션 제거(기존 리컨실 동작 불변).
    assert not any(p.ticker == TICKER for p in coord._state.positions)


async def test_gate_denied_does_not_start_cooldown():
    """게이트 거부는 제출이 아니다 — 쿨다운을 시작시키면 게이트가 풀린 직후
    30초를 더 무방비로 만든다."""
    coord = _coordinator(quantity=116)
    rec = _Recorder(coord)

    async def _deny(market, **kwargs):
        return GateDecision(allowed=False, reason="denied", check="market_mode")

    import services.autonomy as ap
    original = ap.check_autonomy
    ap.check_autonomy = _deny
    try:
        assert await coord._execute_order_from_monitor(_sell_order(116, 36_000.0)) is False
    finally:
        ap.check_autonomy = original

    assert rec.count == 0
    assert TICKER not in coord._last_defensive_sell_at

    # 게이트가 풀리면 즉시 제출된다.
    assert await coord._execute_order_from_monitor(_sell_order(116, 35_900.0)) is True
    assert rec.count == 1


# -------------------------------------------
# 이중 엔진 — PositionManager가 지나는 _close_position/_reduce_position
# -------------------------------------------


async def test_close_position_defensive_suppressed_by_pending_sell(caplog):
    """PositionManager의 30초 틱(`_execute_close_position` → `_close_position`)도
    같은 결함을 갖는다 — 미체결 SELL이 있는데 전량 청산을 또 낸다."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(_pending_sell())
    rec = _Recorder(coord)

    result = await coord._close_position(TICKER, defensive=True, reason="자율 손절")

    assert result is None
    assert rec.count == 0
    assert _suppression_reasons(caplog) == ["pending_sell"]
    # 억제해도 포지션은 유지된다(무방비 방치 아님 — 미체결 주문이 방어 중).
    assert any(p.ticker == TICKER for p in coord._state.positions)


async def test_close_position_defensive_cooldown(caplog):
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    order_stub = _sell_order(116, 41_600.0)
    rec = _Recorder(coord, results=[_result(order_stub, filled=0, status="rejected")])

    assert await coord._close_position(TICKER, defensive=True) is not None
    assert rec.count == 1

    assert await coord._close_position(TICKER, defensive=True) is None
    assert rec.count == 1
    assert _suppression_reasons(caplog) == ["cooldown"]

    coord._last_defensive_sell_at[TICKER] -= coord._defensive_sell_cooldown_sec + 1.0
    assert await coord._close_position(TICKER, defensive=True) is not None
    assert rec.count == 2


async def test_close_position_human_path_is_not_suppressed():
    """사람이 직접 누른 청산(handle_alert_action / REST)은 억제 대상이 아니다 —
    `defensive` 기본값 False로 기존 동작이 바이트 단위로 보존된다."""
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(_pending_sell())
    rec = _Recorder(coord)

    result = await coord._close_position(TICKER)  # defensive 미지정

    assert result is not None
    assert rec.count == 1


async def test_reduce_position_defensive_suppressed_by_pending_sell(caplog):
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=361)
    coord.fill_tracker.register(_pending_sell())
    rec = _Recorder(coord)

    result = await coord._reduce_position(TICKER, 100, defensive=True)

    assert result is None
    assert rec.count == 0
    assert _suppression_reasons(caplog) == ["pending_sell"]


async def test_reduce_position_defensive_clean_still_submits():
    """회귀 가드: 관문에 안 걸리는 축소는 그대로 제출된다."""
    coord = _coordinator(quantity=361)
    rec = _Recorder(coord)

    result = await coord._reduce_position(TICKER, 100, defensive=True)

    assert result is not None
    assert rec.count == 1
    assert rec.orders[0].quantity == 100


async def test_position_manager_close_passes_defensive_flag(monkeypatch):
    """배선 확인: PositionManager의 자율 청산이 실제로 `defensive=True`를
    넘기는지 — 넘기지 않으면 두 번째 엔진은 여전히 무방비다."""
    from unittest.mock import AsyncMock

    import app.dependencies as deps
    from services.agent_chat.position_manager import PositionManager

    pm = PositionManager()
    coord_stub = AsyncMock()
    coord_stub._close_position = AsyncMock(return_value=OrderResult(
        order_id="X", ticker=TICKER, side=OrderSide.SELL,
        requested_quantity=116, filled_quantity=116, avg_price=41_600, status="filled",
    ))
    monkeypatch.setattr(deps, "get_trading_coordinator", AsyncMock(return_value=coord_stub))

    position = pm.add_position(
        ticker=TICKER, stock_name="비에이치아이", quantity=116,
        avg_price=39_000.0, current_price=41_600.0,
        stop_loss=37_000.0, take_profit=41_462.0,
    )

    await pm._execute_close_position(position, "stop_loss")

    coord_stub._close_position.assert_awaited_once()
    assert coord_stub._close_position.await_args.kwargs.get("defensive") is True
