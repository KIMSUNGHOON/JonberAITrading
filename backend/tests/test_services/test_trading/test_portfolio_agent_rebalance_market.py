"""S-3/S-4 (survival discipline): PortfolioAgent's rebalance SELL orders and
R-based buy-side sizing.

S-3 — rebalance SELL orders must submit as MARKET, not the OrderRequest
default of LIMIT — and must carry an explicit `price` (previously omitted
entirely, leaving `price=None`).

Real gap: `_check_rebalancing_needed`/`suggest_rebalancing` build their
rebalance `OrderRequest`s with no `order_type` (defaults to `OrderType.LIMIT`,
models.py) AND no `price` at all. Two problems this closes:

1. A LIMIT rebalance sell submitted with no price would (if a broker/mock
   ever honored the LIMIT semantics literally) be malformed — every other
   defensive-exit MARKET site (risk_monitor.py's `_execute_stop_loss`/
   `_execute_take_profit`, coordinator.py's `_close_position`/
   `_reduce_position`/`on_trade_approved`'s SELL/REDUCE main order, all S-3)
   sets BOTH `order_type=OrderType.MARKET` and an explicit `price` (the
   position's `current_price`, used as the mock/paper broker's fill-price
   fallback and the live Kiwoom fill-confirm's `fallback_price` — see
   order_agent.py `_simulate_order`/`_confirm_kiwoom_fill`) — MARKET orders
   never actually SEND this price to the broker, but every other MARKET site
   still populates it as a sane estimate.
2. A rebalance sell is itself a defensive/system-initiated liquidation of an
   UNRELATED position (freeing room for the trade actually approved) — same
   category as a stop-loss/take-profit trigger — so it belongs in the same
   MARKET convention, not LIMIT-at-a-stale-price.

Spec: docs/superpowers/specs/2026-07-19-survival-discipline-design.md §2 S-3.
"""

from services.trading.models import (
    AccountInfo,
    ManagedPosition,
    OrderSide,
    OrderType,
    RiskParameters,
    TradingState,
)
from services.trading.portfolio_agent import PortfolioAgent


def _agent(**risk_kwargs) -> PortfolioAgent:
    return PortfolioAgent(risk_params=RiskParameters(**risk_kwargs))


# -------------------------------------------
# 1) _check_rebalancing_needed (called from calculate_allocation's own
#    rebalance-room-check, and directly here for isolation)
# -------------------------------------------


def test_check_rebalancing_needed_sell_is_market_with_price():
    agent = _agent(max_total_stock_pct=0.5)
    account = AccountInfo(total_equity=10_000_000, available_cash=1_000_000, total_stock_value=6_000_000)
    positions = [
        ManagedPosition(
            ticker="000660",
            stock_name="SK하이닉스",
            quantity=50,
            avg_price=100_000,
            current_price=120_000,
        )
    ]

    # new_trade_amount pushes projected stock value well past max_stock_value
    # (10_000_000 * 0.5 = 5_000_000; current 6_000_000 already exceeds it).
    orders = agent._check_rebalancing_needed(account, positions, new_trade_amount=1_000_000)

    assert len(orders) == 1
    order = orders[0]
    assert order.ticker == "000660"
    assert order.order_type == OrderType.MARKET
    assert order.price == 120_000  # position.current_price, not None


# -------------------------------------------
# 2) suggest_rebalancing (the periodic over-allocation trim)
# -------------------------------------------


def test_suggest_rebalancing_sell_is_market_with_price():
    agent = _agent(max_single_position_pct=0.10)
    state = TradingState()
    state.account = AccountInfo(total_equity=10_000_000, available_cash=1_000_000, total_stock_value=3_000_000)
    state.positions = [
        ManagedPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=30,
            avg_price=90_000,
            current_price=100_000,  # 3,000,000 / 10,000,000 = 30% >> 10% max * 1.1
        )
    ]

    orders = agent.suggest_rebalancing(state)

    assert orders is not None
    assert len(orders) == 1
    order = orders[0]
    assert order.ticker == "005930"
    assert order.order_type == OrderType.MARKET
    assert order.price == 100_000  # position.current_price, not None


# =============================================================================
# S-4 (생존 규율, decision D4): R-based sizing — _calculate_max_position_value
# now takes entry_price/stop_loss and min()-combines the risk-bucket cap with
# r_sizing.r_cap_value's R-budget cap (smaller wins). Spec: docs/superpowers/
# specs/2026-07-19-survival-discipline-design.md §2 S-4.
# =============================================================================


def test_calculate_max_position_value_adopts_r_cap_when_smaller():
    """브리프 Step1 ②: R 캡이 기존(리스크버킷) 캡보다 작을 때 채택.

    5억 계좌, risk_score=1 (factor 1.0) -> 기존 캡 = 500,000,000*0.15 =
    75,000,000. entry=100,000/stop=90,000 (10% 거리) -> r_cap =
    500,000,000*0.0075/0.10 = 37,500,000 < 75,000,000 -> R 캡 채택.
    """
    agent = _agent()  # defaults: max_single_position_pct=0.15, risk_budget_pct=0.75
    value = agent._calculate_max_position_value(
        total_equity=500_000_000, risk_score=1, entry_price=100_000, stop_loss=90_000
    )
    assert value == 37_500_000


def test_calculate_max_position_value_keeps_existing_cap_when_r_cap_larger():
    """브리프 Step1 ②: R 캡이 기존 캡보다 클 때 기존 캡 유지(회귀).

    entry=100,000/stop=98,000 (2% 거리) -> r_cap = 500,000,000*0.0075/0.02 =
    187,500,000 > 75,000,000 기존 캡 -> 기존 캡 그대로.
    """
    agent = _agent()
    value = agent._calculate_max_position_value(
        total_equity=500_000_000, risk_score=1, entry_price=100_000, stop_loss=98_000
    )
    assert value == 75_000_000


def test_calculate_max_position_value_unaffected_when_stop_loss_none():
    """stop_loss=None(가드) -> R 캡 미적용, 기존(risk_score 버킷) 캡 그대로 —
    S-4 이전 호출부(스탑 없는 큐잉 트레이드 등)의 회귀 핀."""
    agent = _agent()
    value = agent._calculate_max_position_value(
        total_equity=500_000_000, risk_score=1, entry_price=100_000, stop_loss=None
    )
    assert value == 75_000_000
    # entry_price/stop_loss 둘 다 생략(기존 2-인자 호출)해도 동일해야 한다.
    value_no_kwargs = agent._calculate_max_position_value(total_equity=500_000_000, risk_score=1)
    assert value_no_kwargs == 75_000_000


# =============================================================================
# C1 (유동성 인지, 2026-07-27) — 리뷰 Important1 수정: 기존 그린 스위트는
# `apply_liquidity_cap`을 두 호출부에서 통째로 삭제해도 동일했다(mock client가
# TypeError를 내고 inner handler가 삼켜 adtv=None -> "adtv_unknown"으로만
# 흘렀기 때문). 아래는 mock 없이 adtv를 직접 인자로 넘겨 캡이 실제로
# 값을 바꾼다는 것을 증명한다.
# =============================================================================


def test_calculate_max_position_value_applies_liquidity_cap_when_binding():
    """adtv=20억(2e9) -> liquidity cap = 0.5% = 1000만원. 리스크버킷 캡
    (75,000,000)보다 훨씬 작아 캡이 실제로 바인딩해 반환값을 바꾼다.
    adtv=None 대조군은 캡 미적용(fail-open)으로 그대로 75,000,000."""
    agent = _agent()  # max_single_position_pct=0.15 기본

    capped = agent._calculate_max_position_value(
        total_equity=500_000_000, risk_score=1, adtv=2_000_000_000.0
    )
    assert capped == 10_000_000

    uncapped = agent._calculate_max_position_value(
        total_equity=500_000_000, risk_score=1, adtv=None
    )
    assert uncapped == 75_000_000


# -------------------------------------------
# End-to-end via calculate_allocation (public API) — proves the wiring, not
# just the private helper.
# -------------------------------------------


def _fresh_buy_account() -> AccountInfo:
    return AccountInfo(total_equity=500_000_000, available_cash=400_000_000, total_stock_value=0)


def test_buy_allocation_quantity_reflects_r_cap_when_tighter():
    agent = _agent()
    plan = agent.calculate_allocation(
        account=_fresh_buy_account(),
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.BUY,
        entry_price=100_000,
        risk_score=1,
        stop_loss=90_000,  # 10% distance -> r_cap=37,500,000 binds
        take_profit=120_000,
    )
    assert plan.quantity == 375
    assert plan.estimated_amount == 37_500_000
    assert plan.stop_loss == 90_000


def test_buy_allocation_quantity_unaffected_when_r_cap_looser():
    agent = _agent()
    plan = agent.calculate_allocation(
        account=_fresh_buy_account(),
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.BUY,
        entry_price=100_000,
        risk_score=1,
        stop_loss=98_000,  # 2% distance -> r_cap=187,500,000, looser than 75M
        take_profit=120_000,
    )
    assert plan.quantity == 750
    assert plan.estimated_amount == 75_000_000


def test_buy_allocation_quantity_regression_when_no_stop_loss():
    """스탑 없는 기존 호출부(예: 큐잉 트레이드 원복)와 동일 수치 — S-4가 R 캡을
    적용 못 해도(가드) 사이징 결과는 이전 그대로."""
    agent = _agent()
    plan = agent.calculate_allocation(
        account=_fresh_buy_account(),
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.BUY,
        entry_price=100_000,
        risk_score=1,
        stop_loss=None,
        take_profit=None,
    )
    assert plan.quantity == 750
    assert plan.estimated_amount == 75_000_000
