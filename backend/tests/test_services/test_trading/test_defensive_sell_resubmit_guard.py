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

from datetime import date, datetime, timedelta

import pytest

import services.autonomy as autonomy_pkg
from services.autonomy import GateDecision
from services.kiwoom.models import FilledOrder
from services.trading.coordinator import (
    DEFENSIVE_SELL_PENDING_MAX_AGE_SEC,
    ORDER_STATUS_SUPPRESSED_DEFENSIVE_RESUBMIT,
    ExecutionCoordinator,
)
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


def _pending_sell(
    remaining=116, total=361, ord_no="0005305", age_seconds=0.0
) -> TrackedOrder:
    return TrackedOrder(
        ord_no=ord_no,
        ticker=TICKER,
        stock_name="비에이치아이",
        side="sell",
        total_quantity=total,
        filled_quantity=total - remaining,
        placed_at=datetime.now() - timedelta(seconds=age_seconds),
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

    # 리뷰 Important 2: `None`이 아니라 **구별 가능한** 결과다 — 호출자의
    # None 분기는 "원장 불일치"만 뜻하므로 허위 desync 경보가 나간다.
    assert result is not None
    assert result.status == ORDER_STATUS_SUPPRESSED_DEFENSIVE_RESUBMIT
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


# -------------------------------------------
# 리뷰 Important 3 — G2 나이 상한 (유일하게 남았던 무방비 창)
# -------------------------------------------
#
# `TRACKING` → 종료 상태로 가는 길은 실질적으로 둘뿐이다: ka10076 누적 체결
# (apply_fills → FILLED)과 장 마감/날짜 경과(expire_stale → EXPIRED).
# `TrackedOrderStatus.CANCELLED`는 프로덕션 어디서도 대입되지 않고, 미체결
# 조회(ka10075)도 추적기에 배선돼 있지 않다. 따라서 접수는 됐는데 체결로
# 대사되지 않는 매도(실 KRX 시장가 잔량 자동 취소 / ord_no 불일치 / pending
# 등록 후 사후 거부)는 마감까지 TRACKING으로 남아 그 종목의 모든 방어 매도를
# 억제한다. 나이 상한이 그 창을 닫는다.


async def test_g2_ignores_stale_pending_sell_and_submits(caplog):
    """상한을 넘긴 미체결 SELL은 억제 근거로 쓰지 않는다 — 제출을 허용한다.

    최악의 결과는 800033 거부 1회(= 수정 전과 같은 동작)인 반면, 상한이
    없으면 결과는 마감까지 무방비다."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(
        _pending_sell(age_seconds=DEFENSIVE_SELL_PENDING_MAX_AGE_SEC + 1)
    )
    rec = _Recorder(coord)

    submitted = await coord._execute_order_from_monitor(
        _sell_order(116, 36_000.0, reason="Stop-loss auto-execution")
    )

    assert submitted is True
    assert rec.count == 1
    assert _suppression_reasons(caplog) == []
    # 구별되는 관측 포인트 — 라이브에서 이 로그를 세면 된다.
    stale = [r.getMessage() for r in caplog.records
             if "defensive_sell_stale_pending_ignored" in r.getMessage()]
    assert len(stale) == 1
    assert "ord_no=0005305" in stale[0]
    assert "age_seconds=" in stale[0]
    # 낡은 주문은 추적기에서 지우지 않는다 — 사후 체결이 오면
    # apply_fills가 여전히 정상 대사해야 한다.
    assert len(coord.fill_tracker.tracking()) == 1


async def test_g2_still_suppresses_pending_sell_within_age_cap(caplog):
    """회귀 가드: 상한이 너무 짧아 **정상적으로 작동 중인** 주문을 무시하면
    안 된다. 라이브(089860)에서 부분체결 잔량은 약 90초 뒤에 사후 체결됐다 —
    그 시점에 재제출을 허용했다면 800033을 자초했을 것이다."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(_pending_sell(age_seconds=90))
    rec = _Recorder(coord)

    assert await coord._execute_order_from_monitor(_sell_order(116, 36_000.0)) is False
    assert rec.count == 0
    assert _suppression_reasons(caplog) == ["pending_sell"]


async def test_g2_age_cap_is_per_order_not_per_ticker():
    """낡은 주문 하나가 있어도 **신선한** 미체결 SELL이 함께 있으면 억제는
    유지된다 — 상한은 주문 단위 판정이지 종목 단위 해제가 아니다."""
    coord = _coordinator(quantity=300)
    coord.fill_tracker.register(
        _pending_sell(ord_no="OLD", age_seconds=DEFENSIVE_SELL_PENDING_MAX_AGE_SEC + 1)
    )
    coord.fill_tracker.register(_pending_sell(ord_no="FRESH", age_seconds=5))
    rec = _Recorder(coord)

    assert await coord._execute_order_from_monitor(_sell_order(300, 36_000.0)) is False
    assert rec.count == 0


# -------------------------------------------
# 리뷰 Important 2 — 억제가 허위 Telegram 경보를 내면 안 된다
# -------------------------------------------
#
# 2026-07-28 선례: ADD 유동성 캡이 0주에 None을 돌려주자 호출자가 "원장
# 불일치"로 오분류해 🚨 허위 경보를 반복했고,
# `ORDER_STATUS_REJECTED_LIQUIDITY_CAP`라는 구별 가능한 반환으로 봉합했다.
# reduce 억제도 정확히 같은 모양이라 같은 방식을 쓴다.


async def test_reduce_suppression_returns_distinguishable_result_not_none():
    """`None`은 호출자에게 오직 '원장에 포지션 없음'을 뜻한다 — 억제는 그것과
    구별돼야 한다."""
    coord = _coordinator(quantity=361)
    coord.fill_tracker.register(_pending_sell())
    rec = _Recorder(coord)

    result = await coord._reduce_position(TICKER, 100, defensive=True)

    assert result is not None, "None이면 호출자가 원장 불일치로 오진한다"
    assert result.status == ORDER_STATUS_SUPPRESSED_DEFENSIVE_RESUBMIT
    assert "pending_sell" in (result.message or "")
    assert rec.count == 0
    # 원장 불일치(진짜 None)와의 대조군은 아래 별도 테스트.


async def test_reduce_returns_none_only_for_real_ledger_desync():
    """회귀 가드: 진짜 원장 불일치는 여전히 None이어야 한다 — 그래야 desync
    통지가 살아 있다."""
    coord = _coordinator(quantity=0)  # 코디네이터 원장에 포지션 없음
    _Recorder(coord)

    assert await coord._reduce_position(TICKER, 100, defensive=True) is None


async def test_position_manager_reduce_suppression_sends_no_false_alert(monkeypatch):
    """PM 쪽 종단: 억제 결과를 받으면 desync/미체결 통지를 **둘 다** 보내지
    않고, 감시 수량도 건드리지 않는다."""
    from unittest.mock import AsyncMock

    import app.dependencies as deps
    from services.agent_chat.position_manager import PositionManager
    from services.trading.models import OrderResult as _OR

    pm = PositionManager()
    position = pm.add_position(
        ticker=TICKER, stock_name="비에이치아이", quantity=116,
        avg_price=39_000.0, current_price=41_600.0,
    )

    coord_stub = AsyncMock()
    coord_stub._reduce_position = AsyncMock(return_value=_OR(
        order_id="", ticker=TICKER, side=OrderSide.SELL,
        requested_quantity=30, filled_quantity=0, avg_price=0,
        status=ORDER_STATUS_SUPPRESSED_DEFENSIVE_RESUBMIT,
        message="방어 매도 재제출 가드 — pending_sell",
    ))
    monkeypatch.setattr(deps, "get_trading_coordinator", AsyncMock(return_value=coord_stub))

    pm._notify_reduce_ledger_desync = AsyncMock()
    pm._notify_reduce_unfilled = AsyncMock()

    await pm._execute_reduce_position(position, 30, "agent_decision_reduce_partial")

    pm._notify_reduce_ledger_desync.assert_not_awaited()
    pm._notify_reduce_unfilled.assert_not_awaited()
    assert pm._positions[TICKER].quantity == 116  # 수량 불변


async def test_position_manager_reduce_desync_still_alerts(monkeypatch):
    """회귀 가드(가장 중요): 진짜 원장 불일치(None)는 여전히 경보를 낸다 —
    억제 분기가 desync 감지를 삼키면 안 된다."""
    from unittest.mock import AsyncMock

    import app.dependencies as deps
    from services.agent_chat.position_manager import PositionManager

    pm = PositionManager()
    position = pm.add_position(
        ticker=TICKER, stock_name="비에이치아이", quantity=116,
        avg_price=39_000.0, current_price=41_600.0,
    )

    coord_stub = AsyncMock()
    coord_stub._reduce_position = AsyncMock(return_value=None)
    monkeypatch.setattr(deps, "get_trading_coordinator", AsyncMock(return_value=coord_stub))
    pm._notify_reduce_ledger_desync = AsyncMock()

    await pm._execute_reduce_position(position, 30, "agent_decision_reduce_partial")

    pm._notify_reduce_ledger_desync.assert_awaited_once()


async def test_position_manager_reduce_passes_defensive_flag(monkeypatch):
    """M6 대칭 테스트: close뿐 아니라 reduce 배선도 고정한다 — 이 리포는
    '한쪽만 고쳐 다른 쪽에서 재발' 이력이 여러 번이다."""
    from unittest.mock import AsyncMock

    import app.dependencies as deps
    from services.agent_chat.position_manager import PositionManager
    from services.trading.models import OrderResult as _OR

    pm = PositionManager()
    position = pm.add_position(
        ticker=TICKER, stock_name="비에이치아이", quantity=116,
        avg_price=39_000.0, current_price=41_600.0,
    )

    coord_stub = AsyncMock()
    coord_stub._reduce_position = AsyncMock(return_value=_OR(
        order_id="R", ticker=TICKER, side=OrderSide.SELL,
        requested_quantity=30, filled_quantity=30, avg_price=41_600, status="filled",
    ))
    monkeypatch.setattr(deps, "get_trading_coordinator", AsyncMock(return_value=coord_stub))

    await pm._execute_reduce_position(position, 30, "agent_decision_reduce_partial")

    coord_stub._reduce_position.assert_awaited_once()
    assert coord_stub._reduce_position.await_args.kwargs.get("defensive") is True


# -------------------------------------------
# 리뷰 M4 — 억제 로그 에피소드 래치
# -------------------------------------------
#
# RiskMonitor는 1초 틱이라 래치가 없으면 3분짜리 G2 에피소드 하나가 WARNING
# 180줄을 만든다. 이 리포에는 회전 없는 FileHandler로 35GB 단일 로그를 만든
# 이력이 있다. 단, 어떤 에피소드도 WARNING 없이 지나가서는 안 된다.


async def test_suppression_logs_warning_once_per_episode(caplog):
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(_pending_sell())
    rec = _Recorder(coord)

    for _ in range(10):
        assert await coord._execute_order_from_monitor(
            _sell_order(116, 36_000.0)
        ) is False

    assert rec.count == 0  # 억제는 10회 전부 유효
    assert _suppression_reasons(caplog) == ["pending_sell"]  # WARNING은 1회


async def test_suppression_logs_again_when_reason_changes(caplog):
    """사유 전이(pending_sell → no_position)는 그 자체가 정보다 — 삼키면
    안 된다."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(_pending_sell())
    _Recorder(coord)

    await coord._execute_order_from_monitor(_sell_order(116, 36_000.0))
    await coord._execute_order_from_monitor(_sell_order(116, 36_000.0))
    coord._remove_position(TICKER)
    await coord._execute_order_from_monitor(_sell_order(116, 36_000.0))
    await coord._execute_order_from_monitor(_sell_order(116, 36_000.0))

    assert _suppression_reasons(caplog) == ["pending_sell", "no_position"]


async def test_suppression_latch_rearms_after_release(caplog):
    """🔴 억제가 풀렸다가 다시 걸리면 반드시 다시 WARNING이 나간다 — 래치가
    영구히 침묵하면 안 된다."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(_pending_sell())
    rec = _Recorder(coord)

    await coord._execute_order_from_monitor(_sell_order(116, 36_000.0))  # 억제 #1

    # 미체결이 만료돼 억제가 풀리고 실제로 제출된다 → 래치 재무장.
    coord.fill_tracker.expire_stale(None)
    coord._last_defensive_sell_at.clear()
    assert await coord._execute_order_from_monitor(_sell_order(116, 36_000.0)) is True
    assert rec.count == 1

    # 새 미체결 SELL → 새 에피소드 → 다시 WARNING.
    coord._add_position(
        ManagedPosition(
            ticker=TICKER, stock_name="비에이치아이", quantity=116,
            avg_price=39_000.0, current_price=41_600.0,
            stop_loss_mode=StopLossMode.AGENT_AUTO,
        )
    )
    coord.fill_tracker.register(_pending_sell(ord_no="SECOND"))
    await coord._execute_order_from_monitor(_sell_order(116, 36_000.0))

    assert _suppression_reasons(caplog) == ["pending_sell", "pending_sell"]


# -------------------------------------------
# 리뷰 2라운드 Important 1 — 진짜 원장 불일치 경보를 삼키면 안 된다
# -------------------------------------------
#
# `_reduce_position`은 position이 None이면 이미 위에서 None을 돌려준다. 따라서
# 여기까지 와서 G1(`no_position`)이 발동하는 유일한 조건은 **원장에 포지션이
# 있는데 quantity <= 0** — 180초 안에 자동 해제되는 일시 상태가 아니라 자가
# 치유되지 않는 진짜 원장 불일치(PM 116주 vs 코디네이터 0주)다.
# 브랜치 이전에는 `sell_qty = min(q, 0) <= 0` → None → desync 통지로 흘렀다.


async def test_reduce_zero_quantity_position_returns_none_not_suppressed():
    """🔴 G1 억제는 SUPPRESSED가 아니라 기존 `None` 계약으로 떨어져야 한다 —
    그래야 desync 통지가 살아 있다."""
    coord = _coordinator(quantity=116)
    next(p for p in coord._state.positions if p.ticker == TICKER).quantity = 0
    rec = _Recorder(coord)

    result = await coord._reduce_position(TICKER, 100, defensive=True)

    assert result is None, "SUPPRESSED로 돌려주면 진짜 원장 불일치 경보가 사라진다"
    assert rec.count == 0


async def test_position_manager_reduce_zero_quantity_still_alerts_desync(monkeypatch):
    """PM 종단: 코디네이터 수량이 0으로 어긋난 상태는 여전히 desync 경보를
    낸다(억제 분기가 삼키면 안 된다)."""
    from unittest.mock import AsyncMock

    import app.dependencies as deps
    from services.agent_chat.position_manager import PositionManager

    pm = PositionManager()
    position = pm.add_position(
        ticker=TICKER, stock_name="비에이치아이", quantity=116,
        avg_price=39_000.0, current_price=41_600.0,
    )

    # 실제 코디네이터를 쓴다 — 이 경로의 반환 계약 자체가 검증 대상이다.
    coord = _coordinator(quantity=116)
    next(p for p in coord._state.positions if p.ticker == TICKER).quantity = 0
    _Recorder(coord)
    monkeypatch.setattr(deps, "get_trading_coordinator", AsyncMock(return_value=coord))
    pm._notify_reduce_ledger_desync = AsyncMock()

    await pm._execute_reduce_position(position, 30, "agent_decision_reduce_partial")

    pm._notify_reduce_ledger_desync.assert_awaited_once()


# -------------------------------------------
# 리뷰 2라운드 Important 2 — stale 로그가 틱마다 나가면 안 된다
# -------------------------------------------


async def test_stale_pending_log_is_latched_per_order(caplog):
    """🔴 `defensive_sell_stale_pending_ignored`는 M4 래치 **밖**이라 1초 틱에서
    초당 1줄이 나갔다(≈0.9MB/시간·종목). ord_no 단위로 래치한다."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(
        _pending_sell(age_seconds=DEFENSIVE_SELL_PENDING_MAX_AGE_SEC + 1)
    )
    # 브로커가 거부해 포지션이 유지되게 한다 — 체결되면 G1(no_position)이 먼저
    # 잡아 G2 루프(=stale 판정 지점)까지 오지 않아 래치가 시험되지 않는다.
    # 이게 라이브의 실제 모양이기도 하다: 낡은 TRACKING이 남아 있고 트리거도
    # 살아 있는 상태.
    _rej = _result(_sell_order(116, 36_000.0), filled=0, status="rejected")
    rec = _Recorder(coord, results=[_rej] * 10)

    for _ in range(10):
        await coord._execute_order_from_monitor(_sell_order(116, 36_000.0))

    # 제출은 G3 쿨다운 때문에 1회지만, stale 판정은 10틱 전부 일어났다
    # (G2 루프가 G3보다 먼저 돌기 때문 — 리뷰가 지적한 바로 그 구간).
    assert rec.count == 1
    assert coord._state.positions, "포지션이 유지돼야 G2 루프를 반복해서 탄다"
    stale = [r for r in caplog.records
             if "defensive_sell_stale_pending_ignored" in r.getMessage()]
    assert len(stale) == 1, "틱마다 WARNING이 나가면 로그가 폭증한다(≈0.9MB/h·종목)"


async def test_stale_pending_log_rearms_for_a_new_order(caplog):
    """🔴 래치가 영구 침묵이면 안 된다 — 추적기에서 빠지면 재무장된다."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(
        _pending_sell(ord_no="OLD1", age_seconds=DEFENSIVE_SELL_PENDING_MAX_AGE_SEC + 1)
    )
    # 브로커가 거부해 포지션이 유지되게 한다 — 체결되면 G1(no_position)이 먼저
    # 잡아 두 번째 호출이 G2 루프까지 오지 않는다.
    _rej = _result(_sell_order(116, 36_000.0), filled=0, status="rejected")
    _Recorder(coord, results=[_rej, _rej])

    await coord._execute_order_from_monitor(_sell_order(116, 36_000.0))
    coord._last_defensive_sell_at.clear()  # G3는 이 테스트의 관심사가 아니다

    coord.fill_tracker.expire_stale(None)  # OLD1이 tracking()에서 빠진다
    coord.fill_tracker.register(
        _pending_sell(ord_no="OLD2", age_seconds=DEFENSIVE_SELL_PENDING_MAX_AGE_SEC + 1)
    )
    await coord._execute_order_from_monitor(_sell_order(116, 36_000.0))

    stale = [r.getMessage() for r in caplog.records
             if "defensive_sell_stale_pending_ignored" in r.getMessage()]
    assert len(stale) == 2
    assert "ord_no=OLD1" in stale[0] and "ord_no=OLD2" in stale[1]


async def test_stale_pending_log_once_across_reduce_delegation(caplog):
    """`_reduce_position`이 전량 클램프로 `_close_position`에 위임하면 같은
    제출에서 판정이 두 번 도는데, stale 로그는 한 줄이어야 한다."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(
        _pending_sell(age_seconds=DEFENSIVE_SELL_PENDING_MAX_AGE_SEC + 1)
    )
    rec = _Recorder(coord)

    # 요청 수량 >= 보유 → 전량 클램프 → _close_position 위임
    result = await coord._reduce_position(TICKER, 500, defensive=True)

    assert result is not None and rec.count == 1
    stale = [r for r in caplog.records
             if "defensive_sell_stale_pending_ignored" in r.getMessage()]
    assert len(stale) == 1


# -------------------------------------------
# 리뷰 2라운드 Minor 3 — 음수 age는 신뢰 불가 → stale
# -------------------------------------------


async def test_negative_age_is_treated_as_stale(caplog):
    """시계가 뒤로 튀어 `placed_at`이 미래가 되면 나이를 신뢰할 수 없다.
    이 브랜치의 비대칭 논증(최악 = 거부 1회 vs 무방비)대로 stale로 읽는다."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(_pending_sell(age_seconds=-3600))  # 1시간 미래
    rec = _Recorder(coord)

    assert await coord._execute_order_from_monitor(_sell_order(116, 36_000.0)) is True
    assert rec.count == 1
    assert _suppression_reasons(caplog) == []
    assert any("defensive_sell_stale_pending_ignored" in r.getMessage()
               for r in caplog.records)


# -------------------------------------------
# 리뷰 2라운드 M5 — 두 엔진이 각각 한 줄씩 남는다
# -------------------------------------------


async def test_suppression_warning_is_per_engine(caplog):
    """ticker만 키로 쓰면 먼저 온 엔진만 WARNING이고 다른 엔진은 DEBUG로만
    남는다 — "한쪽만 보고 다른 쪽을 놓친" 이력이 있는 리포에서는 관측 손실."""
    caplog.set_level("WARNING")
    coord = _coordinator(quantity=116)
    coord.fill_tracker.register(_pending_sell())
    _Recorder(coord)

    # 엔진 1: RiskMonitor
    await coord._execute_order_from_monitor(_sell_order(116, 36_000.0))
    # 엔진 2: PositionManager
    await coord._close_position(TICKER, defensive=True)
    # 각 엔진의 반복은 여전히 억제된다
    await coord._execute_order_from_monitor(_sell_order(116, 36_000.0))
    await coord._close_position(TICKER, defensive=True)

    messages = [r.getMessage() for r in caplog.records
                if "defensive_sell_suppressed" in r.getMessage()]
    assert len(messages) == 2
    assert any("source=risk_monitor" in m for m in messages)
    assert any("source=position_manager_close" in m for m in messages)


# -------------------------------------------
# 리뷰 2라운드 M6 — tz-aware placed_at이 손절을 죽이면 안 된다
# -------------------------------------------


async def test_tz_aware_placed_at_does_not_break_the_guard():
    """naive `now`와의 뺄셈이 TypeError를 던지면
    `_execute_order_from_monitor`에 except가 없어 **매 틱 손절이 통째로
    실패**한다. 오늘 도달 경로는 없지만 실패 양식이 치명적이라 정규화한다."""
    from datetime import timezone

    coord = _coordinator(quantity=116)
    tracked = _pending_sell(age_seconds=10)
    # 진짜 tz-aware 값(같은 순간을 UTC로 표현) — naive `now`와 그냥 빼면
    # TypeError다.
    tracked.placed_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    coord.fill_tracker.register(tracked)
    rec = _Recorder(coord)

    # 예외 없이 정상 판정돼야 한다(UTC 10초 전 = 상한 이내 → 억제).
    submitted = await coord._execute_order_from_monitor(_sell_order(116, 36_000.0))

    assert submitted is False
    assert rec.count == 0
