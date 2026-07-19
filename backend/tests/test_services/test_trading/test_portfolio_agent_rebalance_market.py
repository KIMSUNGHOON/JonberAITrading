"""S-3 (survival discipline): PortfolioAgent's rebalance SELL orders must
submit as MARKET, not the OrderRequest default of LIMIT — and must carry an
explicit `price` (previously omitted entirely, leaving `price=None`).

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
